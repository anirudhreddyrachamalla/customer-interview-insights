"""Health endpoint — verifies the API process and DB connectivity."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Return ``{status, db}``. 200 if DB reachable, 503 otherwise."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "ok", "db": "error"},
        )
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
