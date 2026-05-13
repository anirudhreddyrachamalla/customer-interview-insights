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

  describe("v1.2 single-type column props", () => {
    it("filters painPoints to the given type", () => {
      // samplePainPoints[0] is workaround, [2] is suggestion, [1] and
      // [3] are pain_point.
      render(
        <PainPointsPanel
          painPoints={painPoints}
          status="completed"
          type="workaround"
        />,
      );
      // Only the workaround card should be in the DOM.
      expect(
        screen.getByTestId(`pain-point-${painPoints[0].id}`),
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId(`pain-point-${painPoints[1].id}`),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId(`pain-point-${painPoints[2].id}`),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId(`pain-point-${painPoints[3].id}`),
      ).not.toBeInTheDocument();
    });

    it("hides the per-card type badge when hideTypeBadge is set", () => {
      render(
        <PainPointsPanel
          painPoints={painPoints}
          status="completed"
          hideTypeBadge
        />,
      );
      // Even the workaround/suggestion cards should not render a badge.
      expect(
        screen.queryByTestId("pain-point-type-badge"),
      ).not.toBeInTheDocument();
    });

    it("renders `· N` in the header when count is supplied", () => {
      render(
        <PainPointsPanel
          painPoints={painPoints}
          status="completed"
          title="Workarounds"
          count={3}
        />,
      );
      const chip = screen.getByTestId("pain-points-count");
      expect(chip).toBeInTheDocument();
      expect(chip.textContent).toMatch(/·\s*3/);
    });

    it("respects the custom title prop in the header", () => {
      render(
        <PainPointsPanel
          painPoints={painPoints}
          status="completed"
          title="Suggestions"
        />,
      );
      expect(screen.getByText("Suggestions")).toBeInTheDocument();
    });
  });

  describe("v1.1 classification badge", () => {
    it("renders a Workaround badge for type='workaround'", () => {
      // Fixture pain point [0] is tagged `workaround`.
      render(<PainPointsPanel painPoints={painPoints} status="completed" />);
      const card = screen.getByTestId(`pain-point-${painPoints[0].id}`);
      const badge = within(card).getByText("Workaround");
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute("data-pain-point-type", "workaround");
    });

    it("renders a Suggestion badge for type='suggestion'", () => {
      // Fixture pain point [2] is tagged `suggestion`.
      render(<PainPointsPanel painPoints={painPoints} status="completed" />);
      const card = screen.getByTestId(`pain-point-${painPoints[2].id}`);
      const badge = within(card).getByText("Suggestion");
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute("data-pain-point-type", "suggestion");
    });

    it("does NOT render a classification badge for type='pain_point'", () => {
      // Fixture pain points [1] and [3] are tagged `pain_point` — the
      // default, no badge.
      render(<PainPointsPanel painPoints={painPoints} status="completed" />);
      const plainCard = screen.getByTestId(`pain-point-${painPoints[1].id}`);
      expect(
        within(plainCard).queryByText("Pain point"),
      ).not.toBeInTheDocument();
      expect(
        within(plainCard).queryByText("Workaround"),
      ).not.toBeInTheDocument();
      expect(
        within(plainCard).queryByText("Suggestion"),
      ).not.toBeInTheDocument();
    });
  });
});
