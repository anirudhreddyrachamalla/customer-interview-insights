"""Project service — thin async repository over the ``projects`` table."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate


async def create_project(db: AsyncSession, payload: ProjectCreate) -> Project:
    """Insert a new project and return the persisted ORM row."""
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, project_id: uuid.UUID) -> Project | None:
    """Look up a project by primary key. Returns ``None`` if not found."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def list_projects(db: AsyncSession) -> Sequence[Project]:
    """Return all projects, newest first."""
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()
