/**
 * Component tests for `ProjectInsightsPanel` — the v1.1 cross-interview
 * Claude summary on `/projects/{id}`.
 *
 * Coverage (mirrors the "Tests (frontend)" bullets in SPEC_v1.1 §3):
 *
 *  1. `idle` + null markdown → empty state with "Generate insights" CTA.
 *  2. Clicking "Generate insights" POSTs to `/refresh` and seeds the
 *     `generating` state into the cache (which the loader uses).
 *  3. `idle` + markdown renders the markdown via `react-markdown` with
 *     a Refresh button, meta line, and (when stale) the staleness hint.
 *  4. `failed` renders an error card + "Try again" button.
 *  5. 409 from refresh surfaces as a toast, not an unhandled exception.
 *
 * The panel reads from `useProjectInsights` (TanStack Query); we drive
 * its state by registering MSW handlers per test rather than mocking
 * the hook directly — keeps the test honest about the fetch shape.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import { ProjectInsightsPanel } from "@/components/projects/ProjectInsightsPanel";
import { server } from "@/tests/msw/server";

const API = "*/api/v1";

// Mock sonner so we can assert on toast.error invocations without
// needing the actual toaster mounted in the tree.
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: vi.fn(),
    message: vi.fn(),
  },
}));

function renderPanel(projectId = "proj-123") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectInsightsPanel projectId={projectId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  toastError.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProjectInsightsPanel", () => {
  it("renders the empty state with a Generate CTA when status='idle' and markdown is null", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown: null,
          interview_count_summarised: 0,
          interview_count_completed: 2,
          is_stale: false,
          error_message: null,
          model: null,
          generated_at: null,
          updated_at: "2026-05-01T10:00:00Z",
        }),
      ),
    );

    renderPanel();

    const generateBtn = await screen.findByTestId("insights-generate");
    expect(generateBtn).toBeInTheDocument();
    expect(generateBtn).toHaveTextContent(/generate insights/i);
    expect(generateBtn).not.toBeDisabled();
  });

  it("disables the Generate CTA when no completed interviews exist", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown: null,
          interview_count_summarised: 0,
          interview_count_completed: 0,
          is_stale: false,
          error_message: null,
          model: null,
          generated_at: null,
          updated_at: "2026-05-01T10:00:00Z",
        }),
      ),
    );

    renderPanel();

    const generateBtn = await screen.findByTestId("insights-generate");
    expect(generateBtn).toBeDisabled();
  });

  it("triggers a POST to /refresh when Generate is clicked", async () => {
    const refreshSpy = vi.fn();
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown: null,
          interview_count_summarised: 0,
          interview_count_completed: 2,
          is_stale: false,
          error_message: null,
          model: null,
          generated_at: null,
          updated_at: "2026-05-01T10:00:00Z",
        }),
      ),
      http.post(
        `${API}/projects/:projectId/insights/refresh`,
        ({ params }) => {
          refreshSpy();
          return HttpResponse.json(
            {
              project_id: params.projectId,
              status: "generating",
              summary_markdown: null,
              interview_count_summarised: 0,
              interview_count_completed: 2,
              is_stale: false,
              error_message: null,
              model: "claude-sonnet-4-6",
              generated_at: null,
              updated_at: "2026-05-01T10:05:00Z",
            },
            { status: 202 },
          );
        },
      ),
    );

    const user = userEvent.setup();
    renderPanel();

    const generateBtn = await screen.findByTestId("insights-generate");
    await user.click(generateBtn);

    await waitFor(() => {
      expect(refreshSpy).toHaveBeenCalledTimes(1);
    });

    // After the 202 lands, the generating state is seeded into the cache.
    await screen.findByText(/generating —/i);
  });

  it("renders the markdown summary, meta line, and Refresh button when status='idle' with markdown", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown:
            "## Common pain points\n- Onboarding friction (5/7 interviews)\n\n## Common workarounds\n- Manual CSV exports",
          interview_count_summarised: 7,
          interview_count_completed: 7,
          is_stale: false,
          error_message: null,
          model: "claude-sonnet-4-6",
          generated_at: "2026-05-01T10:00:00Z",
          updated_at: "2026-05-01T10:05:00Z",
        }),
      ),
    );

    renderPanel();

    const markdown = await screen.findByTestId("insights-markdown");
    expect(within(markdown).getByText("Common pain points")).toBeInTheDocument();
    expect(
      within(markdown).getByText(/onboarding friction \(5\/7 interviews\)/i),
    ).toBeInTheDocument();
    expect(within(markdown).getByText("Common workarounds")).toBeInTheDocument();

    // Meta line shows the summarised count and a generated-at relative
    // timestamp.
    const meta = screen.getByTestId("insights-meta");
    expect(meta).toHaveTextContent(/7 interviews/);

    // Refresh CTA is visible.
    expect(screen.getByTestId("insights-refresh")).toBeInTheDocument();

    // Stale hint must NOT be present in the not-stale path.
    expect(
      screen.queryByTestId("insights-stale-hint"),
    ).not.toBeInTheDocument();
  });

  it("shows the stale hint when is_stale is true", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown: "## Common pain points\n- Something",
          interview_count_summarised: 5,
          interview_count_completed: 7,
          is_stale: true,
          error_message: null,
          model: "claude-sonnet-4-6",
          generated_at: "2026-05-01T10:00:00Z",
          updated_at: "2026-05-01T10:05:00Z",
        }),
      ),
    );

    renderPanel();

    const hint = await screen.findByTestId("insights-stale-hint");
    expect(hint).toHaveTextContent(/stale/i);
  });

  it("renders the failure card and a Try again button when status='failed'", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "failed",
          summary_markdown: null,
          interview_count_summarised: 0,
          interview_count_completed: 3,
          is_stale: false,
          error_message: "Claude returned 503",
          model: "claude-sonnet-4-6",
          generated_at: null,
          updated_at: "2026-05-01T10:05:00Z",
        }),
      ),
    );

    renderPanel();

    expect(
      await screen.findByText(/insights generation failed/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/claude returned 503/i)).toBeInTheDocument();
    expect(screen.getByTestId("insights-try-again")).toBeInTheDocument();
  });

  it("surfaces a 409 from /refresh as a toast", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown: null,
          interview_count_summarised: 0,
          interview_count_completed: 2,
          is_stale: false,
          error_message: null,
          model: null,
          generated_at: null,
          updated_at: "2026-05-01T10:00:00Z",
        }),
      ),
      http.post(`${API}/projects/:projectId/insights/refresh`, () =>
        HttpResponse.json(
          { detail: "Insight generation already in progress." },
          { status: 409 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderPanel();

    const generateBtn = await screen.findByTestId("insights-generate");
    await user.click(generateBtn);

    await waitFor(() => {
      expect(toastError).toHaveBeenCalled();
    });
    const firstCallArg = toastError.mock.calls[0]?.[0] as string;
    expect(firstCallArg.toLowerCase()).toContain("progress");
  });

  it("renders markdown safely — raw HTML in the summary is escaped, not injected", async () => {
    // SPEC_v1.1 §3 "Tests (frontend)": "Markdown renders safely (no raw
    // HTML allowed; react-markdown default)". We assert this by handing
    // the panel a summary that includes a <script> tag and an inline
    // <img onerror=...>; react-markdown's defaults should render those
    // as text (or strip them entirely), never mount them as real DOM
    // nodes inside the insights container.
    server.use(
      http.get(`${API}/projects/:projectId/insights`, ({ params }) =>
        HttpResponse.json({
          project_id: params.projectId,
          status: "idle",
          summary_markdown:
            "## Common pain points\n\n- safe bullet\n\n<script>window.__pwn = 1</script>\n\n<img src=x onerror=\"window.__pwn2 = 1\" />",
          interview_count_summarised: 3,
          interview_count_completed: 3,
          is_stale: false,
          error_message: null,
          model: "claude-sonnet-4-6",
          generated_at: "2026-05-01T10:00:00Z",
          updated_at: "2026-05-01T10:05:00Z",
        }),
      ),
    );

    renderPanel();

    const markdown = await screen.findByTestId("insights-markdown");
    // The safe markdown content rendered normally.
    expect(within(markdown).getByText("Common pain points")).toBeInTheDocument();
    expect(within(markdown).getByText("safe bullet")).toBeInTheDocument();

    // No <script> element should have been mounted (react-markdown's
    // default does not allow raw HTML).
    expect(markdown.querySelector("script")).toBeNull();

    // No <img> element should have been mounted either.
    expect(markdown.querySelector("img")).toBeNull();

    // And neither side-effect should have been observed.
    expect(
      (window as unknown as { __pwn?: unknown }).__pwn,
    ).toBeUndefined();
    expect(
      (window as unknown as { __pwn2?: unknown }).__pwn2,
    ).toBeUndefined();
  });
});
