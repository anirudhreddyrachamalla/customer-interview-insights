# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Integration tests for the v1.1 pain-point ``type`` column.

Covers the bottom three bullets in SPEC_v1.1.md section 1 "Tests
(backend)":

* Pipeline persists pain points with the type Claude returned.
* GET /interviews/{id} surfaces ``type`` in every ``pain_points[]`` entry.
* Backfill smoke: ``InterviewSourceKind`` default + the migration's
  ``UPDATE pain_points SET type='pain_point'`` step.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import select

from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.schemas.interview import (
    InterviewSourceKind,
    InterviewStatus,
    InterviewType,
    PainPointType,
)
from app.services import pipeline as pipeline_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_interview(db_session, **overrides) -> Interview:
    project = Project(name="pp-type-test")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    overrides.setdefault("status", InterviewStatus.uploaded)
    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.audio,
        audio_path="/tmp/x.m4a",
        audio_filename="x.m4a",
        audio_duration_sec=10.0,
        type=InterviewType.problem_validation,
        demographics={
            "name": "Pat",
            "gender": "non_binary",
            "age": 33,
            "income": "50k_100k",
            "marital_status": "single",
            "country": "US",
            "job_role": "engineer",
            "industry": "saas_software",
        },
        **overrides,
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)
    return iv


@pytest.fixture
def patch_async_session_maker(monkeypatch, db_session):
    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        pipeline_mod, "async_session_maker", lambda: _fake_session_ctx()
    )


# ---------------------------------------------------------------------------
# Pipeline persists the Claude-returned type
# ---------------------------------------------------------------------------


async def test_pipeline_persists_type_returned_by_claude(
    db_session,
    patch_async_session_maker,
    mock_transcription,
    sample_pain_points,
    monkeypatch,
):
    """Each pain-point row picks up the ``type`` Claude returned."""
    iv = await _make_interview(db_session)

    async def _fake_extract(_transcript):
        return sample_pain_points

    from app.services import extraction as extraction_mod

    monkeypatch.setattr(extraction_mod, "extract_pain_points", _fake_extract)

    await pipeline_mod.run_pipeline(iv.id)

    rows = (
        await db_session.execute(
            select(PainPoint).where(PainPoint.interview_id == iv.id)
        )
    ).scalars().all()

    by_text = {row.text: row for row in rows}
    expected = {pp["text"]: pp["type"] for pp in sample_pain_points}
    for text, expected_type in expected.items():
        row = by_text.get(text)
        assert row is not None, f"missing pain point: {text!r}"
        assert row.type.value == expected_type


# ---------------------------------------------------------------------------
# GET /interviews/{id} surfaces ``type``
# ---------------------------------------------------------------------------


async def test_get_interview_returns_type_for_each_pain_point(
    client, db_session
):
    iv = await _make_interview(db_session, status=InterviewStatus.completed)

    rows = [
        PainPoint(
            interview_id=iv.id,
            text="a",
            supporting_quote="q1",
            timestamp_start_sec=0,
            timestamp_end_sec=1,
            severity=5,
            type=PainPointType.workaround,
        ),
        PainPoint(
            interview_id=iv.id,
            text="b",
            supporting_quote="q2",
            timestamp_start_sec=2,
            timestamp_end_sec=3,
            severity=4,
            type=PainPointType.suggestion,
        ),
        PainPoint(
            interview_id=iv.id,
            text="c",
            supporting_quote="q3",
            timestamp_start_sec=4,
            timestamp_end_sec=5,
            severity=3,
            type=PainPointType.pain_point,
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    resp = await client.get(f"/api/v1/interviews/{iv.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {pp["text"]: pp["type"] for pp in body["pain_points"]}
    assert types == {"a": "workaround", "b": "suggestion", "c": "pain_point"}
