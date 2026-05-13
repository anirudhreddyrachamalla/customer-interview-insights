# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Pipeline-isolation guarantee for ``Interview.meeting_notes``.

``meeting_notes`` is a human-only field. It exists purely so the
researcher can scribble context onto an interview (e.g. "recruited via
Slack, mood: frustrated") and read it back on the detail page. It must
**never** leak into either external service:

- AssemblyAI gets only the audio path. The transcription call is
  position-only (one ``Path`` argument); no kwargs, no transcript
  enrichment, no notes.
- Anthropic / Claude gets only the canonical transcript dict
  (``{"text": ..., "segments": [...]}``). The extraction prompt is
  exclusively driven by the transcript; the model must not see what the
  human wrote down out-of-band.

If we ever accidentally pass ``meeting_notes`` into the prompt — say by
folding it into the transcript dict, prepending it to system text, or
shipping it as a `<context>` block — Claude's extraction would start
drifting away from the recorded conversation, which defeats the
"evidence-anchored pain points" guarantee in SPEC.md.

This module pins that contract with a single mocked-end-to-end test.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.models.interview import Interview
from app.models.project import Project
from app.schemas.interview import InterviewStatus, InterviewType
from app.services import pipeline as pipeline_mod


# A deliberately distinctive string so a substring search across mock
# call records is unambiguous. If this string ever shows up in either
# external-service call, something is wrong.
_SECRET_NOTES = (
    "this is secret context only the human sees: recruited via Slack, "
    "switched from a competitor 2 weeks ago, do not surface in prompts"
)


@pytest.fixture
def patch_async_session_maker(monkeypatch, db_session):
    """Mirror the helper in ``test_pipeline.py`` so this file is standalone.

    The pipeline opens its own ``async_session_maker()`` context, which
    would bypass the per-test SAVEPOINT. Patch it to yield the existing
    transactional ``db_session`` so we can observe the same rows.
    """
    import contextlib

    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        pipeline_mod, "async_session_maker", lambda: _fake_session_ctx()
    )


async def _make_interview_with_notes(
    db_session, *, meeting_notes: str
) -> Interview:
    """Insert a project + interview with the given ``meeting_notes`` directly.

    Goes via the ORM rather than the upload endpoint so the test stays
    focused on the pipeline contract — we don't want a multipart-form
    round-trip cluttering the assertion that nothing leaks to the
    external services.
    """
    project = Project(name="meeting-notes-isolation")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    interview = Interview(
        project_id=project.id,
        audio_path="/tmp/meeting-notes-isolation.m4a",
        audio_filename="meeting-notes-isolation.m4a",
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
        status=InterviewStatus.uploaded,
        meeting_notes=meeting_notes,
    )
    db_session.add(interview)
    await db_session.commit()
    await db_session.refresh(interview)
    return interview


async def test_pipeline_never_passes_meeting_notes_to_external_services(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    mock_extraction,
    sample_transcript,
) -> None:
    """``meeting_notes`` is pure storage; the pipeline must not leak it.

    Concretely we assert four things after a full mocked pipeline run:

    1. The transcription mock saw only the audio ``Path`` — no
       ``meeting_notes`` anywhere in its args / kwargs.
    2. The extraction mock saw the canonical transcript dict — no
       ``meeting_notes`` in any positional or keyword argument, including
       inside the transcript dict itself.
    3. After the pipeline finishes the interview still carries the
       original ``meeting_notes`` value (it wasn't clobbered).
    4. The pipeline reached ``completed`` — i.e. nothing in our
       isolation harness broke the happy path.
    """
    iv = await _make_interview_with_notes(
        db_session, meeting_notes=_SECRET_NOTES
    )

    await pipeline_mod.run_pipeline(iv.id)

    # 1) Transcription saw only the audio path. The service signature is
    #    ``async def transcribe(audio_path: Path) -> dict``. We don't want
    #    to over-constrain that to a specific call style, so we just check
    #    that the secret string is absent from the entire serialized call.
    assert mock_transcription.await_count == 1
    transcription_call = mock_transcription.await_args
    assert transcription_call is not None
    # The single positional argument must be the audio path.
    assert len(transcription_call.args) == 1
    assert str(transcription_call.args[0]) == iv.audio_path
    # And the secret must not appear anywhere — positional or keyword.
    assert _SECRET_NOTES not in str(transcription_call.args)
    assert _SECRET_NOTES not in str(transcription_call.kwargs)

    # 2) Extraction was called with the canonical transcript dict and
    #    nothing else. Verify the secret is absent from the entire call
    #    record (including the transcript payload, in case some future
    #    helper accidentally folds notes into it).
    assert mock_extraction.await_count == 1
    extraction_call = mock_extraction.await_args
    assert extraction_call is not None
    # First positional should be the transcript dict — assert shape so a
    # future refactor that adds a second arg fails this test loudly.
    assert len(extraction_call.args) == 1
    transcript_arg = extraction_call.args[0]
    assert isinstance(transcript_arg, dict)
    assert transcript_arg.get("text") == sample_transcript["text"]
    # No meeting_notes key, and the secret is nowhere inside the dict.
    assert "meeting_notes" not in transcript_arg
    assert _SECRET_NOTES not in str(transcript_arg)
    # And not in kwargs either.
    assert _SECRET_NOTES not in str(extraction_call.kwargs)
    # Belt-and-braces: full call repr must be free of the secret.
    assert _SECRET_NOTES not in str(extraction_call)

    # 3) The notes are preserved on the row after the pipeline ran. Use a
    #    fresh SELECT (rather than refresh) to be sure we're seeing what
    #    actually persisted, not stale ORM state.
    refreshed: Any = (
        await db_session.execute(select(Interview).where(Interview.id == iv.id))
    ).scalar_one()
    assert refreshed.meeting_notes == _SECRET_NOTES

    # 4) Happy path completed end-to-end despite the notes being present.
    assert refreshed.status is InterviewStatus.completed
    assert refreshed.error_message is None
