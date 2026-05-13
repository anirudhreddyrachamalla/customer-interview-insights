"""Transcript-file parser — turns ``.vtt`` into the canonical
transcript dict the pipeline already expects.

Public surface:

* :func:`parse` — single entry-point, dispatched by file extension.
* :func:`render_formatted` — produce the preprocessed display string
  used by the v1.2 detail page (cue-by-cue blocks).
* :class:`TranscriptParseError` — raised on malformed input.

The :func:`parse` return shape mirrors what
``app.services.transcription.transcribe`` produces, so the rest of the
pipeline doesn't care whether the transcript originated from
AssemblyAI or from a file upload::

    {
        "text": str,
        "segments": [
            {"speaker": str, "start": float, "end": float, "text": str},
            ...
        ],
        "language_code": None,
        "duration_sec": float | None,
    }

v1.2 shrank the supported extension set to ``.vtt`` only. ``.txt`` and
``.srt`` (shipped in v1.1) now raise
:class:`TranscriptParseError`.

This module is pure: it reads the file path it's given and does no
network / Anthropic / AssemblyAI calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

__all__ = ["TranscriptParseError", "parse", "render_formatted"]


# Only ``.vtt`` is supported in v1.2.
_SUPPORTED_EXTENSIONS = frozenset({".vtt"})

# ``Speaker A:`` / ``Speaker B:`` etc. — the convention we surface in
# the prompt + frontend. Captures a single uppercase letter so transcripts
# from Otter / Zoom / etc. match the same shape AssemblyAI emits.
_SPEAKER_PREFIX_RE = re.compile(r"^\s*Speaker\s+([A-Z][A-Z0-9]?)\s*:\s*(.*)$")

# ``<v Speaker A>...`` VTT voice-tag form.
_VTT_VOICE_TAG_RE = re.compile(r"<v\s+(?:Speaker\s+)?([A-Za-z0-9_ -]+)>(.*?)(?:</v>)?$")

# VTT timestamp lines — ``HH:MM:SS.mmm --> HH:MM:SS.mmm`` (or ``MM:SS.mmm``).
_TIMESTAMP_LINE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
    r"\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
    r"\s*(.*)$"
)


class TranscriptParseError(Exception):
    """Raised when a transcript file is malformed or unreadable."""


def parse(path: Path) -> dict[str, Any]:
    """Parse a VTT transcript file into the canonical transcript dict.

    Raises :class:`TranscriptParseError` on:

    * unsupported extension (anything other than ``.vtt``)
    * non-UTF-8 contents
    * empty file
    * structurally malformed VTT (missing ``WEBVTT`` header, bad
      timestamp line, etc.)
    """
    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise TranscriptParseError(
            f"unsupported transcript format {ext!r}; expected '.vtt'"
        )

    raw = _read_text(path)
    return _parse_vtt(raw)


def render_formatted(path: Path) -> str:
    """Render a VTT file into the v1.2 preprocessed display string.

    Each cue becomes a two-line block::

        [MM:SS - MM:SS] Speaker A
        The customer's words on this cue, as written in the VTT.

    Blocks are separated by a single blank line. The ``WEBVTT`` header,
    cue indices, and STYLE blocks are stripped.

    Speaker resolution falls back in this order:

    1. ``<v Speaker X>`` voice tag inside the cue payload.
    2. ``Speaker X:`` prefix inside the cue payload.
    3. Default ``Speaker A``.

    Raises :class:`TranscriptParseError` on the same conditions as
    :func:`parse`.
    """
    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise TranscriptParseError(
            f"unsupported transcript format {ext!r}; expected '.vtt'"
        )

    raw = _read_text(path)
    parsed = _parse_vtt(raw)
    segments = parsed["segments"]

    blocks: list[str] = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        speaker = str(seg.get("speaker", "A"))
        text = str(seg.get("text", "")).strip()
        header = f"[{_format_timestamp(start)} - {_format_timestamp(end)}] Speaker {speaker}"
        blocks.append(f"{header}\n{text}")

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Shared file IO
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError as exc:
        raise TranscriptParseError(f"transcript file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise TranscriptParseError(
            f"transcript file is not valid UTF-8: {path}"
        ) from exc

    if not raw.strip():
        raise TranscriptParseError(f"transcript file is empty: {path}")
    return raw


# ---------------------------------------------------------------------------
# .vtt
# ---------------------------------------------------------------------------


def _format_timestamp(seconds: float) -> str:
    """Render a float number of seconds as ``MM:SS``.

    Matches the format ``extraction._format_timestamp`` uses in the
    Claude prompt, so the preprocessed string is visually consistent
    with the timestamps surfaced elsewhere.
    """
    secs = max(0, int(round(seconds)))
    minutes, sec = divmod(secs, 60)
    return f"{minutes:02d}:{sec:02d}"


def _parse_timestamp(token: str) -> float:
    """Parse ``HH:MM:SS.mmm`` / ``HH:MM:SS,mmm`` / ``MM:SS.mmm`` into seconds."""
    token = token.replace(",", ".")
    parts = token.split(":")
    try:
        if len(parts) == 3:
            hh, mm, ss = parts
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
        if len(parts) == 2:
            mm, ss = parts
            return int(mm) * 60 + float(ss)
    except ValueError as exc:
        raise TranscriptParseError(f"malformed timestamp {token!r}") from exc
    raise TranscriptParseError(f"malformed timestamp {token!r}")


def _extract_cue_speaker_and_text(payload: str) -> tuple[str, str]:
    """Pull ``Speaker A`` (or a ``<v Speaker A>``) out of a cue's text."""
    payload = payload.strip()

    # Try ``<v Speaker A>`` first (VTT-specific).
    voice = _VTT_VOICE_TAG_RE.match(payload)
    if voice:
        raw_speaker = voice.group(1).strip()
        # Single-letter speakers stay as-is; anything else is collapsed
        # to a short label so the frontend still has something stable.
        speaker = raw_speaker.upper() if len(raw_speaker) <= 2 else raw_speaker
        cue_text = voice.group(2).strip()
        return speaker, cue_text

    # Fall back to ``Speaker A: ...`` prefix.
    prefix = _SPEAKER_PREFIX_RE.match(payload)
    if prefix:
        return prefix.group(1), prefix.group(2).strip()

    return "A", payload


