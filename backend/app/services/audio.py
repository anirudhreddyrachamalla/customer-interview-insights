"""Audio file storage + streaming helpers.

Local-filesystem implementation for v0. The path is derived once from
:func:`app.config.get_settings` so tests can override the storage dir
without monkeypatching this module.

Public surface:

* :func:`save_upload` — stream a multipart ``UploadFile`` to disk under
  ``settings.audio_storage_dir``, named by interview UUID.
* :func:`get_duration` — best-effort duration probe via ``tinytag``.
* :func:`range_response` — HTTP Range-aware streaming response.
* :func:`content_type_for_path` — mime sniff used by the streaming endpoint.

Errors raised here are domain-level (``UploadTooLargeError``,
``UnsupportedAudioTypeError``) and translated to RFC 7807 responses at
the API layer.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from fastapi.responses import StreamingResponse

from app.config import get_settings

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


async def save_upload(upload: UploadFile, interview_id: uuid.UUID) -> Path:
    """Stream a multipart upload to ``<storage_dir>/<interview_id><ext>``.

    Enforces the mime allowlist and the 100 MB size cap. The size cap
    is enforced incrementally so we don't have to buffer the whole file
    in memory before rejecting it.

    Returns:
        Absolute :class:`Path` to the persisted file.
    """
    _validate_mime(upload.content_type)
    ext = _extension_for(upload.filename)

    storage_dir = _resolved_storage_dir()
    dest = storage_dir / f"{interview_id}{ext}"

    total = 0
    # Stream in fixed-size chunks. We open in binary write so the file
    # exists immediately; if validation fails mid-stream we clean up.
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
        # Best-effort cleanup of the partial file.
        try:
            dest.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - filesystem race
            logger.warning("failed to delete oversized upload at %s", dest)
        raise
    finally:
        await upload.close()

    return dest


def get_duration(path: Path) -> float | None:
    """Best-effort audio duration probe via ``tinytag``.

    Returns the duration in seconds, or ``None`` if tinytag fails or
    the file format isn't recognized. We deliberately swallow tinytag
    errors and log instead of raising so the upload endpoint can still
    proceed (duration is informational; the pipeline doesn't require
    it).
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

    Supports the three common forms:

    * ``bytes=0-99``        — first 100 bytes
    * ``bytes=100-``        — from byte 100 to EOF
    * ``bytes=-100``        — last 100 bytes
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


def _iter_file_range(path: Path, start: int, end: int) -> Any:
    """Yield bytes from ``path`` between ``start`` and ``end`` inclusive."""

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


def range_response(
    path: Path,
    range_header: str | None,
    mime: str,
) -> StreamingResponse:
    """Build a Range-aware StreamingResponse for an on-disk audio file.

    * No ``Range`` header -> 200 with the full file body.
    * Valid ``Range`` header -> 206 partial content with
      ``Content-Range`` / ``Content-Length`` / ``Accept-Ranges`` set.
    * Malformed or unsatisfiable Range -> 416 (raised as a ValueError
      that the caller should translate; here we short-circuit by
      returning a 416 StreamingResponse with an empty body).
    """
    file_size = os.path.getsize(path)

    if range_header is None or range_header.strip() == "":
        return StreamingResponse(
            _iter_file_range(path, 0, file_size - 1),
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
        _iter_file_range(path, start, end),
        status_code=206,
        media_type=mime,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_len),
        },
    )
