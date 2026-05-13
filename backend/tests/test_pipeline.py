# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Tests for the processing pipeline + transcription/extraction services.

Covers:

- End-to-end pipeline happy path (both external services mocked):
  uploaded -> transcribing -> analyzing -> completed, pain points persisted
  in severity DESC order.
- Failure paths: AssemblyAI error, malformed Claude output, quotes not
  in transcript -> dropped, < 3 verifiable quotes -> failed.
- Service-level coverage of :mod:`app.services.transcription` and
  :mod:`app.services.extraction` by patching their underlying SDK
  clients (no live API calls).
- Prompt caching: assert ``cache_control`` is set on the system block
  of the Anthropic call.

No live API traffic — every test patches either the
``transcription`` / ``extraction`` module callables (for pipeline
choreography tests) or the SDK clients themselves (for service tests).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.schemas.interview import InterviewStatus, InterviewType
from app.services import extraction as extraction_mod
from app.services import pipeline as pipeline_mod
from app.services import transcription as transcription_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_interview_row(
    db_session,
    *,
    status: InterviewStatus = InterviewStatus.uploaded,
    transcript_text: str | None = None,
) -> Interview:
    project = Project(name="pipeline-test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    interview = Interview(
        project_id=project.id,
        audio_path="/tmp/pipeline-test.m4a",
        audio_filename="pipeline-test.m4a",
        audio_duration_sec=78.4,
        type=InterviewType.problem_validation,
        demographics={
            "name": "X",
            "gender": "male",
            "age": 30,
            "income": "50k_100k",
            "marital_status": "single",
            "country": "US",
            "job_role": "engineer",
            "industry": "saas_software",
        },
        status=status,
        transcript_text=transcript_text,
    )
    db_session.add(interview)
    await db_session.commit()
    await db_session.refresh(interview)
    return interview


@pytest.fixture
def patch_async_session_maker(monkeypatch, db_session):
    """Force ``run_pipeline`` to use the test's transactional session.

    The pipeline opens its own ``async_session_maker()`` context, which
    would normally bypass the per-test SAVEPOINT. We patch it to yield
    the existing ``db_session`` so assertions can observe the same rows.
    """
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        pipeline_mod, "async_session_maker", lambda: _fake_session_ctx()
    )


# ---------------------------------------------------------------------------
# Pipeline choreography (mock the two service callables)
# ---------------------------------------------------------------------------


async def test_pipeline_happy_path_persists_pain_points_sorted_by_severity(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    mock_extraction,
    sample_transcript,
    sample_pain_points,
):
    iv = await _make_interview_row(db_session)

    await pipeline_mod.run_pipeline(iv.id)

    # Reload from DB.
    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.completed
    assert iv.processed_at is not None
    assert iv.error_message is None
    assert iv.transcript_text == sample_transcript["text"]
    assert iv.transcript_segments == sample_transcript["segments"]

    # External services were called exactly once.
    assert mock_transcription.await_count == 1
    assert mock_extraction.await_count == 1

    # Pain points landed, sorted severity DESC, created_at ASC.
    rows = (
        await db_session.execute(
            select(PainPoint)
            .where(PainPoint.interview_id == iv.id)
            .order_by(PainPoint.severity.desc(), PainPoint.created_at.asc())
        )
    ).scalars().all()
    assert len(rows) == len(sample_pain_points)
    sorted_expected = sorted(sample_pain_points, key=lambda p: -p["severity"])
    assert [r.severity for r in rows] == [p["severity"] for p in sorted_expected]


async def test_pipeline_marks_failed_when_transcription_raises(
    db_session,
    patch_async_session_maker,
    monkeypatch,
    mock_extraction,
):
    iv = await _make_interview_row(db_session)

    async def _boom(audio_path: Path) -> dict[str, Any]:
        raise RuntimeError("AssemblyAI exploded: audio is corrupt")

    monkeypatch.setattr(transcription_mod, "transcribe", _boom)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.failed
    assert iv.error_message is not None
    assert "AssemblyAI" in iv.error_message
    assert mock_extraction.await_count == 0


