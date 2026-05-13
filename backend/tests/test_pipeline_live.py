# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Live end-to-end pipeline integration test.

Skipped by default. Run with::

    cd backend && uv run pytest -m live

Requires:

- ``ASSEMBLYAI_API_KEY`` and ``ANTHROPIC_API_KEY`` set (via repo-root ``.env``).
- The sample audio fixture at ``tests/fixtures/sample_interview.m4a``.
- A reachable Postgres (the suite's standard ``db_session`` fixture).

Asserts:

- The pipeline transitions ``uploaded -> completed`` (no failure).
- ``transcript_text`` is non-empty.
- At least 3 pain points were persisted.
- Every pain point's ``supporting_quote`` appears verbatim
  (whitespace-collapsed, case-insensitive) in the transcript text.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.schemas.interview import InterviewStatus, InterviewType
from app.services import pipeline as pipeline_mod


@pytest.mark.live
async def test_pipeline_completes_against_real_apis(
    db_session, sample_audio_path, sample_demographics, monkeypatch
):
    settings = get_settings()
    if not settings.assemblyai_api_key:
        pytest.skip("ASSEMBLYAI_API_KEY not set; skipping live pipeline test")
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not set; skipping live pipeline test")

    # Force run_pipeline to use the test's transactional session.
    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        pipeline_mod, "async_session_maker", lambda: _fake_session_ctx()
    )

    project = Project(name="live-pipeline")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    interview = Interview(
        project_id=project.id,
        audio_path=str(sample_audio_path),
        audio_filename=sample_audio_path.name,
        audio_duration_sec=None,
        type=InterviewType.problem_validation,
        demographics=sample_demographics,
        status=InterviewStatus.uploaded,
    )
    db_session.add(interview)
    await db_session.commit()
    await db_session.refresh(interview)

    await pipeline_mod.run_pipeline(interview.id)

    await db_session.refresh(interview)
    assert interview.status is InterviewStatus.completed, (
        f"pipeline did not complete: status={interview.status} "
        f"error={interview.error_message!r}"
    )
    assert interview.transcript_text and len(interview.transcript_text) > 0

    pain_points = (
        await db_session.execute(
            select(PainPoint).where(PainPoint.interview_id == interview.id)
        )
    ).scalars().all()
    assert len(pain_points) >= 3, f"expected >= 3 pain points, got {len(pain_points)}"

    transcript_text = interview.transcript_text or ""
    for pp in pain_points:
        assert pipeline_mod._quote_is_in_transcript(
            pp.supporting_quote, transcript_text
        ), f"supporting_quote not in transcript: {pp.supporting_quote!r}"
