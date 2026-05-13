"""Background processing pipeline: transcribe -> extract -> persist.

This module owns the state-machine choreography. The actual
AssemblyAI + Anthropic SDK calls live in
:mod:`app.services.transcription` and :mod:`app.services.extraction`
respectively, both of which are imported as module attributes here so
the tester's ``monkeypatch.setattr`` calls can replace them.

Task #10 lands the choreography. Task #9 fills in the real
transcription + extraction implementations (this module won't need to
change for that).
"""

from __future__ import annotations

import contextlib
import logging
import re
import uuid
from pathlib import Path

from app.db import async_session_maker
from app.models.interview import Interview
from app.schemas.interview import InterviewStatus
from app.services import extraction as extraction_mod
from app.services import interviews as interviews_service
from app.services import transcription as transcription_mod

logger = logging.getLogger(__name__)


_WHITESPACE_RE = re.compile(r"\s+")


def _collapse(s: str) -> str:
    """Lowercase + collapse whitespace runs so quote matching is robust.

    Real Claude output may differ from the transcript in newline /
    spacing nuances; we normalize both sides before comparing.
    """
    return _WHITESPACE_RE.sub(" ", s).strip().lower()


def _quote_is_in_transcript(quote: str, transcript_text: str) -> bool:
    """Verbatim-with-whitespace-tolerance substring check."""
    return _collapse(quote) in _collapse(transcript_text)


async def run_pipeline(interview_id: uuid.UUID) -> None:
    """End-to-end pipeline run for one interview.

    Opens its own DB session (the FastAPI request-scoped session is
    gone by the time BackgroundTasks executes us). On any exception we
    mark the interview ``failed`` with ``str(exc)`` and re-raise into
    the BackgroundTasks executor's log.
    """
    async with async_session_maker() as db:
        interview = await interviews_service.get_interview(db, interview_id)
        if interview is None:
            logger.error("run_pipeline: interview %s missing", interview_id)
            return

        try:
            # uploaded -> transcribing (or, on retry, failed -> transcribing
            # was already done by the retry endpoint; in that case the
            # transition below is a no-op safeguarded by the state machine)
            if interview.status is InterviewStatus.uploaded:
                await interviews_service.transition_status(
                    db, interview, InterviewStatus.transcribing
                )

            audio_path = Path(interview.audio_path)
            transcript = await transcription_mod.transcribe(audio_path)

            interview.transcript_text = str(transcript.get("text") or "")
            interview.transcript_segments = transcript.get("segments")
            await db.commit()
            await db.refresh(interview)

            await interviews_service.transition_status(db, interview, InterviewStatus.analyzing)

            pain_points = await extraction_mod.extract_pain_points(transcript)

            await _validate_and_persist_pain_points(db, interview, pain_points)

            await interviews_service.mark_completed(db, interview)

        except Exception as exc:  # noqa: BLE001
            logger.exception("pipeline failed for interview %s", interview_id)
            # Re-load a fresh row in case the failure happened mid-commit
            # and the session is in an unusual state.
            with contextlib.suppress(Exception):  # pragma: no cover
                await db.rollback()
            fresh = await interviews_service.get_interview(db, interview_id)
            if fresh is not None and fresh.status is not InterviewStatus.completed:
                # Already in failed (or another terminal-ish state) is
                # fine — swallow the transition error and move on.
                with contextlib.suppress(interviews_service.InvalidStatusTransitionError):
                    await interviews_service.mark_failed(db, fresh, str(exc))


_MIN_VERIFIABLE_PAIN_POINTS = 3


async def _validate_and_persist_pain_points(
    db,  # AsyncSession
    interview: Interview,
    pain_points: list[dict[str, object]],
) -> None:
    """Filter pain points whose ``supporting_quote`` exists verbatim in the
    transcript, then persist them.

    Pain points whose quote isn't found are dropped (the extraction
    service can hallucinate). If fewer than
    :data:`_MIN_VERIFIABLE_PAIN_POINTS` survive the filter, raise so the
    pipeline marks the interview ``failed`` with a descriptive message.
    """
    transcript_text = interview.transcript_text or ""
    verified: list[dict[str, object]] = []
    for pp in pain_points:
        quote = str(pp.get("supporting_quote", ""))
        if _quote_is_in_transcript(quote, transcript_text):
            verified.append(pp)
        else:
            logger.warning(
                "dropping pain point: supporting_quote not in transcript verbatim: %r",
                quote[:80],
            )

    if len(verified) < _MIN_VERIFIABLE_PAIN_POINTS:
        raise ValueError(
            "extraction returned fewer than 3 pain points whose quotes are "
            "verifiable in the transcript"
        )

    await interviews_service.persist_pain_points(db, interview, verified)
