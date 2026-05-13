"""Project endpoints — CRUD subset required by the v0 spec."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import ProblemDetail
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectRead
from app.services import projects as projects_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project = await projects_service.create_project(db, payload)
    return ProjectRead.model_validate(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(db: AsyncSession = Depends(get_db)) -> ProjectListResponse:
    projects = await projects_service.list_projects(db)
    return ProjectListResponse(items=[ProjectRead.model_validate(p) for p in projects])


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    project = await projects_service.get_project(db, project_id)
    if project is None:
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Project Not Found",
            detail=f"No project found with id {project_id}.",
            type_="https://interview-insights.local/problems/project-not-found",
        )
    return ProjectRead.model_validate(project)
