# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Tests for the v1.2 transcript-upload pathway (API + pipeline).

v1.2 narrowed the accepted transcript extension set to ``.vtt`` only;
``.txt`` and ``.srt`` are now 415s instead of the v1.1 202s. The
pipeline now stores the preprocessed formatted string (cue blocks with
``[MM:SS - MM:SS] Speaker X`` headers) in ``transcript_text``.
"""

from __future__ import annotations

import contextlib
import json
import uuid

import pytest
from sqlalchemy import select

from app.models.interview import Interview
from app.models.project import Project
from app.schemas.interview import InterviewSourceKind, InterviewStatus, InterviewType
from app.services import audio as audio_service
from app.services import extraction as extraction_mod
from app.services import pipeline as pipeline_mod
from app.services import transcript_parser as transcript_parser_mod
from app.services import transcription as transcription_mod


# Sample VTT used by multiple tests. The pipeline tests reuse this body
# verbatim — every quote in the canned pain-points fixture is a
# substring of the cues below.
_SAMPLE_VTT = (
    "WEBVTT\n"
    "\n"
    "00:00:00.000 --> 00:00:06.200\n"
    "<v Speaker A>Thanks for taking the time today. Can you walk me through "
    "how you currently track customer feedback?\n"
    "\n"
    "00:00:06.500 --> 00:00:24.100\n"
    "<v Speaker B>Honestly, it's a mess. We have feedback coming in from "
    "intercom, from sales calls, from support tickets, and nobody puts it in "
    "one place. I spend probably four hours a week just copying notes between "
    "Notion and a spreadsheet.\n"
    "\n"
    "00:00:24.500 --> 00:00:27.000\n"
    "<v Speaker A>That sounds painful. What's the worst part?\n"
    "\n"
    "00:00:27.300 --> 00:00:46.900\n"
    "<v Speaker B>The worst part is that by the time I've aggregated "
    "everything, the insight is stale. Last quarter we shipped a feature "
    "based on feedback that was two months old and three customers had "
    "already churned over it. I felt sick about that.\n"
    "\n"
    "00:00:47.200 --> 00:00:49.400\n"
    "<v Speaker A>Have you tried any tools to help?\n"
    "\n"
    "00:00:49.700 --> 00:01:01.100\n"
    "<v Speaker B>We tried Dovetail for a month but the team wouldn't "
    "actually use it. The upload step was too slow and tagging interviews "
    "took forever. We churned off it.\n"
    "\n"
    "00:01:01.400 --> 00:01:03.600\n"
    "<v Speaker A>Anything else that gets in the way?\n"
    "\n"
    "00:01:03.900 --> 00:01:18.400\n"
    "<v Speaker B>Yeah, our PM team is small, just me and one other person, "
    "and we don't have time to do proper research synthesis. So a lot of "
    "decisions get made on vibes. That scares me as we grow.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_project(client, name: str = "transcript-project") -> str:
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def mock_pipeline(monkeypatch):
    calls: list[uuid.UUID] = []

    async def _noop(interview_id: uuid.UUID) -> None:
        calls.append(interview_id)

    monkeypatch.setattr("app.api.v1.interviews.run_pipeline", _noop)
    return calls


@pytest.fixture
def storage_dirs(tmp_path, monkeypatch):
    """Redirect both audio and transcript storage to tmp."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()

    monkeypatch.setattr(audio_service, "_resolved_storage_dir", lambda: audio_dir)
    monkeypatch.setattr(
        audio_service, "_resolved_transcript_storage_dir", lambda: transcripts_dir
    )
    return audio_dir, transcripts_dir


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


async def test_upload_vtt_happy_path(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    _, transcripts_dir = storage_dirs
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": ("hello.vtt", _SAMPLE_VTT.encode("utf-8"), "text/vtt"),
        },
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["source_kind"] == "transcript"
    assert body["audio_filename"] == "hello.vtt"
    assert body["audio_duration_sec"] is None
    assert body["status"] == "uploaded"

    # File persisted under the transcripts dir.
    saved = list(transcripts_dir.iterdir())
    assert len(saved) == 1
    assert saved[0].suffix == ".vtt"

    # Pipeline scheduled.
    assert len(mock_pipeline) == 1


async def test_upload_vtt_with_text_plain_mime_accepted(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    """Some clients send ``text/plain`` for ``.vtt`` — must still 202."""
    proj_id = await _make_project(client)
    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": ("hi.vtt", _SAMPLE_VTT.encode("utf-8"), "text/plain"),
        },
    )
    assert resp.status_code == 202, resp.text


