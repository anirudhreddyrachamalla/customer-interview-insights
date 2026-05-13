# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Tests for the v1.1 pain-point ``type`` classification in extraction."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services import extraction as extraction_mod


# ---------------------------------------------------------------------------
# _validate_pain_point — the new ``type`` field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_value",
    ["pain_point", "workaround", "suggestion"],
)
def test_validate_pain_point_accepts_each_type(type_value):
    pp = extraction_mod._validate_pain_point(
        {
            "text": "x",
            "supporting_quote": "y",
            "timestamp_start_sec": 0,
            "timestamp_end_sec": 1,
            "severity": 3,
            "type": type_value,
        }
    )
    assert pp is not None
    assert pp["type"] == type_value


def test_validate_pain_point_drops_missing_type(caplog):
    with caplog.at_level("WARNING", logger="app.services.extraction"):
        pp = extraction_mod._validate_pain_point(
            {
                "text": "x",
                "supporting_quote": "y",
                "timestamp_start_sec": 0,
                "timestamp_end_sec": 1,
                "severity": 3,
            }
        )
    assert pp is None
    assert any("missing/non-string type" in r.message for r in caplog.records)


def test_validate_pain_point_drops_unknown_type(caplog):
    with caplog.at_level("WARNING", logger="app.services.extraction"):
        pp = extraction_mod._validate_pain_point(
            {
                "text": "x",
                "supporting_quote": "y",
                "timestamp_start_sec": 0,
                "timestamp_end_sec": 1,
                "severity": 3,
                "type": "must_have",  # not in enum
            }
        )
    assert pp is None
    assert any("unknown type" in r.message for r in caplog.records)


def test_validate_pain_point_drops_non_string_type():
    pp = extraction_mod._validate_pain_point(
        {
            "text": "x",
            "supporting_quote": "y",
            "timestamp_start_sec": 0,
            "timestamp_end_sec": 1,
            "severity": 3,
            "type": 42,
        }
    )
    assert pp is None


# ---------------------------------------------------------------------------
# Tool schema — every type is listed and the field is required
# ---------------------------------------------------------------------------


def test_tool_schema_includes_type_enum():
    schema = extraction_mod.TOOL_DEFINITION["input_schema"]
    item_schema = schema["properties"]["pain_points"]["items"]
    assert "type" in item_schema["properties"]
    assert item_schema["properties"]["type"]["enum"] == [
        "pain_point",
        "workaround",
        "suggestion",
    ]
    assert "type" in item_schema["required"]


def test_system_prompt_includes_rules_7_and_8():
    prompt = extraction_mod.SYSTEM_PROMPT
    assert "workaround" in prompt
    assert "suggestion" in prompt
    # The rule numbers are part of the spec — make sure they're present.
    assert "7." in prompt
    assert "8." in prompt


# ---------------------------------------------------------------------------
# Full extract_pain_points path — pain_points dicts now include ``type``
# ---------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, response: Any, captured_kwargs: dict[str, Any]):
        self._response = response
        self._captured = captured_kwargs

    async def create(self, **kwargs: Any) -> Any:
        self._captured.update(kwargs)
        return self._response


class _FakeAsyncAnthropic:
    last_kwargs: dict[str, Any] = {}
    next_response: Any = None

    def __init__(self, *, api_key: str | None = None, **kwargs: Any):
        type(self).last_kwargs = {}
        self.messages = _FakeMessages(
            response=type(self).next_response, captured_kwargs=type(self).last_kwargs
        )


def _tool_use_response(pain_points: list[dict[str, Any]]) -> Any:
    block = SimpleNamespace(
        type="tool_use",
        name="record_pain_points",
        input={"pain_points": pain_points},
    )
    return SimpleNamespace(content=[block])


@pytest.fixture
def patch_anthropic_key(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    yield
    get_settings.cache_clear()


async def test_extract_keeps_type_when_present(
    monkeypatch, patch_anthropic_key, sample_transcript
):
    pain_points = [
        {
            "text": "A",
            "supporting_quote": "q1",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 3,
            "type": "workaround",
        },
        {
            "text": "B",
            "supporting_quote": "q2",
            "timestamp_start_sec": 1.0,
            "timestamp_end_sec": 2.0,
            "severity": 4,
            "type": "suggestion",
        },
        {
            "text": "C",
            "supporting_quote": "q3",
            "timestamp_start_sec": 2.0,
            "timestamp_end_sec": 3.0,
            "severity": 2,
            "type": "pain_point",
        },
    ]
    _FakeAsyncAnthropic.next_response = _tool_use_response(pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    out = await extraction_mod.extract_pain_points(sample_transcript)
    types = [pp["type"] for pp in out]
    assert types == ["workaround", "suggestion", "pain_point"]


async def test_extract_drops_entries_missing_type(
    monkeypatch, patch_anthropic_key, sample_transcript
):
    pain_points = [
        # Two valid + one missing type — should leave 2 < MIN_PAIN_POINTS.
        {
            "text": "A",
            "supporting_quote": "q1",
            "timestamp_start_sec": 0.0,
            "timestamp_end_sec": 1.0,
            "severity": 3,
            "type": "pain_point",
        },
        {
            "text": "B",
            "supporting_quote": "q2",
            "timestamp_start_sec": 1.0,
            "timestamp_end_sec": 2.0,
            "severity": 4,
            # no type
        },
        {
            "text": "C",
            "supporting_quote": "q3",
            "timestamp_start_sec": 2.0,
            "timestamp_end_sec": 3.0,
            "severity": 2,
            "type": "pain_point",
        },
    ]
    _FakeAsyncAnthropic.next_response = _tool_use_response(pain_points)
    monkeypatch.setattr(
        extraction_mod.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic
    )

    with pytest.raises(RuntimeError, match="fewer than 3 valid pain points"):
        await extraction_mod.extract_pain_points(sample_transcript)
