"""Pydantic v2 schemas for the ProjectInsight resource (v1.1).

The insights pane on ``/projects/{id}`` is fed by a single row per
project that Claude regenerates on demand. See ``SPEC_v1.1.md``
section 3 for the contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class InsightStatus(StrEnum):
    """Lifecycle of a per-project Claude-generated summary.

    The synthesised "no row yet" state served by GET is ``idle`` with
    a null ``summary_markdown``; ``generating`` is the in-flight state
    after ``POST /refresh``; ``failed`` is set when the BackgroundTask
    catches an exception from Claude.
    """

    idle = "idle"
    generating = "generating"
    failed = "failed"


class ProjectInsightRead(BaseModel):
    """Response shape for ``GET`` / ``POST`` insights endpoints.

    ``is_stale`` is server-computed: ``True`` when the snapshot of
    completed interview IDs at last generation differs from the current
    set. Before the first generation, ``is_stale`` is ``False`` (the
    UI shows the empty state in that case).
    """

    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    status: InsightStatus
    summary_markdown: str | None
    interview_count_summarised: int
    interview_count_completed: int
    is_stale: bool
    error_message: str | None
    model: str | None
    generated_at: datetime | None
    updated_at: datetime
