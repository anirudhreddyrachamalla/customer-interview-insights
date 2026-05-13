# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Tests for the v1.1 project-insights resource + Claude synth path."""

from __future__ import annotations

import contextlib
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.models.project_insight import ProjectInsight
from app.schemas.insight import InsightStatus
from app.schemas.interview import (
    InterviewSourceKind,
    InterviewStatus,
    InterviewType,
    PainPointType,
)
from app.services import insights as insights_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_project(db_session, name: str = "insights-test") -> Project:
    project = Project(name=name)
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _make_completed_interview(
    db_session,
    project: Project,
    *,
    with_pain_points: bool = True,
) -> Interview:
    iv = Interview(
        project_id=project.id,
        source_kind=InterviewSourceKind.audio,
        audio_path="/tmp/x.m4a",
        audio_filename="x.m4a",
        audio_duration_sec=12.3,
        type=InterviewType.problem_validation,
        demographics={
            "name": "Pat",
            "gender": "non_binary",
            "age": 30,
            "income": "50k_100k",
            "marital_status": "single",
            "country": "US",
            "job_role": "product_manager",
            "industry": "saas_software",
        },
        status=InterviewStatus.completed,
        transcript_text="some text",
    )
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)

    if with_pain_points:
        pp = PainPoint(
            interview_id=iv.id,
            text="hard to do X",
            supporting_quote="this is hard",
            timestamp_start_sec=1.0,
            timestamp_end_sec=2.0,
            severity=4,
            type=PainPointType.pain_point,
        )
        db_session.add(pp)
        await db_session.commit()
        await db_session.refresh(iv)

    return iv


@pytest.fixture
def patch_async_session_maker(monkeypatch, db_session):
    """Force ``generate_summary`` to use the test's transactional session."""
    @contextlib.asynccontextmanager
    async def _fake_session_ctx():
        yield db_session

    monkeypatch.setattr(
        insights_mod, "async_session_maker", lambda: _fake_session_ctx()
    )


# ---------------------------------------------------------------------------
# Fake Anthropic SDK
# ---------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, response: Any):
        self._response = response

    async def create(self, **kwargs: Any) -> Any:
        return self._response


class _FakeAsyncAnthropic:
    next_response: Any = None
    raise_on_create: Exception | None = None

    def __init__(self, *, api_key: str | None = None, **kwargs: Any):
        if type(self).raise_on_create is not None:
            raise type(self).raise_on_create
        self.messages = _FakeMessages(response=type(self).next_response)


def _summary_response(markdown: str) -> Any:
    block = SimpleNamespace(
        type="tool_use",
        name="record_project_summary",
        input={"summary_markdown": markdown},
    )
    return SimpleNamespace(content=[block])


