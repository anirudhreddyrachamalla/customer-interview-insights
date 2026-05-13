/**
 * Tests for the Retry behaviour on the interview detail page.
 *
 * Per `.claude/agents/tester.md`, the v0 retry surface may be either a
 * dedicated `RetryButton` component OR a button rendered inline inside
 * `InterviewDetail`. The frontend teammate shipped task #4 with the
 * button living inside `InterviewDetail`, so we drive these tests
 * through `InterviewDetail` directly. The behavioural contract is the
 * same regardless of where the button lives:
 *
 *   - on `status === "failed"`, the Retry button is visible
 *   - clicking it POSTs `/api/v1/interviews/{id}/retry`
 *   - a 409 response surfaces as a visible (toast) error
 *   - on `status === "completed"`, no Retry button is visible
 *
 * `sonner` toasts are rendered through a portal; the suite mocks the
 * top-level `toast.error` so we can assert the message without
 * mounting a `<Toaster />`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { InterviewDetail } from "@/components/interviews/InterviewDetail";
import { server } from "@/tests/msw/server";
import { failedInterviewHandlers } from "@/tests/msw/handlers";
import {
  sampleInterview,
  sampleInterviewFailed,
} from "@/tests/fixtures/sampleInterview";

// --- Mocks ----------------------------------------------------------

// `sonner` toasts open through a portal; in jsdom we don't mount a
// <Toaster />, so spy on toast.error to capture the visible message.
// `vi.hoisted` runs before the `vi.mock` hoist, so the spy is in scope
// when the factory executes.
const { toastErrorMock } = vi.hoisted(() => ({
  toastErrorMock: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: { error: toastErrorMock, success: vi.fn(), message: vi.fn() },
  Toaster: () => null,
}));

// `next/navigation` — InterviewDetail uses <Link> via the Button render
// prop. <Link> in tests would otherwise rely on the Next router. Stub
// it so renders succeed under jsdom.
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
  toastErrorMock.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

// --- Helpers --------------------------------------------------------

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

// --- Suite ----------------------------------------------------------

describe("Retry behaviour on InterviewDetail", () => {
  it("shows a Retry button when status is 'failed'", async () => {
    server.use(...failedInterviewHandlers);
    renderDetail(sampleInterviewFailed.id);

    expect(
      await screen.findByRole("button", { name: /^retry$/i }),
    ).toBeInTheDocument();
    // And the error message from the failed interview is visible.
    expect(
      screen.getByText(/AssemblyAI returned 503/i),
    ).toBeInTheDocument();
  });

  it("POSTs /interviews/{id}/retry when the Retry button is clicked", async () => {
    server.use(...failedInterviewHandlers);

    const seen: string[] = [];
    server.use(
      http.post(
        "*/api/v1/interviews/:interviewId/retry",
        async ({ params }) => {
          seen.push(params.interviewId as string);
          return HttpResponse.json(
            { ...sampleInterviewFailed, status: "transcribing" },
            { status: 202 },
          );
        },
      ),
    );

    renderDetail(sampleInterviewFailed.id);
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: /^retry$/i });
    await user.click(button);

    await waitFor(() => {
      expect(seen).toEqual([sampleInterviewFailed.id]);
    });
  });

  it("surfaces a visible toast when the retry endpoint returns 409", async () => {
    server.use(...failedInterviewHandlers);
    server.use(
      http.post("*/api/v1/interviews/:interviewId/retry", () =>
        HttpResponse.json(
          {
            status: 409,
            title: "Conflict",
            detail: "retry only valid when status=failed",
            type: "about:blank",
          },
          { status: 409 },
        ),
      ),
    );

    renderDetail(sampleInterviewFailed.id);
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: /^retry$/i });
    await user.click(button);

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    // The component uses a friendly message for 409, not the raw
    // problem-detail string — assert on that contract.
    const calls = toastErrorMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((msg) => /retry only allowed/i.test(msg))).toBe(true);
  });

  it("hides the Retry button when status is 'completed'", async () => {
    // Default handlers return the completed sampleInterview at this id.
    renderDetail(sampleInterview.id);

    // Wait for the page to actually settle on the completed interview
    // before asserting absence. The audio filename is in the header so
    // it's a reliable "done loading" signal.
    await screen.findByRole("heading", {
      name: new RegExp(sampleInterview.audio_filename, "i"),
    });
    expect(
      screen.queryByRole("button", { name: /^retry$/i }),
    ).not.toBeInTheDocument();
  });
});