async def test_pipeline_marks_failed_when_extraction_raises(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    monkeypatch,
):
    iv = await _make_interview_row(db_session)

    async def _boom(transcript: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("Claude did not call the tool")

    monkeypatch.setattr(extraction_mod, "extract_pain_points", _boom)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.failed
    assert iv.error_message is not None
    assert "Claude" in iv.error_message


async def test_pipeline_drops_unverifiable_quotes_but_keeps_enough(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    monkeypatch,
    sample_pain_points,
):
    """One bogus quote is dropped; the remaining valid ones still persist."""
    iv = await _make_interview_row(db_session)

    bogus = {
        "text": "Hallucinated pain",
        "supporting_quote": "this string is nowhere in the transcript at all",
        "timestamp_start_sec": 0.0,
        "timestamp_end_sec": 1.0,
        "severity": 4,
    }

    async def _fake_extract(transcript: dict[str, Any]) -> list[dict[str, Any]]:
        return [*sample_pain_points, bogus]

    monkeypatch.setattr(extraction_mod, "extract_pain_points", _fake_extract)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.completed
    rows = (
        await db_session.execute(
            select(PainPoint).where(PainPoint.interview_id == iv.id)
        )
    ).scalars().all()
    # All four canned pain points stay; the bogus one is dropped.
    assert len(rows) == len(sample_pain_points)
    assert all("nowhere in the transcript" not in r.supporting_quote for r in rows)


async def test_pipeline_fails_when_too_few_verifiable_quotes(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    monkeypatch,
):
    """If only 1-2 quotes are verifiable, the interview is marked failed."""
    iv = await _make_interview_row(db_session)

    # Only one of these quotes is in sample_transcript.text verbatim.
    pain_points = [
        {
            "text": "Real one",
            "supporting_quote": "Honestly, it's a mess.",
            "timestamp_start_sec": 6.5,
            "timestamp_end_sec": 24.1,
            "severity": 5,
        },
        {
            "text": "Fake 1",
            "supporting_quote": "this is not in the transcript",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 3,
        },
        {
            "text": "Fake 2",
            "supporting_quote": "neither is this",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 3,
        },
    ]

    async def _fake_extract(transcript: dict[str, Any]) -> list[dict[str, Any]]:
        return pain_points

    monkeypatch.setattr(extraction_mod, "extract_pain_points", _fake_extract)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.failed
    assert iv.error_message is not None
    assert "fewer than 3" in iv.error_message
    assert "verifiable" in iv.error_message
    # And no pain points landed.
    rows = (
        await db_session.execute(
            select(PainPoint).where(PainPoint.interview_id == iv.id)
        )
    ).scalars().all()
    assert rows == []


async def test_pipeline_handles_retry_from_transcribing_state(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    mock_extraction,
):
    """When invoked via /retry, status starts at ``transcribing`` already."""
    iv = await _make_interview_row(db_session, status=InterviewStatus.transcribing)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.completed


# ---------------------------------------------------------------------------
# Transcription service unit tests (patching the AssemblyAI SDK)
# ---------------------------------------------------------------------------


def _fake_transcript(
    *,
    status,
    text: str = "hi there",
    utterances: list[Any] | None = None,
    audio_duration: int | None = 12,
    language_code: str | None = "en",
    error: str | None = None,
) -> Any:
    """Build a duck-typed stand-in for aai.Transcript."""
    return SimpleNamespace(
        status=status,
        text=text,
        utterances=utterances,
        audio_duration=audio_duration,
        language_code=language_code,
        error=error,
    )


def _fake_utterance(speaker: str, start_ms: int, end_ms: int, text: str) -> Any:
    return SimpleNamespace(speaker=speaker, start=start_ms, end=end_ms, text=text)


class _FakeTranscriber:
    """Stand-in for aai.Transcriber that records construction + invocations."""

    last_config: Any = None
    last_audio_path: str | None = None
    next_result: Any = None

    def __init__(self, *, config=None):  # noqa: D401
        type(self).last_config = config

    def transcribe(self, audio_path: str):
        type(self).last_audio_path = audio_path
        return type(self).next_result


@pytest.fixture
def patch_aai_settings_key(monkeypatch):
    """Force the transcription service to see a non-empty API key."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "test-aai-key")
    yield
    get_settings.cache_clear()


async def test_transcribe_returns_canonical_dict(monkeypatch, patch_aai_settings_key):
    import assemblyai as aai

    utterances = [
        _fake_utterance("A", 0, 1500, "Hello."),
        _fake_utterance("B", 1500, 4200, "Hi back."),
    ]
    _FakeTranscriber.next_result = _fake_transcript(
        status=aai.TranscriptStatus.completed,
        text="Hello. Hi back.",
        utterances=utterances,
        audio_duration=4,
        language_code="en",
    )
    monkeypatch.setattr(transcription_mod.aai, "Transcriber", _FakeTranscriber)

    out = await transcription_mod.transcribe(Path("/tmp/fake.m4a"))

    assert out["text"] == "Hello. Hi back."
    assert out["language_code"] == "en"
    assert out["duration_sec"] == 4.0
    assert out["segments"] == [
        {"speaker": "A", "start": 0.0, "end": 1.5, "text": "Hello."},
        {"speaker": "B", "start": 1.5, "end": 4.2, "text": "Hi back."},
    ]

    # The SDK was configured with diarization + language detection + universal model.
    cfg = _FakeTranscriber.last_config
    assert cfg.speaker_labels is True
    assert cfg.language_detection is True
    assert cfg.speech_model == aai.SpeechModel.universal
    assert _FakeTranscriber.last_audio_path == "/tmp/fake.m4a"


async def test_transcribe_falls_back_to_single_segment_without_utterances(
    monkeypatch, patch_aai_settings_key
):
    import assemblyai as aai

    _FakeTranscriber.next_result = _fake_transcript(
        status=aai.TranscriptStatus.completed,
        text="One mono segment",
        utterances=None,
        audio_duration=30,
        language_code="en",
    )
    monkeypatch.setattr(transcription_mod.aai, "Transcriber", _FakeTranscriber)

    out = await transcription_mod.transcribe(Path("/tmp/fake.m4a"))

    assert out["segments"] == [
        {"speaker": "A", "start": 0.0, "end": 30.0, "text": "One mono segment"},
    ]


async def test_transcribe_raises_on_assemblyai_error(monkeypatch, patch_aai_settings_key):
    import assemblyai as aai

    _FakeTranscriber.next_result = _fake_transcript(
        status=aai.TranscriptStatus.error,
        text="",
        utterances=None,
        audio_duration=None,
        error="audio file unreadable",
    )
    monkeypatch.setattr(transcription_mod.aai, "Transcriber", _FakeTranscriber)

    with pytest.raises(RuntimeError) as excinfo:
        await transcription_mod.transcribe(Path("/tmp/fake.m4a"))
    assert "audio file unreadable" in str(excinfo.value)


async def test_transcribe_raises_when_api_key_missing(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", "")
    try:
        with pytest.raises(RuntimeError, match="ASSEMBLYAI_API_KEY is not set"):
            await transcription_mod.transcribe(Path("/tmp/fake.m4a"))
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Extraction service unit tests (patching anthropic.AsyncAnthropic)
# ---------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, response: Any, captured_kwargs: dict[str, Any]):
        self._response = response
        self._captured = captured_kwargs

    async def create(self, **kwargs: Any) -> Any:
        self._captured.update(kwargs)
        return self._response


class _FakeAsyncAnthropic:
    last_kwargs: dict[str, Any] = {}
    last_init_kwargs: dict[str, Any] = {}
    next_response: Any = None

    def __init__(self, *, api_key: str | None = None, **kwargs: Any):
        type(self).last_init_kwargs = {"api_key": api_key, **kwargs}
        type(self).last_kwargs = {}
        self.messages = _FakeMessages(
            response=type(self).next_response, captured_kwargs=type(self).last_kwargs
        )


def _tool_use_response(pain_points: list[dict[str, Any]]) -> Any:
    """Build a duck-typed Claude Message with a tool_use block."""
    block = SimpleNamespace(
        type="tool_use",
        name="record_pain_points",
        input={"pain_points": pain_points},
    )
    return SimpleNamespace(content=[block])


@pytest.fixture
def patch_anthropic_key(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    yield
    get_settings.cache_clear()


async def test_extract_pain_points_happy_path(
    monkeypatch, patch_anthropic_key, sample_transcript, sample_pain_points
):
    _FakeAsyncAnthropic.next_response = _tool_use_response(sample_pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    out = await extraction_mod.extract_pain_points(sample_transcript)

    assert len(out) == len(sample_pain_points)
    for pp in out:
        assert set(pp.keys()) == {
            "text",
            "supporting_quote",
            "timestamp_start_sec",
            "timestamp_end_sec",
            "severity",
        }
        assert 1 <= pp["severity"] <= 5
        assert len(pp["text"]) <= 500


async def test_extract_pain_points_sends_cache_control_on_system_block(
    monkeypatch, patch_anthropic_key, sample_transcript, sample_pain_points
):
    """Prompt caching: the system block must include cache_control."""
    _FakeAsyncAnthropic.next_response = _tool_use_response(sample_pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    await extraction_mod.extract_pain_points(sample_transcript)

    kwargs = _FakeAsyncAnthropic.last_kwargs
    system_blocks = kwargs["system"]
    assert isinstance(system_blocks, list) and len(system_blocks) == 1
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}
    # And the forced-tool plumbing is intact.
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_pain_points"}
    assert kwargs["model"] == "claude-sonnet-4-6"
    # The tool schema is registered.
    tools = kwargs["tools"]
    assert any(t["name"] == "record_pain_points" for t in tools)


async def test_extract_pain_points_raises_when_tool_not_called(
    monkeypatch, patch_anthropic_key, sample_transcript
):
    """If the model returns plain text, we surface a descriptive error."""
    plain_text = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="I refuse")]
    )
    _FakeAsyncAnthropic.next_response = plain_text
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    with pytest.raises(RuntimeError, match="record_pain_points"):
        await extraction_mod.extract_pain_points(sample_transcript)


async def test_extract_pain_points_raises_when_too_few_valid(
    monkeypatch, patch_anthropic_key, sample_transcript
):
    """Validator should drop malformed pain points; if <3 left, raise."""
    pain_points = [
        # OK
        {
            "text": "Pain A",
            "supporting_quote": "some quote",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 4,
        },
        # Empty text -> dropped.
        {
            "text": "",
            "supporting_quote": "another quote",
            "timestamp_start_sec": 1.0,
            "timestamp_end_sec": 2.0,
            "severity": 3,
        },
        # Missing key -> dropped.
        {
            "text": "Pain C",
            "timestamp_start_sec": 2.0,
            "timestamp_end_sec": 3.0,
            "severity": 5,
        },
    ]
    _FakeAsyncAnthropic.next_response = _tool_use_response(pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    with pytest.raises(RuntimeError, match="fewer than 3 valid pain points"):
        await extraction_mod.extract_pain_points(sample_transcript)


async def test_extract_pain_points_clamps_out_of_range_severity(
    monkeypatch, patch_anthropic_key, sample_transcript
):
    """A model-returned severity outside 1..5 should be clamped, not dropped."""
    pain_points = [
        {
            "text": "A",
            "supporting_quote": "q1",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 9,  # too high; clamp to 5
        },
        {
            "text": "B",
            "supporting_quote": "q2",
            "timestamp_start_sec": 1.0,
            "timestamp_end_sec": 2.0,
            "severity": 0,  # too low; clamp to 1
        },
        {
            "text": "C",
            "supporting_quote": "q3",
            "timestamp_start_sec": 2.0,
            "timestamp_end_sec": 3.0,
            "severity": 3,
        },
    ]
    _FakeAsyncAnthropic.next_response = _tool_use_response(pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    out = await extraction_mod.extract_pain_points(sample_transcript)
    severities = sorted(p["severity"] for p in out)
    assert severities == [1, 3, 5]


async def test_extract_pain_points_raises_when_key_missing(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    try:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
            await extraction_mod.extract_pain_points({"text": "", "segments": []})
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_quote_match_is_case_insensitive_and_whitespace_tolerant():
    transcript = "Hello\n there,   friend."
    assert pipeline_mod._quote_is_in_transcript("HELLO THERE, friend.", transcript)
    assert pipeline_mod._quote_is_in_transcript("hello there, friend.", transcript)


def test_quote_match_rejects_substring_not_in_transcript():
    assert not pipeline_mod._quote_is_in_transcript("not here", "totally different text")


def test_render_transcript_uses_speaker_labels_and_mmss_timestamps(sample_transcript):
    rendered = extraction_mod._render_transcript(sample_transcript)
    assert "Speaker A [00:00-00:06]:" in rendered
    # Python's round() uses banker's rounding so 6.5 -> 6 and 24.1 -> 24.
    assert "Speaker B [00:06-00:24]:" in rendered
    # And the customer's last segment lands at MM:SS too.
    assert "Speaker B [01:04-01:18]:" in rendered


def test_validate_pain_point_clamps_severity_high():
    pp = extraction_mod._validate_pain_point(
        {
            "text": "x",
            "supporting_quote": "y",
            "timestamp_start_sec": 0,
            "timestamp_end_sec": 1,
            "severity": 99,
        }
    )
    assert pp is not None
    assert pp["severity"] == 5


def test_validate_pain_point_rejects_overlong_text():
    pp = extraction_mod._validate_pain_point(
        {
            "text": "x" * 501,
            "supporting_quote": "y",
            "timestamp_start_sec": 0,
            "timestamp_end_sec": 1,
            "severity": 3,
        }
    )
    assert pp is None
