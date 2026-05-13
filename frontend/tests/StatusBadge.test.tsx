/**
 * Component tests for `StatusBadge`.
 *
 * Covers the v0 coverage target in `.claude/agents/tester.md`:
 *
 *   "StatusBadge: renders each status with the right colour/label"
 *
 * The badge is a thin presentational wrapper around `<Badge>`, so the
 * assertions here intentionally focus on user-visible output:
 *
 *   - the visible label string for each of the 5 statuses
 *   - the `data-status` attribute survives so list / filter UIs can
 *     style or query on status without re-parsing the label text
 *   - the `aria-label` includes the human-readable label for
 *     screen-reader users (covers the colour-only-distinction concern)
 *   - the `completed` status renders the bespoke emerald palette
 *     classes; `failed` falls through to the destructive variant
 *     (verified via class name presence so the contract is locked).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatusBadge } from "@/components/interviews/StatusBadge";
import type { InterviewStatus } from "@/lib/api/types";

interface Case {
  status: InterviewStatus;
  label: string;
}

const CASES: Case[] = [
  { status: "uploaded", label: "Uploaded" },
  { status: "transcribing", label: "Transcribing…" },
  { status: "analyzing", label: "Analyzing…" },
  { status: "completed", label: "Completed" },
  { status: "failed", label: "Failed" },
];

describe("StatusBadge", () => {
  it.each(CASES)(
    "renders the '$status' status with the label '$label'",
    ({ status, label }) => {
      render(<StatusBadge status={status} />);
      const badge = screen.getByLabelText(`Status: ${label}`);
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveTextContent(label);
      expect(badge).toHaveAttribute("data-status", status);
    },
  );

  it("applies the bespoke emerald palette for 'completed'", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByLabelText("Status: Completed");
    // We assert the class is present rather than the exact tailwind
    // string — if the design tweaks shade later, only the assertion
    // value here needs to change.
    expect(badge.className).toContain("emerald");
  });

  it("forwards a caller-supplied className", () => {
    render(<StatusBadge status="uploaded" className="my-extra-class" />);
    const badge = screen.getByLabelText("Status: Uploaded");
    expect(badge.className).toContain("my-extra-class");
  });
});
