"""Interview endpoints.

Routes live on two routers because the URL prefixes differ:

* :data:`project_router` is mounted at ``/projects/{project_id}/interviews``
  and owns create + list.
* :data:`router` is mounted at ``/interviews`` and owns get + retry +
  audio streaming.

The endpoints stay thin: parsing -> service call -> schema. All audio
file handling lives in :mod:`app.services.audio`; all state-machine
logic lives in :mod:`app.services.interviews`.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.errors import ProblemDetail
from app.models.interview import Interview
from app.schemas.demographics import DemographicsSchema
from app.schemas.interview import (
    InterviewListResponse,
    InterviewRead,
    InterviewSourceKind,
    InterviewStatus,
    InterviewType,
)
from app.services import audio as audio_service
from app.services import interviews as interviews_service
from app.services import projects as projects_service
from app.services.pipeline import run_pipeline

# Mounted under /api/v1/projects/{project_id}/interviews in app.main.
project_router = APIRouter(prefix="/projects/{project_id}/interviews", tags=["interviews"])
# Mounted under /api/v1/interviews in app.main.
router = APIRouter(prefix="/interviews", tags=["interviews"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALIDATION_TYPE = "https://interview-insights.local/problems/validation-error"
_NOT_FOUND_TYPE = "https://interview-insights.local/problems/interview-not-found"
_PROJECT_NOT_FOUND_TYPE = "https://interview-insights.local/problems/project-not-found"
_CONFLICT_TYPE = "https://interview-insights.local/problems/invalid-status-transition"
_TOO_LARGE_TYPE = "https://interview-insights.local/problems/upload-too-large"
_UNSUPPORTED_TYPE = "https://interview-insights.local/problems/unsupported-media-type"
_NO_AUDIO_TYPE = "https://interview-insights.local/problems/no-audio-source"

# Hard cap on meeting_notes (server-side). Locked by the team-lead in
# the v0.1 feature spec — anything longer is rejected 422.
MEETING_NOTES_MAX_LEN = 10_000


def _to_read_model(interview: Interview) -> InterviewRead:
    """Build an :class:`InterviewRead` from an ORM ``Interview``.

    ``model_validate`` handles the simple fields; we explicitly hand it
    the demographics dict so Pydantic re-validates it on the way out
    (catches any drift between the JSONB column and the schema).
    """
    return InterviewRead.model_validate(
        {
            "id": interview.id,
            "project_id": interview.project_id,
            "source_kind": interview.source_kind,
            "audio_filename": interview.audio_filename,
            "audio_duration_sec": interview.audio_duration_sec,
            "type": interview.type,
            "demographics": interview.demographics,
            "transcript_text": interview.transcript_text,
            "transcript_segments": interview.transcript_segments,
            "meeting_notes": interview.meeting_notes,
            "status": interview.status,
            "error_message": interview.error_message,
            "created_at": interview.created_at,
            "processed_at": interview.processed_at,
            "pain_points": list(interview.pain_points),
        }
    )


async def _require_project(db: AsyncSession, project_id: uuid.UUID) -> None:
    project = await projects_service.get_project(db, project_id)
    if project is None:
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Project Not Found",
            detail=f"No project found with id {project_id}.",
            type_=_PROJECT_NOT_FOUND_TYPE,
        )


async def _require_interview(db: AsyncSession, interview_id: uuid.UUID) -> Interview:
    interview = await interviews_service.get_interview(db, interview_id)
    if interview is None:
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Interview Not Found",
            detail=f"No interview found with id {interview_id}.",
            type_=_NOT_FOUND_TYPE,
        )
    return interview


def _normalize_meeting_notes(raw: str | None) -> str | None:
    """Strip whitespace; empty -> ``None``; reject overlong with 422.

    Empty string and whitespace-only strings are normalized to ``None``
    so the DB only ever stores a non-empty value or NULL. Anything
    longer than :data:`MEETING_NOTES_MAX_LEN` is rejected with an RFC
    7807 422 carrying ``errors[0].loc == ["meeting_notes"]`` so the
    frontend can render the message inline.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if len(stripped) > MEETING_NOTES_MAX_LEN:
        raise ProblemDetail(
            status_code=422,
            title="Validation Error",
            detail=(
                f"meeting_notes exceeds the {MEETING_NOTES_MAX_LEN}-character "
                f"limit (got {len(stripped)} characters)."
            ),
            type_=_VALIDATION_TYPE,
            errors=[
                {
                    "loc": ["meeting_notes"],
                    "msg": (
                        f"String should have at most {MEETING_NOTES_MAX_LEN} characters"
                    ),
                    "type": "string_too_long",
                }
            ],
        )
    return stripped