async def test_upload_both_audio_and_transcript_returns_422(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "audio": ("x.mp3", b"\xff\xfb\x90\x00", "audio/mpeg"),
            "transcript": ("x.vtt", _SAMPLE_VTT.encode("utf-8"), "text/vtt"),
        },
    )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["status"] == 422
    assert "exactly one" in body["detail"]
    assert body["errors"][0]["loc"] == ["audio"]
    # Pipeline must not have been scheduled.
    assert mock_pipeline == []


async def test_upload_neither_audio_nor_transcript_returns_422(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
    )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["errors"][0]["loc"] == ["audio"]
    assert "exactly one" in body["detail"]
    assert mock_pipeline == []


async def test_upload_oversized_transcript_returns_413(
    client, sample_demographics, mock_pipeline, storage_dirs, monkeypatch
):
    proj_id = await _make_project(client)
    # Bring the cap down so a small payload trips it.
    monkeypatch.setattr(audio_service, "MAX_TRANSCRIPT_BYTES", 16)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": (
                "big.vtt",
                b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n" + b"x" * 64,
                "text/vtt",
            ),
        },
    )
    assert resp.status_code == 413, resp.text
    assert mock_pipeline == []


async def test_upload_txt_extension_returns_415(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    """v1.2: .txt was 202 in v1.1, now 415."""
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": (
                "hello.txt",
                b"Speaker A: Hi.\nSpeaker B: Hi back.\n",
                "text/plain",
            ),
        },
    )
    assert resp.status_code == 415, resp.text
    assert mock_pipeline == []


async def test_upload_srt_extension_returns_415(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    """v1.2: .srt was 202 in v1.1, now 415."""
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": (
                "hello.srt",
                b"1\n00:00:00,000 --> 00:00:02,500\nSpeaker A: Hi.\n",
                "application/x-subrip",
            ),
        },
    )
    assert resp.status_code == 415, resp.text
    assert mock_pipeline == []


async def test_upload_unsupported_transcript_extension_returns_415(
    client, sample_demographics, mock_pipeline, storage_dirs
):
    proj_id = await _make_project(client)

    resp = await client.post(
        f"/api/v1/projects/{proj_id}/interviews",
        data={
            "type": "problem_validation",
            "demographics": json.dumps(sample_demographics),
        },
        files={
            "transcript": (
                "bad.docx",
                b"not a real docx",
                "application/octet-stream",
            ),
        },
    )
    assert resp.status_code == 415, resp.text
    assert mock_pipeline == []


# ---------------------------------------------------------------------------
# Audio endpoint on a transcript interview -> 404 with the new message
# ---------------------------------------------------------------------------


async def _make_transcript_row(db_session) -> Interview:
    project = Project(name="transcript-source")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.transcript,
        audio_path=None,
        audio_filename="up.vtt",
        audio_duration_sec=None,
        transcript_path="/tmp/nope.vtt",
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
        status=InterviewStatus.completed,
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)
    return iv


async def test_audio_endpoint_404s_for_transcript_interview(client, db_session):
    iv = await _make_transcript_row(db_session)
    resp = await client.get(f"/api/v1/interviews/{iv.id}/audio")
    assert resp.status_code == 404
    body = resp.json()
    assert "source_kind = transcript" in body["detail"]


# ---------------------------------------------------------------------------
# Pipeline: transcript branch skips AssemblyAI and stores the formatted string
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_async_session_maker(monkeypatch, db_session):
    """Mirror the helper in test_pipeline.py."""
    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        pipeline_mod, "async_session_maker", lambda: _fake_session_ctx()
    )


async def test_pipeline_transcript_branch_skips_assemblyai(
    db_session,
    patch_async_session_maker,
    mock_extraction,
    monkeypatch,
    tmp_path,
):
    """End-to-end: a real .vtt file lands at completed with the formatted
    string in ``transcript_text`` (byte-equal to ``render_formatted``)."""
    transcript_file = tmp_path / "interview.vtt"
    transcript_file.write_text(_SAMPLE_VTT)

    project = Project(name="transcript-pipeline")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.transcript,
        audio_path=None,
        audio_filename=transcript_file.name,
        audio_duration_sec=None,
        transcript_path=str(transcript_file),
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
        status=InterviewStatus.uploaded,
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)

    # Assert AssemblyAI is NOT called.
    async def _boom(_path):
        raise AssertionError("transcription.transcribe must not be called")

    monkeypatch.setattr(transcription_mod, "transcribe", _boom)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    assert iv.status is InterviewStatus.completed
    # transcript_text is byte-equal to the formatted render.
    expected = transcript_parser_mod.render_formatted(transcript_file)
    assert iv.transcript_text == expected
    # And the formatted text contains the cue-block markers.
    assert iv.transcript_text is not None
    assert "[00:00 - 00:06] Speaker A" in iv.transcript_text
    assert "\n\n" in iv.transcript_text
    assert mock_extraction.await_count == 1


