"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health as health_v1
from app.api.v1 import interviews as interviews_v1
from app.api.v1 import projects as projects_v1
from app.config import get_settings
from app.errors import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the audio storage directory exists before serving requests."""
    settings = get_settings()
    audio_dir = settings.audio_storage_dir
    if not audio_dir.is_absolute():
        # Resolve relative to the backend/ working directory so a process
        # launched from anywhere still writes into backend/storage/audio.
        backend_root = Path(__file__).resolve().parent.parent
        audio_dir = backend_root / audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="interview-insights backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health_v1.router, prefix="/api/v1")
app.include_router(projects_v1.router, prefix="/api/v1")
app.include_router(interviews_v1.project_router, prefix="/api/v1")
app.include_router(interviews_v1.router, prefix="/api/v1")
