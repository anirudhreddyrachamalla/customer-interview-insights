# ruff: noqa: I001 - phantom isort violation; layout matches conftest.py.
"""Unit tests for ``app.services.transcript_parser`` (v1.2).

v1.2 dropped ``.txt`` and ``.srt`` parsing (shipped in v1.1) so the
only happy path here is ``.vtt``. The non-VTT cases now assert that
:func:`parse` raises :class:`TranscriptParseError`.

This module also covers the new :func:`render_formatted` surface — the
preprocessed display string that the detail page renders verbatim.
"""

from __future__ import annotations

import pytest

from app.services.transcript_parser import (
    TranscriptParseError,
    parse,
    render_formatted,
)


# ---------------------------------------------------------------------------
# parse(): .vtt happy path
# ---------------------------------------------------------------------------


def test_parse_vtt_with_voice_tags(tmp_path):
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:03.500\n"
        "<v Speaker A>Welcome, thanks for joining.\n"
        "\n"
        "00:00:03.600 --> 00:00:07.200\n"
        "<v Speaker B>Happy to be here, I've been using the product for six months.\n"
    )

    out = parse(p)
    assert len(out["segments"]) == 2
    assert out["segments"][0]["speaker"] == "A"
    assert out["segments"][0]["start"] == 0.0
    assert out["segments"][0]["end"] == 3.5
    assert out["segments"][1]["speaker"] == "B"
    assert out["segments"][1]["start"] == 3.6
    assert out["segments"][1]["end"] == 7.2
    assert out["duration_sec"] == 7.2
    assert "Welcome" in out["text"]
    assert "six months" in out["text"]


def test_parse_vtt_with_speaker_prefix_inside_cue(tmp_path):
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Speaker A: First cue.\n"
        "\n"
        "00:00:02.500 --> 00:00:05.000\n"
        "Speaker B: Second cue.\n"
    )

    out = parse(p)
    assert [seg["speaker"] for seg in out["segments"]] == ["A", "B"]
    assert out["segments"][0]["text"] == "First cue."


def test_parse_vtt_without_webvtt_header_raises(tmp_path):
    p = tmp_path / "t.vtt"
    p.write_text(
        "00:00:00.000 --> 00:00:02.000\n"
        "Speaker A: missing header.\n"
    )
    with pytest.raises(TranscriptParseError):
        parse(p)


def test_parse_vtt_malformed_timestamp_raises(tmp_path):
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "this is not a timestamp\n"
        "garbage cue body\n"
    )
    with pytest.raises(TranscriptParseError):
        parse(p)


# ---------------------------------------------------------------------------
# parse(): .txt / .srt removed in v1.2 — now reject as unsupported.
# ---------------------------------------------------------------------------


def test_parse_txt_now_raises_unsupported(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("Speaker A: hi.\nSpeaker B: hi back.\n")
    with pytest.raises(TranscriptParseError, match="unsupported transcript format"):
        parse(p)


def test_parse_srt_now_raises_unsupported(tmp_path):
    p = tmp_path / "t.srt"
    p.write_text(
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "Speaker A: Welcome.\n"
    )
    with pytest.raises(TranscriptParseError, match="unsupported transcript format"):
        parse(p)


def test_parse_unsupported_extension_raises(tmp_path):
    p = tmp_path / "t.docx"
    p.write_bytes(b"not a real docx")
    with pytest.raises(TranscriptParseError, match="unsupported transcript format"):
        parse(p)


def test_parse_invalid_utf8_raises(tmp_path):
    p = tmp_path / "t.vtt"
    p.write_bytes(b"WEBVTT\n\n\xff\xfe\xfd not valid utf-8\n")
    with pytest.raises(TranscriptParseError, match="UTF-8"):
        parse(p)


# ---------------------------------------------------------------------------
# render_formatted()
# ---------------------------------------------------------------------------


def test_render_formatted_voice_tag_speaker(tmp_path):
    """Speaker is taken from the ``<v Speaker A>`` voice tag."""
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:03.500\n"
        "<v Speaker A>Welcome, thanks for joining.\n"
        "\n"
        "00:00:03.600 --> 00:00:07.200\n"
        "<v Speaker B>Happy to be here.\n"
    )

    rendered = render_formatted(p)
    assert rendered == (
        "[00:00 - 00:04] Speaker A\n"
        "Welcome, thanks for joining.\n"
        "\n"
        "[00:04 - 00:07] Speaker B\n"
        "Happy to be here."
    )


def test_render_formatted_prefix_speaker(tmp_path):
    """Speaker falls back to the ``Speaker X:`` prefix when no voice tag."""
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Speaker A: First cue text.\n"
        "\n"
        "00:00:02.500 --> 00:00:05.000\n"
        "Speaker B: Second cue text.\n"
    )

    rendered = render_formatted(p)
    blocks = rendered.split("\n\n")
    assert blocks[0].splitlines()[0] == "[00:00 - 00:02] Speaker A"
    assert blocks[0].splitlines()[1] == "First cue text."
    # Python's round() uses banker's rounding, so 2.5 -> 2.
    assert blocks[1].splitlines()[0] == "[00:02 - 00:05] Speaker B"
    assert blocks[1].splitlines()[1] == "Second cue text."


def test_render_formatted_default_speaker(tmp_path):
    """No tag and no prefix -> default to Speaker A."""
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "Just a plain cue with no speaker attribution.\n"
    )

    rendered = render_formatted(p)
    assert rendered == (
        "[00:00 - 00:02] Speaker A\n"
        "Just a plain cue with no speaker attribution."
    )


def test_render_formatted_blank_line_separator_between_cues(tmp_path):
    """Cue blocks are separated by a single blank line (and only one)."""
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "<v Speaker A>First.\n"
        "\n"
        "00:00:02.500 --> 00:00:05.000\n"
        "<v Speaker B>Second.\n"
        "\n"
        "00:00:06.000 --> 00:00:08.000\n"
        "<v Speaker A>Third.\n"
    )

    rendered = render_formatted(p)
    blocks = rendered.split("\n\n")
    # Three cue blocks, each two lines.
    assert len(blocks) == 3
    for block in blocks:
        assert len(block.splitlines()) == 2
    # And there's no leading/trailing blank line in the output.
    assert not rendered.startswith("\n")
    assert not rendered.endswith("\n")


def test_render_formatted_no_webvtt_header_or_cue_indices(tmp_path):
    """Numeric cue indices and the WEBVTT header are stripped."""
    p = tmp_path / "t.vtt"
    p.write_text(
        "WEBVTT\n"
        "\n"
        "1\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "<v Speaker A>Hello.\n"
        "\n"
        "2\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "<v Speaker B>Hi back.\n"
    )

    rendered = render_formatted(p)
    assert "WEBVTT" not in rendered
    # The lone numeric cue ids never appear in the rendered output.
    assert "\n1\n" not in rendered
    assert "\n2\n" not in rendered
    assert "[00:00 - 00:02] Speaker A" in rendered
    assert "[00:03 - 00:05] Speaker B" in rendered


def test_render_formatted_non_vtt_extension_raises(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("Speaker A: hi.\n")
    with pytest.raises(TranscriptParseError, match="unsupported transcript format"):
        render_formatted(p)