async def test_pipeline_quote_verification_passes_against_formatted_transcript(
    db_session,
    patch_async_session_maker,
    monkeypatch,
    tmp_path,
):
    """Even with [MM:SS] / Speaker X prefixes injected into transcript_text,
    a plain customer-words supporting_quote still matches."""
    transcript_file = tmp_path / "interview.vtt"
    transcript_file.write_text(_SAMPLE_VTT)

    project = Project(name="quote-verify")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.transcript,
        audio_path=None,
        audio_filename=transcript_file.name,
        audio_duration_sec=None,
        transcript_path=str(transcript_file),
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
        status=InterviewStatus.uploaded,
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)

    # Stub AssemblyAI out (transcript branch shouldn't touch it anyway).
    async def _boom(_path):
        raise AssertionError("transcription.transcribe must not be called")

    monkeypatch.setattr(transcription_mod, "transcribe", _boom)

    # Three pain points whose supporting quotes are plain customer-words
    # — they appear verbatim inside the cue text but the rendered
    # transcript_text wraps each cue in a [MM:SS] header.
    pain_points = [
        {
            "text": "Feedback fragmentation forces manual aggregation.",
            "supporting_quote": (
                "I spend probably four hours a week just copying notes "
                "between Notion and a spreadsheet."
            ),
            "timestamp_start_sec": 6.5,
            "timestamp_end_sec": 24.1,
            "severity": 4,
            "type": "workaround",
        },
        {
            "text": "Stale synthesis leads to churn.",
            "supporting_quote": (
                "Last quarter we shipped a feature based on feedback that "
                "was two months old and three customers had already churned "
                "over it."
            ),
            "timestamp_start_sec": 27.3,
            "timestamp_end_sec": 46.9,
            "severity": 5,
            "type": "pain_point",
        },
        {
            "text": "Existing tools have too much friction.",
            "supporting_quote": (
                "We tried Dovetail for a month but the team wouldn't "
                "actually use it."
            ),
            "timestamp_start_sec": 49.7,
            "timestamp_end_sec": 61.1,
            "severity": 3,
            "type": "pain_point",
        },
    ]

    async def _fake_extract(transcript):
        return pain_points

    monkeypatch.setattr(extraction_mod, "extract_pain_points", _fake_extract)

    await pipeline_mod.run_pipeline(iv.id)

    await db_session.refresh(iv)
    # All three pain points survived verification against the FORMATTED
    # transcript_text. None were dropped.
    assert iv.status is InterviewStatus.completed
    rows = (
        await db_session.execute(
            select(Interview).where(Interview.id == iv.id)
        )
    ).scalar_one()
    assert rows.transcript_text is not None
    # Each plain-text quote is a substring of the formatted output (the
    # whitespace-collapse helper handles the cue-wrap line breaks).
    for pp in pain_points:
        assert pipeline_mod._quote_is_in_transcript(
            pp["supporting_quote"], iv.transcript_text
        )


async def test_pipeline_get_interview_returns_formatted_transcript_text(
    client,
    db_session,
    patch_async_session_maker,
    mock_extraction,
    monkeypatch,
    tmp_path,
):
    """``GET /interviews/{id}`` returns transcript_text byte-equal to
    ``render_formatted(vtt_path)`` after the pipeline completes."""
    transcript_file = tmp_path / "interview.vtt"
    transcript_file.write_text(_SAMPLE_VTT)

    project = Project(name="get-formatted")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.transcript,
        audio_path=None,
        audio_filename=transcript_file.name,
        audio_duration_sec=None,
        transcript_path=str(transcript_file),
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
        status=InterviewStatus.uploaded,
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)

    async def _boom(_path):
        raise AssertionError("transcription.transcribe must not be called")

    monkeypatch.setattr(transcription_mod, "transcribe", _boom)

    await pipeline_mod.run_pipeline(iv.id)

    resp = await client.get(f"/api/v1/interviews/{iv.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transcript_text"] == transcript_parser_mod.render_formatted(
        transcript_file
    )


# ---------------------------------------------------------------------------
# Migration backfill smoke test
# ---------------------------------------------------------------------------


async def test_existing_interviews_backfilled_to_source_kind_audio(db_session):
    """A row inserted without an explicit source_kind defaults to 'audio'
    via the server_default — matches what the backfill sets for v0 rows."""
    project = Project(name="backfill-smoke")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    iv = Interview(
        project_id=project.id,
        audio_path="/tmp/x.m4a",
        audio_filename="x.m4a",
        audio_duration_sec=10.0,
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
        status=InterviewStatus.uploaded,
        # source_kind intentionally unset — relies on default.
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)

    refreshed = (
        await db_session.execute(select(Interview).where(Interview.id == iv.id))
    ).scalar_one()
    assert refreshed.source_kind is InterviewSourceKind.audio
    assert refreshed.audio_path == "/tmp/x.m4a"