def _parse_vtt(raw: str) -> dict[str, Any]:
    """Parse VTT content into the canonical transcript dict."""
    # Strip an optional BOM.
    raw = raw.lstrip("﻿")
    lines = raw.splitlines()

    # First non-empty line should be ``WEBVTT`` (we tolerate trailing notes).
    first_nonempty = next((line for line in lines if line.strip()), "")
    if not first_nonempty.upper().startswith("WEBVTT"):
        raise TranscriptParseError(
            "VTT file must start with a 'WEBVTT' header"
        )

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    last_end = 0.0

    i = 0
    n = len(lines)
    while i < n:
        # Skip blank lines.
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break

        # An optional cue id line (VTT — sometimes present). If the
        # current line is NOT a timestamp line, treat it as the id and
        # move on.
        if not _TIMESTAMP_LINE_RE.match(lines[i]):
            # Special-case the VTT header itself, which we already accepted.
            if lines[i].strip().upper().startswith("WEBVTT"):
                i += 1
                continue
            i += 1
            if i >= n:
                break

        if i >= n or not lines[i].strip():
            break

        timestamp_match = _TIMESTAMP_LINE_RE.match(lines[i])
        if not timestamp_match:
            raise TranscriptParseError(
                f"expected timestamp line, got {lines[i]!r}"
            )

        start_token = timestamp_match.group(1)
        end_token = timestamp_match.group(2)
        start = _parse_timestamp(start_token)
        end = _parse_timestamp(end_token)
        if end < start:
            raise TranscriptParseError(
                f"cue end ({end_token}) is before start ({start_token})"
            )
        i += 1

        # Collect cue text lines until a blank line or EOF.
        cue_lines: list[str] = []
        while i < n and lines[i].strip():
            cue_lines.append(lines[i])
            i += 1

        if not cue_lines:
            # Empty cue — skip rather than fail. Common in real-world VTT.
            continue

        payload = " ".join(line.strip() for line in cue_lines).strip()
        speaker, cue_text = _extract_cue_speaker_and_text(payload)
        if not cue_text:
            continue

        segments.append(
            {
                "speaker": speaker,
                "start": start,
                "end": end,
                "text": cue_text,
            }
        )
        text_parts.append(cue_text)
        last_end = max(last_end, end)

    if not segments:
        raise TranscriptParseError(
            "transcript file produced no usable cues"
        )

    return {
        "text": " ".join(text_parts).strip(),
        "segments": segments,
        "language_code": None,
        "duration_sec": last_end if last_end > 0 else None,
    }
