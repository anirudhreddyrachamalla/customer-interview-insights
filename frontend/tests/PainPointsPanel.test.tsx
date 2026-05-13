/**
 * Component tests for `PainPointsPanel`.
 *
 * Covers the three behaviours the interview-detail wiring relies on:
 *
 *  1. Pain points render sorted by `severity DESC, created_at ASC`,
 *     regardless of the order the API hands them back in. The backend
 *     should already sort, but the panel re-sorts defensively.
 *  2. Empty-state copy switches based on interview status —
 *     `completed` shows "No pain points were extracted", while
 *     in-flight statuses render skeleton placeholders.
 *  3. Clicking a card calls `onClickPainPoint` with that exact pain
 *     point (so the parent can drive the transcript pane's scroll).
 *
 * Kept deliberately minimal — the tester teammate's task #6 will layer
 * in keyboard-activation + accessibility checks on top.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PainPointsPanel } from "@/components/interviews/PainPointsPanel";
import { samplePainPoints } from "@/tests/fixtures/sampleInterview";
import type { PainPoint } from "@/lib/api/types";

const painPoints = samplePainPoints as unknown as PainPoint[];

describe("PainPointsPanel", () => {
  it("renders pain points sorted by severity DESC, created_at ASC", () => {
    // Shuffle the fixture so we know the sort comes from the panel, not
    // from the input order.
    const shuffled = [painPoints[2], painPoints[0], painPoints[3], painPoints[1]];

    // Pass a click handler so each card renders as role="button" (the
    // component only attaches that role when interactive — see
    // PainPointsPanel.tsx).
    render(
      <PainPointsPanel
        painPoints={shuffled}
        status="completed"
        onClickPainPoint={() => {}}
      />,
    );

    const items = screen.getAllByRole("button");
    // Expected order from samplePainPoints:
    //   severity 5 → id …202
    //   severity 4 → id …201 (created 10:01:00, earlier)
    //   severity 4 → id …204 (created 10:01:03)
    //   severity 3 → id …203
    expect(items[0]).toHaveAttribute(
      "data-testid",
      `pain-point-${painPoints[1].id}`,
    );
    expect(items[1]).toHaveAttribute(
      "data-testid",
      `pain-point-${painPoints[0].id}`,
    );
    expect(items[2]).toHaveAttribute(
      "data-testid",
      `pain-point-${painPoints[3].id}`,
    );
    expect(items[3]).toHaveAttribute(
      "data-testid",
      `pain-point-${painPoints[2].id}`,
    );
  });

  it("shows the empty-state message when completed with no pain points", () => {
    render(<PainPointsPanel painPoints={[]} status="completed" />);
    expect(
      screen.getByText(/no pain points were extracted/i),
    ).toBeInTheDocument();
  });

  it("renders skeleton placeholders while the pipeline is still running", () => {
    const { container } = render(
      <PainPointsPanel painPoints={[]} status="analyzing" />,
    );
    expect(
      screen.queryByText(/no pain points were extracted/i),
    ).not.toBeInTheDocument();
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0);
  });

  it("invokes onClickPainPoint with the right pain point on click", async () => {
    const onClickPainPoint = vi.fn();
    const user = userEvent.setup();

    render(
      <PainPointsPanel
        painPoints={painPoints}
        status="completed"
        onClickPainPoint={onClickPainPoint}
      />,
    );

    const targetCard = screen.getByTestId(`pain-point-${painPoints[2].id}`);
    await user.click(within(targetCard).getByText(painPoints[2].text));

    expect(onClickPainPoint).toHaveBeenCalledTimes(1);
    expect(onClickPainPoint).toHaveBeenCalledWith(painPoints[2]);
  });
});
