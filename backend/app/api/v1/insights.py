"""Project insights endpoints (v1.1).

GET   /api/v1/projects/{id}/insights         -> 200 ProjectInsightRead
POST  /api/v1/projects/{id}/insights/refresh -> 202 ProjectInsightRead
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import ProblemDetail
from app.schemas.insight import ProjectInsightRead
from app.services import insights as insights_service

router = APIRouter(prefix="/projects/{project_id}/insights", tags=["insights"])


_PROJECT_NOT_FOUND_TYPE = "https://interview-insights.local/problems/project-not-found"
_CONFLICT_TYPE = "https://interview-insights.local/problems/insights-conflict"


def _project_not_found(project_id: uuid.UUID) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Project Not Found",
        detail=f"No project found with id {project_id}.",
        type_=_PROJECT_NOT_FOUND_TYPE,
    )


@router.get("", response_model=ProjectInsightRead)
async def get_project_insights(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectInsightRead:
    try:
        return await insights_service.get_or_synthesize_view(db, project_id)
    except insights_service.ProjectNotFoundError as exc:
        raise _project_not_found(project_id) from exc


@router.post(
    "/refresh",
    response_model=ProjectInsightRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_project_insights(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> ProjectInsightRead:
    try:
        view = await insights_service.request_refresh(db, project_id)
    except insights_service.ProjectNotFoundError as exc:
        raise _project_not_found(project_id) from exc
    except insights_service.NoCompletedInterviewsError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="refresh requires at least one completed interview.",
            type_=_CONFLICT_TYPE,
        ) from exc
    except insights_service.InsightAlreadyGeneratingError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail="insight generation already in progress.",
            type_=_CONFLICT_TYPE,
        ) from exc

    background_tasks.add_task(insights_service.generate_summary, project_id)
    return view
