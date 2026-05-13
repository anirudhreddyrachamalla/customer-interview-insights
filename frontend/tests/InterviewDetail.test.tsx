/**
 * Component tests for the v1.2 `InterviewDetail` layout.
 *
 * Coverage targets (per SPEC_v1.2 §Tests-frontend):
 *
 *  - Three pain-point columns render with the correct counts in their
 *    headers.
 *  - Clicking a Workarounds card triggers the transcript highlight
 *    handler (verified through the segment-highlight side-effect on the
 *    audio path, since the audio fixture is the default).
 *  - Per-column empty state appears when there are no pain points of
 *    that type.
 *  - Demographics + meeting notes appear in the left rail.
 *  - Transcript is the rightmost column.
 *
 * The detail page is wired into MSW + React Query so we exercise the
 * real fetching path, not a hand-mocked hook.
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { InterviewDetail } from "@/components/interviews/InterviewDetail";
import { server } from "@/tests/msw/server";
import {
  sampleInterview,
  samplePainPoints,
} from "@/tests/fixtures/sampleInterview";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), message: vi.fn() },
  Toaster: () => null,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

beforeEach(() => {
  // jsdom doesn't ship scrollIntoView; stub it for any node that calls
  // it during the tests (`scrollToIndex` and `scrollToQuote` both do).
  Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
});

function renderDetail(interviewId: string) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <InterviewDetail interviewId={interviewId} />
    </QueryClientProvider>,
  );
}

describe("InterviewDetail (v1.2 5-region layout)", () => {
  it("renders 3 pain-point columns with the correct counts in their headers", async () => {
    renderDetail(sampleInterview.id);

    // Wait for the data to settle — the audio filename is in the header.
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    const painCol = await screen.findByTestId(
      "interview-detail-pain-point-column",
    );
    const workaroundCol = screen.getByTestId(
      "interview-detail-workaround-column",
    );
    const suggestionCol = screen.getByTestId(
      "interview-detail-suggestion-column",
    );

    // Header labels.
    expect(within(painCol).getByText("Pain points")).toBeInTheDocument();
    expect(within(workaroundCol).getByText("Workarounds")).toBeInTheDocument();
    expect(within(suggestionCol).getByText("Suggestions")).toBeInTheDocument();

    // Count chips. Fixture has 2 pain_point, 1 workaround, 1 suggestion.
    expect(
      within(painCol).getByTestId("pain-points-count").textContent,
    ).toMatch(/·\s*2/);
    expect(
      within(workaroundCol).getByTestId("pain-points-count").textContent,
    ).toMatch(/·\s*1/);
    expect(
      within(suggestionCol).getByTestId("pain-points-count").textContent,
    ).toMatch(/·\s*1/);
  });

  it("shows the per-column empty state when there are no pain points of that type", async () => {
    // Override the interview detail handler to drop two of the types so
    // Workarounds + Suggestions are empty.
    const painPointsOnly = samplePainPoints.filter(
      (p) => p.type === "pain_point",
    );
    server.use(
      http.get("*/api/v1/interviews/:interviewId", ({ params }) =>
        HttpResponse.json({
          ...sampleInterview,
          id: params.interviewId,
          pain_points: painPointsOnly,
        }),
      ),
    );

    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    const workaroundCol = await screen.findByTestId(
      "interview-detail-workaround-column",
    );
    const suggestionCol = screen.getByTestId(
      "interview-detail-suggestion-column",
    );
    expect(
      within(workaroundCol).getByText(/no workarounds\./i),
    ).toBeInTheDocument();
    expect(
      within(suggestionCol).getByText(/no suggestions\./i),
    ).toBeInTheDocument();
  });

  it("renders demographics + meeting notes in the left rail", async () => {
    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    const rail = await screen.findByTestId("interview-detail-left-rail");
    // Demographics card title.
    expect(within(rail).getByText("Interviewee")).toBeInTheDocument();
    // Demographics field — the name we seeded.
    expect(
      within(rail).getByText(sampleInterview.demographics.name),
    ).toBeInTheDocument();
    // Meeting notes card title + the notes text.
    expect(within(rail).getByText("Meeting notes")).toBeInTheDocument();
    expect(
      within(rail).getByText(
        (sampleInterview.meeting_notes ?? "").slice(0, 25),
        { exact: false },
      ),
    ).toBeInTheDocument();
  });

  it("puts the transcript pane in the rightmost column", async () => {
    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    const grid = (await screen.findByTestId(
      "interview-detail-left-rail",
    )).parentElement;
    expect(grid).not.toBeNull();
    const children = Array.from(grid!.children) as HTMLElement[];
    const testIds = children.map((c) => c.dataset.testid);

    // Order matters: rail → pain_point → workaround → suggestion → transcript.
    expect(testIds).toEqual([
      "interview-detail-left-rail",
      "interview-detail-pain-point-column",
      "interview-detail-workaround-column",
      "interview-detail-suggestion-column",
      "interview-detail-transcript-column",
    ]);
  });

  it("clicking a Workarounds card triggers the transcript highlight handler", async () => {
    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    const user = userEvent.setup();
    // Sample fixture's workaround pain point has timestamps 6.5–24.1,
    // which overlaps transcript segment index 1.
    const workaroundCol = await screen.findByTestId(
      "interview-detail-workaround-column",
    );
    const card = within(workaroundCol).getByTestId(
      `pain-point-${samplePainPoints[0].id}`,
    );
    await user.click(card);

    // The transcript pane applies a transient yellow highlight on the
    // overlapping segment — assert via the `data-highlighted` attribute.
    await waitFor(() => {
      const seg = screen.getByTestId("transcript-segment-1");
      expect(seg.getAttribute("data-highlighted")).toBe("true");
    });
  });

  it("renders the failed-pipeline banner ABOVE the 5-region grid, not inside it", async () => {
    // SPEC_v1.2 acceptance: "Failed-pipeline banner sits above the grid
    // (no behaviour change from v1.1)." This regression-style test
    // protects against a future refactor that accidentally nests the
    // banner card inside the grid, which would steal a 12-col slot and
    // break the 3-2-2-2-3 layout.
    server.use(
      http.get("*/api/v1/interviews/:interviewId", ({ params }) =>
        HttpResponse.json({
          ...sampleInterview,
          id: params.interviewId,
          status: "failed",
          error_message: "AssemblyAI returned 503; please retry.",
          processed_at: null,
          pain_points: [],
        }),
      ),
    );

    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    // Banner present (role="alert" on the failed-banner Card).
    const banner = await screen.findByRole("alert");
    expect(banner).toBeInTheDocument();

    // The grid is identified by the left-rail's parent.
    const rail = screen.getByTestId("interview-detail-left-rail");
    const grid = rail.parentElement!;
    expect(grid).not.toBeNull();

    // Banner must NOT be a descendant of the grid div, and the grid
    // must still hold exactly the 5 layout children in spec order.
    expect(grid.contains(banner)).toBe(false);
    const testIds = (Array.from(grid.children) as HTMLElement[]).map(
      (c) => c.dataset.testid,
    );
    expect(testIds).toEqual([
      "interview-detail-left-rail",
      "interview-detail-pain-point-column",
      "interview-detail-workaround-column",
      "interview-detail-suggestion-column",
      "interview-detail-transcript-column",
    ]);
  });

  it("dispatches scrollToQuote on transcript-source interviews", async () => {
    // Swap the handler to return a transcript-source interview.
    const formatted =
      "[00:00 - 00:05] Speaker A\nIntro question.\n\n" +
      "[00:06 - 00:24] Speaker B\n" +
      samplePainPoints[1].supporting_quote +
      "\n\n[00:25 - 00:30] Speaker A\nThanks.";
    server.use(
      http.get("*/api/v1/interviews/:interviewId", ({ params }) =>
        HttpResponse.json({
          ...sampleInterview,
          id: params.interviewId,
          source_kind: "transcript",
          transcript_text: formatted,
          transcript_segments: null,
          pain_points: samplePainPoints,
        }),
      ),
    );

    renderDetail(sampleInterview.id);
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });

    // The preformatted block renders for transcript-source interviews.
    await screen.findByTestId("transcript-preformatted");

    const user = userEvent.setup();
    // Click the pain_point card whose supporting_quote is embedded in
    // the formatted transcript above.
    const painCol = screen.getByTestId("interview-detail-pain-point-column");
    const card = within(painCol).getByTestId(
      `pain-point-${samplePainPoints[1].id}`,
    );
    await user.click(card);

    // The pane should mount a highlight span for the matched range.
    await waitFor(() => {
      expect(screen.getByTestId("transcript-quote-match")).toBeInTheDocument();
    });
  });
});
