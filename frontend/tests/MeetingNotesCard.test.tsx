/**
 * Component tests for `MeetingNotesCard`.
 *
 * Covers the two rendering branches that the interview detail page
 * depends on:
 *
 *  1. When a non-empty `meetingNotes` string is provided, the text is
 *     rendered with `whitespace-pre-wrap` so newlines authored in the
 *     upload textarea are preserved on the detail surface.
 *  2. When `meetingNotes` is `null`, the card falls back to the muted
 *     "No notes added" empty-state copy so the column never looks broken.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MeetingNotesCard } from "@/components/interviews/MeetingNotesCard";

describe("MeetingNotesCard", () => {
  it("renders the provided string with line breaks preserved", () => {
    const notes =
      "Line one of notes.\nLine two of notes — recruited via Slack.";

    render(<MeetingNotesCard meetingNotes={notes} />);

    // The exact string (including the literal newline) must appear in
    // the rendered text — `whitespace-pre-wrap` doesn't replace `\n`,
    // it just preserves it visually.
    const node = screen.getByText((_, el) => {
      if (!el) return false;
      return el.tagName === "P" && el.textContent === notes;
    });
    expect(node).toBeInTheDocument();
    expect(node.className).toMatch(/whitespace-pre-wrap/);

    // The empty-state copy must NOT appear when notes are present.
    expect(screen.queryByText(/no notes added/i)).not.toBeInTheDocument();
  });

  it("renders the empty state when meetingNotes is null", () => {
    render(<MeetingNotesCard meetingNotes={null} />);

    const empty = screen.getByText(/no notes added/i);
    expect(empty).toBeInTheDocument();
    expect(empty.className).toMatch(/text-muted-foreground/);
  });
});
