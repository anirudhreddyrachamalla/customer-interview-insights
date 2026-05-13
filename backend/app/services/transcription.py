"""AssemblyAI transcription wrapper.

Wraps the official ``assemblyai`` Python SDK to submit an audio file
for transcription with speaker diarization and language detection, and
returns the canonical dict shape the pipeline + tests expect.

Locked public contract (also mirrored by ``mock_transcription`` in
``tests/conftest.py``):

.. code-block:: python

    {
        "text": str,
        "segments": [
            {"speaker": "A"|"B"|..., "start": float, "end": float, "text": str},
            ...
        ],
        "language_code": str | None,
        "duration_sec": float | None,
    }

Notes:

* The AssemblyAI SDK is synchronous. We wrap the blocking ``transcribe``
  call with :func:`asyncio.to_thread` so this ``async def`` doesn't
  starve the event loop.
* The API key is read from :class:`app.config.Settings` lazily (inside
  the function, not at import time) so tests that monkeypatch / clear
  the cached settings keep working.
* ``Utterance.start`` and ``.end`` are in *milliseconds*; we convert to
  seconds before returning. ``Transcript.audio_duration`` is in seconds
  per the SDK type comment.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import assemblyai as aai

from app.config import get_settings

logger = logging.getLogger(__name__)


def _segments_from_transcript(transcript: aai.Transcript) -> list[dict[str, Any]]:
    """Build the canonical segment list from a finished AssemblyAI transcript.

    When ``speaker_labels=True``, ``transcript.utterances`` is the
    turn-by-turn diarized list. If it's missing or empty (e.g. the
    audio had no detectable speech-changes or the SDK didn't return
    utterances for some reason), we fall back to a single
    ``Speaker A`` segment spanning the entire audio.
    """
    utterances = transcript.utterances or []
    segments: list[dict[str, Any]] = []
    for u in utterances:
        # Defensively coerce — Utterance.speaker/start/end are typed as
        # optional in the SDK, but in practice present on a completed
        # diarized transcript.
        speaker = u.speaker if u.speaker is not None else "A"
        start_ms = u.start if u.start is not None else 0
        end_ms = u.end if u.end is not None else start_ms
        text = u.text if u.text is not None else ""
        segments.append(
            {
                "speaker": str(speaker),
                "start": float(start_ms) / 1000.0,
                "end": float(end_ms) / 1000.0,
                "text": str(text),
            }
        )

    if not segments:
        full_text = transcript.text or ""
        duration_sec = float(transcript.audio_duration or 0)
        segments.append(
            {
                "speaker": "A",
                "start": 0.0,
                "end": duration_sec,
                "text": full_text,
            }
        )

    return segments


async def transcribe(audio_path: Path) -> dict[str, Any]:
    """Transcribe an audio file via AssemblyAI with speaker diarization.

    Args:
        audio_path: Absolute path to the audio file on disk.

    Returns:
        See module docstring.

    Raises:
        RuntimeError: if the API key is unset, or AssemblyAI reports an
            ``error`` status (the message is the SDK's ``error`` string).
    """
    settings = get_settings()
    if not settings.assemblyai_api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set")

    # Configure the SDK lazily so test monkeypatches / cache_clear() take effect.
    aai.settings.api_key = settings.assemblyai_api_key

    config = aai.TranscriptionConfig(
        speaker_labels=True,
        language_detection=True,
        speech_model=aai.SpeechModel.universal,
    )

    def _run_blocking() -> aai.Transcript:
        transcriber = aai.Transcriber(config=config)
        return transcriber.transcribe(str(audio_path))

    transcript = await asyncio.to_thread(_run_blocking)

    if transcript.status == aai.TranscriptStatus.error:
        err = transcript.error or "AssemblyAI returned an error with no message"
        raise RuntimeError(err)

    segments = _segments_from_transcript(transcript)

    duration_sec: float | None = None
    if transcript.audio_duration is not None:
        duration_sec = float(transcript.audio_duration)

    language_code: str | None = None
    if transcript.language_code is not None:
        # LanguageCode is a ``str, Enum`` so str() yields the iso code.
        language_code = str(transcript.language_code)

    return {
        "text": transcript.text or "",
        "segments": segments,
        "language_code": language_code,
        "duration_sec": duration_sec,
    }
