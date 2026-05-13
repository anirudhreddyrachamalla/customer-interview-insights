"""Pydantic v2 request/response schemas for the Project resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """Request body for ``POST /api/v1/projects``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectRead(BaseModel):
    """Response shape for project endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """List wrapper used by ``GET /api/v1/projects``."""

    items: list[ProjectRead]
