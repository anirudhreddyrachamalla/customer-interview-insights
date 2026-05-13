"""Anthropic Claude pain-point extraction wrapper.

Calls Claude Sonnet 4.6 with a forced tool call (`record_pain_points`)
so the model is guaranteed to return JSON that matches our schema. The
system prompt is marked with ``cache_control: {"type": "ephemeral"}``
to enable prompt caching across calls.

Locked public contract (also mirrored by ``mock_extraction`` in
``tests/conftest.py``):

.. code-block:: python

    [
        {
            "text": str,                       # <= 500 chars
            "supporting_quote": str,           # non-empty
            "timestamp_start_sec": float,
            "timestamp_end_sec": float,
            "severity": int,                   # clamped to 1..5
            "type": str,                       # "pain_point" | "workaround" | "suggestion"
        },
        ...
    ]

The pipeline (``app.services.pipeline``) is responsible for verifying
each ``supporting_quote`` actually exists verbatim in the transcript;
this module only validates shape + structural constraints.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import anthropic

from app.config import get_settings
from app.schemas.interview import PainPointType

logger = logging.getLogger(__name__)


CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_TEXT_CHARS = 500
MIN_PAIN_POINTS = 3

# Allowed values for the v1.1 ``type`` field, kept in sync with the
# PG ENUM ``pain_point_type``.
PAIN_POINT_TYPE_VALUES: frozenset[str] = frozenset(m.value for m in PainPointType)


SYSTEM_PROMPT = (
    "You analyse customer interview transcripts for product research. "
    "Your job is to extract the pain points the customer (not the interviewer) "
    "mentioned during the interview.\n\n"
    "Rules you must follow:\n"
    "1. Only extract pain points spoken by the customer. Ignore questions or "
    "summaries from the interviewer.\n"
    "2. Every pain point must include a verbatim supporting_quote copied "
    "exactly from the transcript — no paraphrasing, no ellipses, no edits.\n"
    "3. Timestamps come from the transcript segment(s) that contain the "
    "supporting_quote, so the UI can highlight the matching segment.\n"
    "4. Each `text` field is a single-sentence summary (<= 500 characters).\n"
    "5. Severity is an integer 1 to 5 (1 = mild annoyance, 5 = severe / "
    "blocking the customer's work).\n"
    "6. Return 3 to 10 pain points. Always call the `record_pain_points` "
    "tool exactly once; never reply with plain text.\n"
    "7. For each pain point, set `type`:\n"
    "   - `workaround` if the customer described how they currently cope "
    "with the pain — a manual process, another tool they pay for, a hack, "
    "asking a colleague, copy-pasting between systems, etc. The "
    "supporting_quote should be the customer describing the workaround "
    "itself.\n"
    "   - `suggestion` if the customer explicitly suggested or asked for "
    "a feature or fix — \"I wish the app did X\", \"if only it could Y\", "
    "\"I'd pay for Z\", \"I need this to be able to...\", or said something "
    "would unblock them. The supporting_quote should be the customer's own "
    "words proposing the fix.\n"
    "   - `pain_point` otherwise. When the customer mentions the pain "
    "without describing how they cope and without asking for a fix, use "
    "`pain_point`. When in doubt, default to `pain_point`.\n"
    "8. Try to capture workarounds and suggestions when they're present in "
    "the transcript — they're the most valuable signal for product "
    "decisions. If the customer described two separate workarounds for the "
    "same pain, emit two pain points (each with its own quote and "
    "timestamps) rather than merging them."
)


TOOL_NAME = "record_pain_points"
TOOL_DEFINITION: dict[str, Any] = {
    "name": TOOL_NAME,
    "description": (
        "Record the pain points extracted from a customer interview transcript. "
        "Call this tool exactly once with the full list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pain_points": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_TEXT_CHARS,
                            "description": "One-sentence summary of the pain point.",
                        },
                        "supporting_quote": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "Verbatim quote from the customer, copied exactly "
                                "from the transcript."
                            ),
                        },
                        "timestamp_start_sec": {
                            "type": "number",
                            "minimum": 0,
                            "description": (
                                "Start time (seconds) of the transcript segment "
                                "containing the supporting_quote."
                            ),
                        },
                        "timestamp_end_sec": {
                            "type": "number",
                            "minimum": 0,
                            "description": (
                                "End time (seconds) of the transcript segment "
                                "containing the supporting_quote."
                            ),
                        },
                        "severity": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5,
                            "description": "Integer severity 1..5.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["pain_point", "workaround", "suggestion"],
                            "description": (
                                "Classification: 'pain_point' = problem only, no "
                                "workaround and no explicit ask; 'workaround' = "
                                "customer described how they currently cope "
                                "(manual process, another tool, a hack); "
                                "'suggestion' = customer explicitly asked for / "
                                "suggested / said they need a specific feature "
                                "or fix."
                            ),
                        },
                    },
                    "required": [
                        "text",
                        "supporting_quote",
                        "timestamp_start_sec",
                        "timestamp_end_sec",
                        "severity",
                        "type",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["pain_points"],
        "additionalProperties": False,
    },
}


def _format_timestamp(seconds: float) -> str:
    """Render a float number of seconds as ``MM:SS`` for the prompt header."""
    seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(seconds, 60)
    return f"{minutes:02d}:{sec:02d}"


def _render_transcript(transcript: dict[str, Any]) -> str:
    """Render the transcript as ``Speaker A [00:12-00:18]: text...`` lines."""
    segments = transcript.get("segments") or []
    if not segments:
        # No diarization fell through; just hand Claude the raw text.
        text = str(transcript.get("text") or "")
        return text

    lines: list[str] = []
    for seg in segments:
        speaker = str(seg.get("speaker", "?"))
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", 0.0))
        text = str(seg.get("text", "")).strip()
        lines.append(
            f"Speaker {speaker} [{_format_timestamp(start)}-{_format_timestamp(end)}]: {text}"
        )
    return "\n".join(lines)


def _validate_pain_point(pp: dict[str, Any]) -> dict[str, Any] | None:
    """Validate one pain-point dict; return the cleaned copy or None.

    On any structural problem we drop the item and log a warning so the
    pipeline can decide whether enough good ones remain.
    """
    try:
        text = str(pp["text"]).strip()
        supporting_quote = str(pp["supporting_quote"]).strip()
        timestamp_start_sec = float(pp["timestamp_start_sec"])
        timestamp_end_sec = float(pp["timestamp_end_sec"])
        severity_raw = int(pp["severity"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("dropping malformed pain point %r: %s", pp, exc)
        return None

    if not text or not supporting_quote:
        logger.warning("dropping pain point with empty text/quote: %r", pp)
        return None

    if len(text) > MAX_TEXT_CHARS:
        logger.warning(
            "dropping pain point with text > %d chars: %r", MAX_TEXT_CHARS, text[:80]
        )
        return None

    # v1.1: ``type`` is required and must be one of the enum values.
    # Missing / wrong-typed / unknown -> drop with a warning, matching
    # the pattern used for the other fields.
    type_raw = pp.get("type")
    if not isinstance(type_raw, str):
        logger.warning(
            "dropping pain point with missing/non-string type: %r", pp
        )
        return None
    type_value = type_raw.strip()
    if type_value not in PAIN_POINT_TYPE_VALUES:
        logger.warning(
            "dropping pain point with unknown type %r (expected one of %s)",
            type_value,
            sorted(PAIN_POINT_TYPE_VALUES),
        )
        return None

    # Clamp severity defensively even though the schema bounds it 1..5.
    severity = max(1, min(5, severity_raw))

    return {
        "text": text,
        "supporting_quote": supporting_quote,
        "timestamp_start_sec": timestamp_start_sec,
        "timestamp_end_sec": timestamp_end_sec,
        "severity": severity,
        "type": type_value,
    }


def _extract_tool_input(message: Any) -> dict[str, Any]:
    """Find the ``record_pain_points`` tool_use block in a Claude response.

    Raises:
        RuntimeError: if the model didn't call the tool or called the
            wrong one.
    """
    content = getattr(message, "content", None) or []
    for block in content:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type != "tool_use":
            continue
        block_name = getattr(block, "name", None) or (
            block.get("name") if isinstance(block, dict) else None
        )
        if block_name != TOOL_NAME:
            continue
        block_input = getattr(block, "input", None)
        if block_input is None and isinstance(block, dict):
            block_input = block.get("input")
        if not isinstance(block_input, dict):
            raise RuntimeError(
                f"tool_use block input was not a dict: {type(block_input).__name__}"
            )
        return block_input

    raise RuntimeError(
        f"Claude response did not include a {TOOL_NAME!r} tool_use block"
    )


async def extract_pain_points(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract pain points from a transcript dict via Claude.

    See module docstring for the shape of the returned list.

    Raises:
        RuntimeError: if the API key is unset, the model fails to call
            the tool, or fewer than :data:`MIN_PAIN_POINTS` validated
            pain points come back.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    rendered = _render_transcript(transcript)
    user_text = (
        "Extract the pain points from the customer interview transcript below.\n\n"
        "Transcript (speaker-labeled, timestamps in MM:SS):\n"
        f"{rendered}"
    )

    # The Anthropic SDK uses very specific TypedDict overloads for each
    # parameter; cast through ``Any`` so mypy doesn't insist on importing
    # a dozen ``…Param`` types just to spell the request.
    system_blocks: Any = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    tools_arg: Any = [TOOL_DEFINITION]
    tool_choice_arg: Any = {"type": "tool", "name": TOOL_NAME}
    messages_arg: Any = [
        {"role": "user", "content": [{"type": "text", "text": user_text}]}
    ]

    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=cast(Any, system_blocks),
        tools=cast(Any, tools_arg),
        tool_choice=cast(Any, tool_choice_arg),
        messages=cast(Any, messages_arg),
    )

    tool_input = _extract_tool_input(message)
    raw_pain_points = tool_input.get("pain_points")
    if not isinstance(raw_pain_points, list):
        raise RuntimeError(
            "tool_use input did not include a 'pain_points' list "
            f"(got {type(raw_pain_points).__name__})"
        )

    validated: list[dict[str, Any]] = []
    for pp in raw_pain_points:
        if not isinstance(pp, dict):
            logger.warning("dropping non-dict pain point entry: %r", pp)
            continue
        cleaned = _validate_pain_point(pp)
        if cleaned is not None:
            validated.append(cleaned)

    if len(validated) < MIN_PAIN_POINTS:
        raise RuntimeError(
            f"extraction returned fewer than {MIN_PAIN_POINTS} valid pain points "
            f"(got {len(validated)})"
        )

    return validated