def _parse_demographics(raw: str) -> DemographicsSchema:
    """Parse the multipart ``demographics`` field (a JSON string) into a schema.

    422 RFC 7807 on either JSON decode failure or schema validation
    failure. The endpoint owns this rather than letting FastAPI handle
    it because ``demographics`` arrives as a form field (a string), not
    a request body, so FastAPI's automatic validation doesn't apply.
    """
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProblemDetail(
            status_code=422,
            title="Validation Error",
            detail=f"demographics field is not valid JSON: {exc.msg}",
            type_=_VALIDATION_TYPE,
        ) from exc

    try:
        return DemographicsSchema.model_validate(decoded)
    except ValidationError as exc:
        # Surface the structured Pydantic errors as the RFC 7807 'errors'
        # member (matches the projects validation flow).
        raise ProblemDetail(
            status_code=422,
            title="Validation Error",
            detail="demographics failed validation.",
            type_=_VALIDATION_TYPE,
            headers={"X-Validation-Errors": "demographics"},
        ) from exc


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/interviews
# ---------------------------------------------------------------------------


@project_router.post(
    "",
    response_model=InterviewRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_interview(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    type: InterviewType = Form(...),  # noqa: A002 - matches the public field name
    demographics: str = Form(...),
    audio: UploadFile | None = File(None),
    transcript: UploadFile | None = File(None),
    meeting_notes: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    """Create an interview row, persist the upload, kick off the pipeline.

    v1.1: accepts EITHER ``audio`` or ``transcript`` (exactly one).
    Zero or both is a 422 with ``errors[0].loc == ["audio"]`` so the
    frontend can render the message under the upload picker.
    """
    await _require_project(db, project_id)

    # Exactly-one-of validation. ``filename`` is the reliable presence
    # signal — an absent multipart part can still arrive as a stub
    # ``UploadFile`` with an empty filename.
    has_audio = audio is not None and bool(audio.filename)
    has_transcript = transcript is not None and bool(transcript.filename)
    if has_audio == has_transcript:
        raise ProblemDetail(
            status_code=422,
            title="Validation Error",
            detail="exactly one of 'audio' or 'transcript' is required.",
            type_=_VALIDATION_TYPE,
            errors=[
                {
                    "loc": ["audio"],
                    "msg": "exactly one of 'audio' or 'transcript' is required.",
                    "type": "value_error.missing",
                }
            ],
        )

    # Demographics validation. Done before touching disk so we don't
    # write a file we're about to reject.
    demographics_obj = _parse_demographics(demographics)

    # Normalize meeting_notes (strip + empty -> NULL + length cap). Done
    # before disk I/O so a rejected upload doesn't leak a file.
    meeting_notes_value = _normalize_meeting_notes(meeting_notes)

    interview_id = uuid.uuid4()

    if has_audio:
        assert audio is not None  # narrowed by has_audio
        interview = await _create_audio_interview(
            db,
            project_id=project_id,
            interview_id=interview_id,
            audio=audio,
            demographics_obj=demographics_obj,
            type_=type,
            meeting_notes_value=meeting_notes_value,
        )
    else:
        assert transcript is not None
        interview = await _create_transcript_interview(
            db,
            project_id=project_id,
            interview_id=interview_id,
            transcript=transcript,
            demographics_obj=demographics_obj,
            type_=type,
            meeting_notes_value=meeting_notes_value,
        )

    # Re-load so the response carries an empty pain_points list (the
    # service returns the row without the relationship populated).
    interview = await _require_interview(db, interview.id)

    background_tasks.add_task(run_pipeline, interview.id)

    return _to_read_model(interview)


async def _create_audio_interview(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    interview_id: uuid.UUID,
    audio: UploadFile,
    demographics_obj: DemographicsSchema,
    type_: InterviewType,
    meeting_notes_value: str | None,
) -> Interview:
    """Persist an audio-sourced upload + interview row."""
    try:
        audio_path = await audio_service.save_upload(audio, interview_id)
    except audio_service.UploadTooLargeError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload Too Large",
            detail=(
                f"audio upload exceeds the {audio_service.MAX_UPLOAD_BYTES} "
                f"byte limit (got {exc.size} bytes)."
            ),
            type_=_TOO_LARGE_TYPE,
        ) from exc
    except audio_service.UnsupportedAudioTypeError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            title="Unsupported Media Type",
            detail=exc.detail,
            type_=_UNSUPPORTED_TYPE,
        ) from exc

    duration = audio_service.get_duration(audio_path)
    if duration is not None and duration > audio_service.MAX_DURATION_SEC:
        with contextlib.suppress(OSError):  # pragma: no cover
            audio_path.unlink(missing_ok=True)
        raise ProblemDetail(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload Too Large",
            detail=(
                f"audio duration {duration:.1f}s exceeds the "
                f"{audio_service.MAX_DURATION_SEC:.0f}s limit."
            ),
            type_=_TOO_LARGE_TYPE,
        )

    return await interviews_service.create_interview(
        db,
        project_id=project_id,
        interview_id=interview_id,
        demographics=demographics_obj,
        type_=type_,
        source_kind=InterviewSourceKind.audio,
        audio_path=str(audio_path),
        audio_filename=audio.filename or audio_path.name,
        audio_duration_sec=duration,
        meeting_notes=meeting_notes_value,
        transcript_path=None,
    )


async def _create_transcript_interview(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    interview_id: uuid.UUID,
    transcript: UploadFile,
    demographics_obj: DemographicsSchema,
    type_: InterviewType,
    meeting_notes_value: str | None,
) -> Interview:
    """Persist a transcript-sourced upload + interview row."""
    try:
        transcript_path = await audio_service.save_transcript_upload(
            transcript, interview_id
        )
    except audio_service.UploadTooLargeError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload Too Large",
            detail=(
                f"transcript upload exceeds the {audio_service.MAX_TRANSCRIPT_BYTES} "
                f"byte limit (got {exc.size} bytes)."
            ),
            type_=_TOO_LARGE_TYPE,
        ) from exc
    except audio_service.UnsupportedAudioTypeError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            title="Unsupported Media Type",
            detail=exc.detail,
            type_=_UNSUPPORTED_TYPE,
        ) from exc

    return await interviews_service.create_interview(
        db,
        project_id=project_id,
        interview_id=interview_id,
        demographics=demographics_obj,
        type_=type_,
        source_kind=InterviewSourceKind.transcript,
        audio_path=None,
        audio_filename=transcript.filename or transcript_path.name,
        audio_duration_sec=None,
        meeting_notes=meeting_notes_value,
        transcript_path=str(transcript_path),
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/interviews
# ---------------------------------------------------------------------------


@project_router.get("", response_model=InterviewListResponse)
async def list_interviews(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InterviewListResponse:
    await _require_project(db, project_id)
    rows = await interviews_service.list_interviews(db, project_id)
    return InterviewListResponse(items=[_to_read_model(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /interviews/{id}
# ---------------------------------------------------------------------------


@router.get("/{interview_id}", response_model=InterviewRead)
async def get_interview(
    interview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    interview = await _require_interview(db, interview_id)
    return _to_read_model(interview)


# ---------------------------------------------------------------------------
# POST /interviews/{id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/{interview_id}/retry",
    response_model=InterviewRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_interview(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> InterviewRead:
    interview = await _require_interview(db, interview_id)

    if interview.status is not InterviewStatus.failed:
        raise ProblemDetail(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=(
                f"interview status is {interview.status.value!r}; retry is only "
                "valid from 'failed'."
            ),
            type_=_CONFLICT_TYPE,
        )

    try:
        await interviews_service.clear_error_for_retry(db, interview)
    except interviews_service.InvalidStatusTransitionError as exc:
        raise ProblemDetail(
            status_code=status.HTTP_409_CONFLICT,
            title="Conflict",
            detail=str(exc),
            type_=_CONFLICT_TYPE,
        ) from exc

    background_tasks.add_task(run_pipeline, interview.id)

    refreshed = await _require_interview(db, interview.id)
    return _to_read_model(refreshed)


# ---------------------------------------------------------------------------
# GET /interviews/{id}/audio
# ---------------------------------------------------------------------------


@router.get("/{interview_id}/audio")
async def stream_audio(
    interview_id: uuid.UUID,
    range: str | None = Header(default=None),  # noqa: A002 - HTTP header name
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    interview = await _require_interview(db, interview_id)
    # v1.1: transcript-sourced interviews never have audio. Safety net
    # for direct URL hits — the UI no longer shows the audio player for
    # those rows.
    if interview.source_kind is InterviewSourceKind.transcript:
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Audio Not Found",
            detail="this interview has no audio (source_kind = transcript).",
            type_=_NO_AUDIO_TYPE,
        )

    if not interview.audio_path:
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Audio Not Found",
            detail=f"audio file for interview {interview_id} is missing on disk.",
            type_=_NOT_FOUND_TYPE,
        )
    audio_path = Path(interview.audio_path)
    if not audio_path.exists():
        raise ProblemDetail(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Audio Not Found",
            detail=f"audio file for interview {interview_id} is missing on disk.",
            type_=_NOT_FOUND_TYPE,
        )

    mime = audio_service.content_type_for_path(audio_path)
    return audio_service.range_response(audio_path, range, mime)
