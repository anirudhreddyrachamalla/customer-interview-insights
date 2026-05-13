"""Interview service — repository + status state machine.

The repository methods stay thin so endpoints can delegate without
duplicating SQL. The state machine in :func:`transition_status` is the
single source of truth for legal status transitions and is unit-tested
in ``tests/test_interviews.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.interview import Interview
from app.models.pain_point import PainPoint
from app.schemas.demographics import DemographicsSchema
from app.schemas.interview import InterviewSourceKind, InterviewStatus, InterviewType


class InvalidStatusTransitionError(Exception):
    """Raised when a caller tries to apply a disallowed status transition."""

    def __init__(self, current: InterviewStatus, attempted: InterviewStatus) -> None:
        super().__init__(f"cannot transition interview from {current.value} to {attempted.value}")
        self.current = current
        self.attempted = attempted


# Allowed transitions, sourced from the task brief:
#
# - uploaded     -> transcribing
# - transcribing -> analyzing
# - analyzing    -> completed
# - *            -> failed (except failed -> failed, completed is terminal)
# - failed       -> transcribing  (retry path)
#
# ``completed`` is terminal (no outgoing edges).
_ALLOWED_TRANSITIONS: dict[InterviewStatus, frozenset[InterviewStatus]] = {
    InterviewStatus.uploaded: frozenset({InterviewStatus.transcribing, InterviewStatus.failed}),
    InterviewStatus.transcribing: frozenset({InterviewStatus.analyzing, InterviewStatus.failed}),
    InterviewStatus.analyzing: frozenset({InterviewStatus.completed, InterviewStatus.failed}),
    InterviewStatus.completed: frozenset(),
    InterviewStatus.failed: frozenset({InterviewStatus.transcribing}),
}


def _is_allowed(current: InterviewStatus, new: InterviewStatus) -> bool:
    return new in _ALLOWED_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Repository methods
# ---------------------------------------------------------------------------


async def create_interview(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    interview_id: uuid.UUID,
    demographics: DemographicsSchema,
    type_: InterviewType,
    audio_path: str | None,
    audio_filename: str,
    audio_duration_sec: float | None,
    meeting_notes: str | None = None,
    source_kind: InterviewSourceKind = InterviewSourceKind.audio,
    transcript_path: str | None = None,
) -> Interview:
    """Insert an ``Interview`` row in status ``uploaded`` and return it.

    ``interview_id`` is passed in (not generated here) because the
    upload endpoint pre-generates it so the on-disk filename and DB id
    match.

    ``meeting_notes`` must already be normalized by the caller (strip
    whitespace, empty -> ``None``, length-cap enforced). This service
    persists it as-is.

    v1.1: ``source_kind`` defaults to ``audio`` so existing call sites
    keep working. For transcript uploads, ``audio_path`` is ``None`` and
    ``transcript_path`` carries the on-disk path.
    """
    interview = Interview(
        id=interview_id,
        project_id=project_id,
        source_kind=source_kind,
        audio_path=audio_path,
        audio_filename=audio_filename,
        audio_duration_sec=audio_duration_sec,
        transcript_path=transcript_path,
        type=type_,
        demographics=demographics.model_dump(mode="json"),
        meeting_notes=meeting_notes,
        status=InterviewStatus.uploaded,
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview


async def get_interview(db: AsyncSession, interview_id: uuid.UUID) -> Interview | None:
    """Fetch an interview with pain_points eager-loaded + sorted.

    Pain points are ordered by ``severity DESC, created_at ASC`` to
    match the SPEC's UI ordering. We do the sort in Python after the
    eager-load so the relationship stays simple and the endpoint can
    return the list as-is.
    """
    result = await db.execute(
        select(Interview)
        .where(Interview.id == interview_id)
        .options(selectinload(Interview.pain_points))
    )
    interview = result.scalar_one_or_none()
    if interview is not None:
        interview.pain_points.sort(key=lambda p: (-p.severity, p.created_at))
    return interview


async def list_interviews(db: AsyncSession, project_id: uuid.UUID) -> Sequence[Interview]:
    """Return all interviews in a project, newest first.

    Pain points are eager-loaded so the list endpoint can embed them
    without an N+1.
    """
    result = await db.execute(
        select(Interview)
        .where(Interview.project_id == project_id)
        .options(selectinload(Interview.pain_points))
        .order_by(Interview.created_at.desc())
    )
    interviews = list(result.scalars().all())
    for iv in interviews:
        iv.pain_points.sort(key=lambda p: (-p.severity, p.created_at))
    return interviews


# ---------------------------------------------------------------------------
# State machine + lifecycle helpers
# ---------------------------------------------------------------------------


async def transition_status(
    db: AsyncSession,
    interview: Interview,
    new_status: InterviewStatus,
) -> Interview:
    """Apply a status transition, enforcing the state machine.

    Raises :class:`InvalidStatusTransitionError` on a disallowed move.
    """
    current = interview.status
    if not _is_allowed(current, new_status):
        raise InvalidStatusTransitionError(current=current, attempted=new_status)
    interview.status = new_status
    await db.commit()
    await db.refresh(interview)
    return interview


async def mark_failed(
    db: AsyncSession,
    interview: Interview,
    error_message: str,
) -> Interview:
    """Move an interview to ``failed`` and store the error message."""
    if not _is_allowed(interview.status, InterviewStatus.failed):
        raise InvalidStatusTransitionError(
            current=interview.status, attempted=InterviewStatus.failed
        )
    interview.status = InterviewStatus.failed
    interview.error_message = error_message
    await db.commit()
    await db.refresh(interview)
    return interview


async def mark_completed(db: AsyncSession, interview: Interview) -> Interview:
    """Move an interview to ``completed`` and stamp ``processed_at``."""
    if not _is_allowed(interview.status, InterviewStatus.completed):
        raise InvalidStatusTransitionError(
            current=interview.status, attempted=InterviewStatus.completed
        )
    interview.status = InterviewStatus.completed
    interview.processed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(interview)
    return interview


async def clear_error_for_retry(db: AsyncSession, interview: Interview) -> Interview:
    """Reset ``error_message`` and move from ``failed`` to ``transcribing``.

    Used by ``POST /interviews/{id}/retry``. Raises
    :class:`InvalidStatusTransitionError` if the interview isn't in
    ``failed``.
    """
    if interview.status is not InterviewStatus.failed:
        raise InvalidStatusTransitionError(
            current=interview.status, attempted=InterviewStatus.transcribing
        )
    interview.error_message = None
    interview.status = InterviewStatus.transcribing
    await db.commit()
    await db.refresh(interview)
    return interview


# ---------------------------------------------------------------------------
# Pain-point persistence (used by the pipeline)
# ---------------------------------------------------------------------------


async def persist_pain_points(
    db: AsyncSession,
    interview: Interview,
    pain_points: list[dict[str, object]],
) -> list[PainPoint]:
    """Insert pain-point rows for an interview and return them.

    The caller is responsible for validating that supporting_quote
    text is present verbatim in the transcript before calling this.
    """
    from app.schemas.interview import PainPointType

    rows: list[PainPoint] = []
    for pp in pain_points:
        # The pipeline validates pain-point shape upstream; coerce here
        # defensively in case the extraction stub or a test passes a
        # mixed-type dict.
        type_raw = pp.get("type")
        pp_type = (
            PainPointType(type_raw)
            if isinstance(type_raw, str) and type_raw in {m.value for m in PainPointType}
            else PainPointType.pain_point
        )
        rows.append(
            PainPoint(
                interview_id=interview.id,
                text=str(pp["text"]),
                supporting_quote=str(pp["supporting_quote"]),
                timestamp_start_sec=float(str(pp["timestamp_start_sec"])),
                timestamp_end_sec=float(str(pp["timestamp_end_sec"])),
                severity=int(str(pp["severity"])),
                type=pp_type,
            )
        )
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows
