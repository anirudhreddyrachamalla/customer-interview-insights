"""Audio + transcript file storage and HTTP Range streaming.

Two backends sit behind a single API: the legacy filesystem backend
(used by tests and local dev) and Azure Blob Storage (production).
Selection is driven by ``settings.storage_backend``.

Public surface:

* :func:`save_upload` / :func:`save_transcript_upload` — stream a
  multipart upload into the configured backend, returning a
  :class:`SavedAudio` / :class:`SavedTranscript` carrying the value to
  persist on the ``Interview`` row plus a local path for the duration
  probe / parser.
* :func:`delete_audio` / :func:`delete_transcript` — best-effort
  deletion (used when a post-upload check fails, e.g. duration cap).
* :func:`cleanup_temp` — drop the local probe tempfile (no-op in
  local-FS mode where the probe path IS the persisted file).
* :func:`get_duration` — best-effort duration probe via ``tinytag``.
* :func:`range_response` — HTTP Range-aware streaming response that
  works for both backends.
* :func:`content_type_for_path` — mime sniff used by the streaming
  endpoint.
* :func:`audio_view` / :func:`transcript_view` — async context managers
  that yield a local :class:`Path` for the configured backend (the
  on-disk file in local mode, a downloaded tempfile in blob mode).
  Used by the pipeline to feed AssemblyAI / the VTT parser regardless
  of where the bytes live.

Errors raised here are domain-level (``UploadTooLargeError``,
``UnsupportedAudioTypeError``) and translated to RFC 7807 responses at
the API layer.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.storage import azure_blob

logger = logging.getLogger(__name__)

# Allowed-list aligned with SPEC.md: "mp3, wav, m4a". We accept the
# common mime-type encodings browsers + curl send for each.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "audio/mpeg",  # .mp3
        "audio/mp3",  # .mp3 (some clients)
        "audio/wav",  # .wav
        "audio/x-wav",  # .wav (alt)
        "audio/wave",  # .wav (alt)
        "audio/x-m4a",  # .m4a
        "audio/mp4",  # .m4a / .mp4 container
        "audio/aac",  # .m4a/.aac
    }
)

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".wav", ".m4a"})

# 100 MB hard cap per SPEC.md.
MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024

# 90 minutes hard cap per SPEC.md.
MAX_DURATION_SEC: float = 90 * 60.0

# v1.2 transcript-upload limits — narrowed from v1.1's
# ``.txt``/``.vtt``/``.srt`` triple to just ``.vtt`` (SPEC_v1.2.md
# section 1, "Removed surfaces"). Some browsers / curl invocations
# don't send a registered mime for ``.vtt`` — accept the generic fall-
# backs (``text/plain``, ``application/octet-stream``) so the picker
# isn't trapped behind a quirky mime sniff.
ALLOWED_TRANSCRIPT_EXTENSIONS: frozenset[str] = frozenset({".vtt"})
ALLOWED_TRANSCRIPT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/vtt",
        "text/plain",
        "application/octet-stream",
    }
)
MAX_TRANSCRIPT_BYTES: int = 5 * 1024 * 1024  # 5 MB

# Streaming chunk size for Range responses (1 MiB).
_CHUNK_SIZE: int = 1024 * 1024

# Mime-type to use when serving by extension if the request didn't pin one.
_EXT_TO_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
}


class UploadTooLargeError(Exception):
    """Raised when an audio upload exceeds :data:`MAX_UPLOAD_BYTES`."""

    def __init__(self, size: int) -> None:
        super().__init__(f"upload exceeds {MAX_UPLOAD_BYTES} bytes ({size} bytes)")
        self.size = size


class UnsupportedAudioTypeError(Exception):
    """Raised when the upload's mime or extension is outside the allowlist."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class SavedAudio:
    """Outcome of a successful :func:`save_upload` call.

    ``key`` is the opaque identifier persisted on ``Interview.audio_path``.
    For the local backend it's the absolute on-disk path; for the blob
    backend it's just the blob name within the audio container.

    ``probe_path`` is a local filesystem path the caller can hand to
    tinytag for the duration check. ``is_temp`` flags whether the path
    should be unlinked once the probe is done (blob mode).
    """

    key: str
    probe_path: Path
    is_temp: bool


@dataclass
class SavedTranscript:
    key: str
    local_path: Path
    is_temp: bool


def _resolved_storage_dir() -> Path:
    """Return the absolute path to the audio storage directory.

    ``audio_storage_dir`` is read from settings; if relative, it's
    resolved against the ``backend/`` root so a worker started from any
    cwd still writes to the right place.
    """
    settings = get_settings()
    audio_dir = settings.audio_storage_dir
    if not audio_dir.is_absolute():
        backend_root = Path(__file__).resolve().parent.parent.parent
        audio_dir = backend_root / audio_dir
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def _resolved_transcript_storage_dir() -> Path:
    """Return the absolute path to the transcript storage directory.

    Lives as a sibling of the audio storage directory
    (``<audio_storage_dir>/../transcripts``) so a persistent disk
    hosts both — see ``SPEC_v1.1.md`` section 2 (Storage).
    """
    audio_dir = _resolved_storage_dir()
    transcript_dir = audio_dir.parent / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    return transcript_dir


def _extension_for(filename: str | None) -> str:
    """Return a lowercased extension (``.mp3`` etc.) from a filename.

    Raises :class:`UnsupportedAudioTypeError` if the extension isn't in
    :data:`ALLOWED_EXTENSIONS`.
    """
    if not filename:
        raise UnsupportedAudioTypeError("upload has no filename")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedAudioTypeError(
            f"extension {ext!r} not in allowed set {sorted(ALLOWED_EXTENSIONS)}"
        )
    return ext


def _validate_mime(content_type: str | None) -> None:
    """Reject obviously-wrong content types early.

    We're permissive: if the client didn't send one at all, fall back
    to extension-based validation. This matches what curl / fetch /
    Postman do with raw files.
    """
    if content_type is None or content_type == "":
        return
    # Strip parameters like "; charset=binary".
    primary = content_type.split(";", 1)[0].strip().lower()
    if primary in ALLOWED_MIME_TYPES:
        return
    raise UnsupportedAudioTypeError(
        f"content-type {primary!r} not in allowed set {sorted(ALLOWED_MIME_TYPES)}"
    )


# ---------------------------------------------------------------------------
# save_upload — branches on backend
# ---------------------------------------------------------------------------


async def save_upload(upload: UploadFile, interview_id: uuid.UUID) -> SavedAudio:
    """Persist an audio upload to the configured backend.

    Enforces the mime allowlist and the 100 MB size cap incrementally
    (no whole-file buffering). Returns a :class:`SavedAudio` whose
    ``key`` should be written to ``Interview.audio_path`` and whose
    ``probe_path`` is suitable for :func:`get_duration`.
    """
    _validate_mime(upload.content_type)
    ext = _extension_for(upload.filename)

    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        return await _save_upload_blob(upload, interview_id, ext, settings)
    return await _save_upload_local(upload, interview_id, ext)


async def _save_upload_local(
    upload: UploadFile, interview_id: uuid.UUID, ext: str
) -> SavedAudio:
    storage_dir = _resolved_storage_dir()
    dest = storage_dir / f"{interview_id}{ext}"

    total = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise UploadTooLargeError(total)
                fh.write(chunk)
    except UploadTooLargeError:
        try:
            dest.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - filesystem race
            logger.warning("failed to delete oversized upload at %s", dest)
        raise
    finally:
        await upload.close()

    return SavedAudio(key=str(dest), probe_path=dest, is_temp=False)


async def _save_upload_blob(
    upload: UploadFile, interview_id: uuid.UUID, ext: str, settings: Any
) -> SavedAudio:
    key = f"{interview_id}{ext}"
    container = settings.azure_storage_container_audio
    await azure_blob.upload_stream(
        upload,
        container=container,
        key=key,
        max_bytes=MAX_UPLOAD_BYTES,
        too_large_exc=UploadTooLargeError,
    )
    # tinytag needs a local file; download just for the probe.
    probe_path = await azure_blob.download_to_tempfile(container, key)
    return SavedAudio(key=key, probe_path=probe_path, is_temp=True)


# ---------------------------------------------------------------------------
# save_transcript_upload — branches on backend
# ---------------------------------------------------------------------------


async def save_transcript_upload(
    upload: UploadFile, interview_id: uuid.UUID
) -> SavedTranscript:
    """Persist a transcript upload to the configured backend.

    Enforces the ``.vtt``-only allowlist + the 5 MB cap (v1.2; see
    ``SPEC_v1.2.md`` section 1). Returns a :class:`SavedTranscript`
    whose ``key`` is what to write to ``Interview.transcript_path``.
    """
    filename = upload.filename
    if not filename:
        raise UnsupportedAudioTypeError("transcript upload has no filename")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_TRANSCRIPT_EXTENSIONS:
        raise UnsupportedAudioTypeError(
            f"extension {ext!r} not allowed for transcript uploads; "
            f"expected '.vtt'"
        )

    content_type = upload.content_type
    if content_type:
        primary = content_type.split(";", 1)[0].strip().lower()
        if primary and primary not in ALLOWED_TRANSCRIPT_MIME_TYPES:
            raise UnsupportedAudioTypeError(
                f"content-type {primary!r} not allowed for transcript uploads; "
                f"expected one of {sorted(ALLOWED_TRANSCRIPT_MIME_TYPES)}"
            )

    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        return await _save_transcript_blob(upload, interview_id, ext, settings)
    return await _save_transcript_local(upload, interview_id, ext)


async def _save_transcript_local(
    upload: UploadFile, interview_id: uuid.UUID, ext: str
) -> SavedTranscript:
    storage_dir = _resolved_transcript_storage_dir()
    dest = storage_dir / f"{interview_id}{ext}"

    total = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TRANSCRIPT_BYTES:
                    raise UploadTooLargeError(total)
                fh.write(chunk)
    except UploadTooLargeError:
        try:
            dest.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - filesystem race
            logger.warning("failed to delete oversized transcript at %s", dest)
        raise
    finally:
        await upload.close()

    return SavedTranscript(key=str(dest), local_path=dest, is_temp=False)


async def _save_transcript_blob(
    upload: UploadFile, interview_id: uuid.UUID, ext: str, settings: Any
) -> SavedTranscript:
    key = f"{interview_id}{ext}"
    container = settings.azure_storage_container_transcripts
    await azure_blob.upload_stream(
        upload,
        container=container,
        key=key,
        max_bytes=MAX_TRANSCRIPT_BYTES,
        too_large_exc=UploadTooLargeError,
    )
    local_path = await azure_blob.download_to_tempfile(container, key)
    return SavedTranscript(key=key, local_path=local_path, is_temp=True)


# ---------------------------------------------------------------------------
# Deletion + temp cleanup helpers
# ---------------------------------------------------------------------------


async def delete_audio(saved: SavedAudio) -> None:
    """Best-effort delete the persisted audio (used when a later check fails)."""
    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        from azure.storage.blob.aio import BlobServiceClient  # local import: optional

        # Re-derive the service client; small extra cost, simpler than threading state.
        from app.storage.azure_blob import _account_url, _credential  # noqa: PLC0415

        service = BlobServiceClient(account_url=_account_url(), credential=_credential())
        try:
            with contextlib.suppress(Exception):
                await service.get_blob_client(
                    container=settings.azure_storage_container_audio,
                    blob=saved.key,
                ).delete_blob()
        finally:
            await service.close()
    else:
        with contextlib.suppress(OSError):
            Path(saved.key).unlink(missing_ok=True)


def cleanup_temp(saved: SavedAudio | SavedTranscript) -> None:
    """Unlink the local probe / parse tempfile if one was created."""
    if not saved.is_temp:
        return
    path = saved.probe_path if isinstance(saved, SavedAudio) else saved.local_path
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Pipeline helpers: yield a local file path regardless of backend
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def audio_view(key: str) -> AsyncIterator[Path]:
    """Yield a local :class:`Path` for the persisted audio identified by ``key``.

    Local mode: yields the on-disk path directly.
    Blob mode: downloads the blob to a tempfile, yields its path, then
    unlinks on exit.
    """
    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        path = await azure_blob.download_to_tempfile(
            settings.azure_storage_container_audio, key
        )
        try:
            yield path
        finally:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
    else:
        yield Path(key)


@contextlib.asynccontextmanager
async def transcript_view(key: str) -> AsyncIterator[Path]:
    """Mirror of :func:`audio_view` for transcript files."""
    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        path = await azure_blob.download_to_tempfile(
            settings.azure_storage_container_transcripts, key
        )
        try:
            yield path
        finally:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
    else:
        yield Path(key)


# ---------------------------------------------------------------------------
# Duration + mime
# ---------------------------------------------------------------------------


def get_duration(path: Path) -> float | None:
    """Best-effort audio duration probe via ``tinytag``.

    Returns the duration in seconds, or ``None`` if tinytag fails or
    the file format isn't recognized.
    """
    try:
        from tinytag import TinyTag

        tag = TinyTag.get(str(path))
        duration = tag.duration
        if duration is None:
            return None
        return float(duration)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logger.warning("tinytag failed to probe %s: %s", path, exc)
        return None


def content_type_for_path(path: Path) -> str:
    """Map a file extension to a streaming mime type."""
    ext = path.suffix.lower()
    return _EXT_TO_MIME.get(ext, "application/octet-stream")


# ---------------------------------------------------------------------------
# HTTP Range streaming
# ---------------------------------------------------------------------------


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse an HTTP ``Range: bytes=start-end`` header.

    Returns ``(start, end)`` inclusive byte offsets. Raises
    :class:`ValueError` on malformed input or an unsatisfiable range
    (caller maps that to 416).
    """
    match = _RANGE_RE.match(range_header.strip())
    if not match:
        raise ValueError(f"malformed Range header: {range_header!r}")

    start_s, end_s = match.group(1), match.group(2)
    if start_s == "" and end_s == "":
        raise ValueError("empty Range header")

    if start_s == "":
        # Suffix form: last N bytes.
        suffix_len = int(end_s)
        if suffix_len <= 0:
            raise ValueError("zero-length suffix range")
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s != "" else file_size - 1

    if start < 0 or end < start or start >= file_size:
        raise ValueError(f"unsatisfiable range start={start} end={end} size={file_size}")
    # Clamp end to EOF.
    end = min(end, file_size - 1)
    return start, end


def _iter_local_file_range(path: Path, start: int, end: int) -> Any:
    def _gen():
        remaining = end - start + 1
        with path.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return _gen()


async def range_response(
    key_or_path: Path | str,
    range_header: str | None,
    mime: str,
) -> StreamingResponse:
    """Build a Range-aware StreamingResponse for a persisted audio file.

    ``key_or_path`` is whatever was stored on ``Interview.audio_path`` —
    an absolute path in local-FS mode, a blob name in Azure mode. The
    correct backend is dispatched automatically based on
    ``settings.storage_backend``.

    * No ``Range`` header -> 200 with the full file body.
    * Valid ``Range`` header -> 206 partial content.
    * Malformed or unsatisfiable Range -> 416.
    """
    settings = get_settings()
    if settings.storage_backend == "azure_blob":
        return await _range_response_blob(
            str(key_or_path), range_header, mime, settings
        )
    return _range_response_local(Path(key_or_path), range_header, mime)


def _range_response_local(
    path: Path, range_header: str | None, mime: str
) -> StreamingResponse:
    file_size = os.path.getsize(path)

    if range_header is None or range_header.strip() == "":
        return StreamingResponse(
            _iter_local_file_range(path, 0, file_size - 1),
            status_code=200,
            media_type=mime,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    try:
        start, end = _parse_range(range_header, file_size)
    except ValueError:
        return StreamingResponse(
            iter([b""]),
            status_code=416,
            media_type=mime,
            headers={
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
            },
        )

    chunk_len = end - start + 1
    return StreamingResponse(
        _iter_local_file_range(path, start, end),
        status_code=206,
        media_type=mime,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_len),
        },
    )


async def _range_response_blob(
    key: str, range_header: str | None, mime: str, settings: Any
) -> StreamingResponse:
    container = settings.azure_storage_container_audio
    file_size = await azure_blob.get_blob_size(container, key)

    if range_header is None or range_header.strip() == "":
        return StreamingResponse(
            azure_blob.iter_blob_range(container, key, 0, file_size - 1),
            status_code=200,
            media_type=mime,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    try:
        start, end = _parse_range(range_header, file_size)
    except ValueError:
        return StreamingResponse(
            iter([b""]),
            status_code=416,
            media_type=mime,
            headers={
                "Content-Range": f"bytes */{file_size}",
                "Accept-Ranges": "bytes",
            },
        )

    chunk_len = end - start + 1
    return StreamingResponse(
        azure_blob.iter_blob_range(container, key, start, end),
        status_code=206,
        media_type=mime,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_len),
        },
    )