@pytest.fixture
def patch_anthropic_key(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    _FakeAsyncAnthropic.next_response = None
    _FakeAsyncAnthropic.raise_on_create = None
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# GET — synthetic idle when no row exists
# ---------------------------------------------------------------------------


async def test_get_insights_synthesises_idle_when_no_row(client, db_session):
    project = await _make_project(db_session)

    resp = await client.get(f"/api/v1/projects/{project.id}/insights")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == str(project.id)
    assert body["status"] == "idle"
    assert body["summary_markdown"] is None
    assert body["interview_count_summarised"] == 0
    assert body["interview_count_completed"] == 0
    assert body["is_stale"] is False
    assert body["model"] is None
    assert body["generated_at"] is None


async def test_get_insights_reports_current_completed_count(client, db_session):
    project = await _make_project(db_session)
    await _make_completed_interview(db_session, project)
    await _make_completed_interview(db_session, project)

    resp = await client.get(f"/api/v1/projects/{project.id}/insights")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["interview_count_completed"] == 2
    assert body["status"] == "idle"


async def test_get_insights_returns_404_for_missing_project(client):
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/insights")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /refresh — the two 409 paths and the happy path
# ---------------------------------------------------------------------------


async def test_refresh_409_when_no_completed_interviews(client, db_session):
    project = await _make_project(db_session)

    resp = await client.post(f"/api/v1/projects/{project.id}/insights/refresh")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert "at least one completed interview" in body["detail"]


async def test_refresh_409_when_already_generating(
    client, db_session, monkeypatch
):
    project = await _make_project(db_session)
    await _make_completed_interview(db_session, project)

    # Make BackgroundTasks a no-op so we can observe the row state
    # without the background generator flipping it back to idle.
    async def _noop(project_id):
        return None

    monkeypatch.setattr(insights_mod, "generate_summary", _noop)

    first = await client.post(f"/api/v1/projects/{project.id}/insights/refresh")
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "generating"

    second = await client.post(f"/api/v1/projects/{project.id}/insights/refresh")
    assert second.status_code == 409, second.text
    assert "already in progress" in second.json()["detail"]


async def test_refresh_kicks_off_background_task(
    client, db_session, monkeypatch
):
    project = await _make_project(db_session)
    await _make_completed_interview(db_session, project)

    calls: list[uuid.UUID] = []

    async def _record(project_id):
        calls.append(project_id)

    monkeypatch.setattr(insights_mod, "generate_summary", _record)

    resp = await client.post(f"/api/v1/projects/{project.id}/insights/refresh")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "generating"
    assert calls == [project.id]


# ---------------------------------------------------------------------------
# generate_summary — happy + failure
# ---------------------------------------------------------------------------


async def test_generate_summary_writes_markdown_and_flips_idle(
    db_session, patch_async_session_maker, patch_anthropic_key, monkeypatch
):
    project = await _make_project(db_session)
    iv = await _make_completed_interview(db_session, project)

    row = ProjectInsight(
        project_id=project.id,
        status=InsightStatus.generating,
        summary_markdown=None,
        interview_ids=[],
    )
    db_session.add(row)
    await db_session.commit()

    _FakeAsyncAnthropic.next_response = _summary_response(
        "## Common pain points\n- thing (1/1)\n"
    )
    monkeypatch.setattr(insights_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)

    await insights_mod.generate_summary(project.id)

    refreshed = (
        await db_session.execute(
            select(ProjectInsight).where(ProjectInsight.project_id == project.id)
        )
    ).scalar_one()
    assert refreshed.status is InsightStatus.idle
    assert refreshed.summary_markdown is not None
    assert "Common pain points" in refreshed.summary_markdown
    assert refreshed.model == "claude-sonnet-4-6"
    assert refreshed.generated_at is not None
    assert refreshed.interview_ids == [iv.id]


async def test_generate_summary_marks_failed_on_anthropic_error(
    db_session, patch_async_session_maker, patch_anthropic_key, monkeypatch
):
    project = await _make_project(db_session)
    await _make_completed_interview(db_session, project)

    row = ProjectInsight(
        project_id=project.id,
        status=InsightStatus.generating,
        summary_markdown=None,
        interview_ids=[],
    )
    db_session.add(row)
    await db_session.commit()

    # Make the SDK explode on init so we don't need a fake response.
    class _Boom(_FakeAsyncAnthropic):
        pass

    _Boom.raise_on_create = RuntimeError("anthropic exploded")
    monkeypatch.setattr(insights_mod.anthropic, "AsyncAnthropic", _Boom)

    await insights_mod.generate_summary(project.id)

    refreshed = (
        await db_session.execute(
            select(ProjectInsight).where(ProjectInsight.project_id == project.id)
        )
    ).scalar_one()
    assert refreshed.status is InsightStatus.failed
    assert refreshed.error_message is not None
    assert "anthropic exploded" in refreshed.error_message


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


async def test_is_stale_flag_when_interview_count_drifts(
    client, db_session, patch_async_session_maker, patch_anthropic_key, monkeypatch
):
    project = await _make_project(db_session)
    iv1 = await _make_completed_interview(db_session, project)

    # Seed a "generating" row + run generate_summary so it flips to idle
    # with interview_ids = [iv1.id].
    row = ProjectInsight(
        project_id=project.id,
        status=InsightStatus.generating,
        summary_markdown=None,
        interview_ids=[],
    )
    db_session.add(row)
    await db_session.commit()

    _FakeAsyncAnthropic.next_response = _summary_response("## Common pain points\n")
    monkeypatch.setattr(insights_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)
    await insights_mod.generate_summary(project.id)

    # No new interviews yet — should be fresh.
    resp = await client.get(f"/api/v1/projects/{project.id}/insights")
    assert resp.status_code == 200
    assert resp.json()["is_stale"] is False
    assert resp.json()["interview_count_summarised"] == 1
    assert resp.json()["interview_count_completed"] == 1

    # Add another completed interview — now stale.
    await _make_completed_interview(db_session, project)
    resp = await client.get(f"/api/v1/projects/{project.id}/insights")
    body = resp.json()
    assert body["is_stale"] is True
    assert body["interview_count_summarised"] == 1
    assert body["interview_count_completed"] == 2
    # iv1 is still the snapshot id.
    assert iv1.id is not None


# ---------------------------------------------------------------------------
# Cascade delete
# ---------------------------------------------------------------------------


async def test_project_delete_cascades_to_insights_row(db_session):
    from sqlalchemy import delete

    project = await _make_project(db_session)
    row = ProjectInsight(
        project_id=project.id,
        status=InsightStatus.idle,
        summary_markdown="x",
        interview_ids=[],
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    await db_session.execute(delete(Project).where(Project.id == project.id))
    await db_session.commit()

    remaining = (
        await db_session.execute(
            select(ProjectInsight).where(ProjectInsight.id == row.id)
        )
    ).scalar_one_or_none()
    assert remaining is None
