"""Pydantic v2 schemas for the Interview + PainPoint resources.

We deliberately do NOT include the on-disk ``audio_path`` in any
response schema — per ``CLAUDE.md`` (module boundaries), the frontend
only ever accesses audio via the streaming endpoint
``GET /api/v1/interviews/{id}/audio``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.demographics import DemographicsSchema


class InterviewType(StrEnum):
    """Interview taxonomy. Only one option in v0."""

    problem_validation = "problem_validation"


class InterviewStatus(StrEnum):
    """Lifecycle status of an interview's processing pipeline.

    Allowed transitions are enforced in
    :func:`app.services.interviews.transition_status`.
    """

    uploaded = "uploaded"
    transcribing = "transcribing"
    analyzing = "analyzing"
    completed = "completed"
    failed = "failed"


class PainPointRead(BaseModel):
    """A single Claude-extracted pain point, embedded inside InterviewRead."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str = Field(max_length=500)
    supporting_quote: str
    timestamp_start_sec: float
    timestamp_end_sec: float
    severity: int = Field(ge=1, le=5)
    created_at: datetime


class InterviewRead(BaseModel):
    """Response shape for interview endpoints.

    ``pain_points`` is embedded; ordering is the service layer's job
    (``severity DESC, created_at ASC``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    audio_filename: str
    audio_duration_sec: float | None
    type: InterviewType
    demographics: DemographicsSchema
    transcript_text: str | None
    transcript_segments: list[dict[str, Any]] | None
    meeting_notes: str | None = None
    status: InterviewStatus
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None
    pain_points: list[PainPointRead] = Field(default_factory=list)


class InterviewListResponse(BaseModel):
    """List wrapper used by ``GET /api/v1/projects/{project_id}/interviews``."""

    items: list[InterviewRead]
