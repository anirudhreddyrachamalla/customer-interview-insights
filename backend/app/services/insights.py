"""Project-level Claude-synthesised insights (v1.1).

Owns three concerns:

* :func:`get_or_synthesize_view` — render a :class:`ProjectInsightRead`
  for ``GET /projects/{id}/insights``. Synthesises an idle row when
  no DB row exists yet so the frontend never needs to handle a 404.
* :func:`request_refresh` — handle ``POST /projects/{id}/insights/refresh``.
  Enforces the 409 paths and upserts the row to ``status='generating'``.
* :func:`generate_summary` — the BackgroundTask that calls Claude,
  writes the markdown back to the row, and flips ``status`` to
  ``idle`` / ``failed``.

The Anthropic SDK is imported as a module attribute so tests can
replace ``insights_mod.anthropic.AsyncAnthropic`` without monkeypatching
the whole module.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session_maker
from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.models.project import Project
from app.models.project_insight import ProjectInsight
from app.schemas.insight import InsightStatus, ProjectInsightRead
from app.schemas.interview import InterviewStatus

logger = logging.getLogger(__name__)


CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
TOOL_NAME = "record_project_summary"

SYSTEM_PROMPT = (
    "You synthesise cross-interview themes for a product researcher. "
    "You're given a list of customer interviews. Each interview has "
    "demographics and a list of extracted pain points, each pain point "
    "tagged as `pain_point`, `workaround`, or `suggestion`.\n\n"
    "Produce a concise Markdown summary with three sections:\n"
    "- `## Common pain points` (themes seen across multiple interviews)\n"
    "- `## Common workarounds` (current coping strategies)\n"
    "- `## Suggestions` (features / fixes the customers explicitly asked "
    "for or said they need)\n\n"
    "For each bullet, cite how many interviews mentioned it "
    "(e.g. \"(5/7 interviews)\"). Quote specific customer language where "
    "it's especially vivid. Keep the whole summary under ~600 words. "
    "If there are fewer than 3 interviews, say so and produce best-effort "
    "observations without forcing themes."
)


TOOL_DEFINITION: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Record the cross-interview summary in Markdown. Call this tool "
        "exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary_markdown": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The full cross-interview summary as Markdown, with the "
                    "three required sections."
                ),
            }
        },
        "required": ["summary_markdown"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


async def _get_insight_row(
    db: AsyncSession, project_id: uuid.UUID
) -> ProjectInsight | None:
    result = await db.execute(
        select(ProjectInsight).where(ProjectInsight.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def _list_completed_interviews(
    db: AsyncSession, project_id: uuid.UUID
) -> list[Interview]:
    """All ``status='completed'`` interviews for a project, with pain points.

    Eager-loads ``pain_points`` so we can render them into the prompt
    without an N+1.
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Interview)
        .where(Interview.project_id == project_id)
        .where(Interview.status == InterviewStatus.completed)
        .options(selectinload(Interview.pain_points))
        .order_by(Interview.created_at.asc())
    )
    return list(result.scalars().all())


def _is_stale(snapshot: list[uuid.UUID], current: list[uuid.UUID]) -> bool:
    """True iff the two id sets differ (order-independent)."""
    return set(snapshot) != set(current)


def _row_to_read(
    project: Project,
    row: ProjectInsight | None,
    completed_ids: list[uuid.UUID],
) -> ProjectInsightRead:
    """Project (id, current completed ids) + optional row -> read schema."""
    if row is None:
        # Synthetic idle row: no DB write, no staleness signal.
        return ProjectInsightRead(
            project_id=project.id,
            status=InsightStatus.idle,
            summary_markdown=None,
            interview_count_summarised=0,
            interview_count_completed=len(completed_ids),
            is_stale=False,
            error_message=None,
            model=None,
            generated_at=None,
            updated_at=project.created_at,
        )

    snapshot_ids = list(row.interview_ids or [])
    is_stale = _is_stale(snapshot_ids, completed_ids)
    return ProjectInsightRead(
        project_id=project.id,
        status=row.status,
        summary_markdown=row.summary_markdown,
        interview_count_summarised=len(snapshot_ids),
        interview_count_completed=len(completed_ids),
        is_stale=is_stale,
        error_message=row.error_message,
        model=row.model,
        generated_at=row.generated_at,
        updated_at=row.updated_at,
    )


async def _require_project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Fetch a project or raise :class:`ProjectNotFoundError`."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError(project_id)
    return project


# ---------------------------------------------------------------------------
# Exceptions surfaced to the API layer
# ---------------------------------------------------------------------------


class ProjectNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id


class NoCompletedInterviewsError(Exception):
    """Raised when a refresh would have nothing to summarise."""


class InsightAlreadyGeneratingError(Exception):
    """Raised when a refresh is requested while one is already in flight."""


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------


async def get_or_synthesize_view(
    db: AsyncSession, project_id: uuid.UUID
) -> ProjectInsightRead:
    """Render the insights view for a project, synthesising a row if absent."""
    project = await _require_project(db, project_id)
    row = await _get_insight_row(db, project_id)
    completed = await _list_completed_interviews(db, project_id)
    completed_ids = [iv.id for iv in completed]
    return _row_to_read(project, row, completed_ids)


async def request_refresh(
    db: AsyncSession, project_id: uuid.UUID
) -> ProjectInsightRead:
    """Kick off a Claude refresh for a project.

    Returns the row in ``status='generating'`` once it's been persisted.
    The actual Claude call happens in a BackgroundTask (the API layer
    schedules :func:`generate_summary` after this returns).
    """
    project = await _require_project(db, project_id)
    completed = await _list_completed_interviews(db, project_id)
    completed_ids = [iv.id for iv in completed]

    if not completed_ids:
        raise NoCompletedInterviewsError(
            "refresh requires at least one completed interview."
        )

    row = await _get_insight_row(db, project_id)
    if row is not None and row.status is InsightStatus.generating:
        raise InsightAlreadyGeneratingError(
            "insight generation already in progress."
        )

    if row is None:
        row = ProjectInsight(
            project_id=project_id,
            status=InsightStatus.generating,
            summary_markdown=None,
            interview_ids=[],
            error_message=None,
            model=None,
            generated_at=None,
        )
        db.add(row)
    else:
        row.status = InsightStatus.generating
        # Clear the prior error so the polling client doesn't see a
        # stale failure message while we re-try.
        row.error_message = None

    await db.commit()
    await db.refresh(row)

    return _row_to_read(project, row, completed_ids)


def _format_pain_point(pp: PainPoint) -> str:
    timestamp = f"{pp.timestamp_start_sec:.1f}-{pp.timestamp_end_sec:.1f}s"
    return (
        f"  [severity {pp.severity} / {pp.type.value}] "
        f"{pp.text} "
        f"\"{pp.supporting_quote}\" ({timestamp})"
    )


def _render_interview_block(idx: int, interview: Interview) -> str:
    demo = interview.demographics or {}
    header_bits = [
        str(demo.get("name", "")) or "Unknown",
        str(demo.get("age", "")),
        str(demo.get("gender", "")),
        str(demo.get("country", "")),
        str(demo.get("job_role", "")),
        str(demo.get("industry", "")),
    ]
    header = ", ".join(bit for bit in header_bits if bit)
    lines = [f"## Interview {idx} — {header}", "Pain points:"]
    if not interview.pain_points:
        lines.append("  (none extracted)")
    else:
        for pp in interview.pain_points:
            lines.append(_format_pain_point(pp))
    return "\n".join(lines)


def _extract_summary_markdown(message: Any) -> str:
    """Pull the ``summary_markdown`` from the forced tool_use block."""
    content = getattr(message, "content", None) or []
    for block in content:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type != "tool_use":
            continue
        block_name = getattr(block, "name", None) or (
            block.get("name") if isinstance(block, dict) else None
        )
        if block_name != TOOL_NAME:
            continue
        block_input = getattr(block, "input", None)
        if block_input is None and isinstance(block, dict):
            block_input = block.get("input")
        if not isinstance(block_input, dict):
            raise RuntimeError(
                f"tool_use block input was not a dict: {type(block_input).__name__}"
            )
        summary = block_input.get("summary_markdown")
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("tool_use input did not include summary_markdown")
        return summary

    raise RuntimeError(
        f"Claude response did not include a {TOOL_NAME!r} tool_use block"
    )


async def _call_claude(interviews: list[Interview]) -> str:
    """Force the ``record_project_summary`` tool call and return the markdown."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    blocks = [
        _render_interview_block(idx, interview)
        for idx, interview in enumerate(interviews, start=1)
    ]
    user_text = (
        f"You're summarising {len(interviews)} customer interview(s) "
        "below. Each block is one interview with its demographics and "
        "extracted pain points.\n\n" + "\n\n".join(blocks)
    )

    system_blocks: Any = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    tools_arg: Any = [TOOL_DEFINITION]
    tool_choice_arg: Any = {"type": "tool", "name": TOOL_NAME}
    messages_arg: Any = [
        {"role": "user", "content": [{"type": "text", "text": user_text}]}
    ]

    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=cast(Any, system_blocks),
        tools=cast(Any, tools_arg),
        tool_choice=cast(Any, tool_choice_arg),
        messages=cast(Any, messages_arg),
    )

    return _extract_summary_markdown(message)


async def generate_summary(project_id: uuid.UUID) -> None:
    """Generate the project-level cross-interview summary.

    Owns its own DB session (BackgroundTask scope). On any failure,
    marks the row ``status='failed'`` with the error message. Designed
    so the API endpoint can just ``background_tasks.add_task`` this
    callable and forget.
    """
    async with async_session_maker() as db:
        row = await _get_insight_row(db, project_id)
        if row is None:
            logger.error(
                "generate_summary: no project_insights row for %s; aborting",
                project_id,
            )
            return

        try:
            interviews = await _list_completed_interviews(db, project_id)
            if not interviews:
                raise RuntimeError(
                    "no completed interviews to summarise (race vs. delete?)"
                )

            summary_markdown = await _call_claude(interviews)

            row.summary_markdown = summary_markdown
            row.interview_ids = [iv.id for iv in interviews]
            row.status = InsightStatus.idle
            row.error_message = None
            row.model = CLAUDE_MODEL
            row.generated_at = datetime.now(UTC)
            await db.commit()

        except Exception as exc:  # noqa: BLE001
            logger.exception("generate_summary failed for project %s", project_id)
            # Mark the row failed in a fresh session so we don't trip
            # any half-rolled-back state from the failed transaction.
            async with async_session_maker() as fail_db:
                fresh = await _get_insight_row(fail_db, project_id)
                if fresh is not None:
                    fresh.status = InsightStatus.failed
                    fresh.error_message = str(exc)
                    await fail_db.commit()
