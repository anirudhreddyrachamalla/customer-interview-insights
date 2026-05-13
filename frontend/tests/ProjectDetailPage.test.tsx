/**
 * Integration test for the v1.1 `/projects/{id}` redesign.
 *
 * Covers (per SPEC_v1.1 §3+4 "Tests (frontend)"):
 *
 *  - Compact rows show only name + gender + StatusBadge; NO other
 *    demographic chips (industry, income, marital status, etc.).
 *  - Clicking a row navigates to `/interviews/{id}` — verified via the
 *    rendered `<a href>` since jsdom doesn't actually follow links.
 *  - The right column mounts `ProjectInsightsPanel`, which (with the
 *    default MSW handler) lands in the empty-state with a Generate CTA.
 *
 * Like the existing detail-page tests, we mount the page component
 * directly with a fresh QueryClient instead of going through Next's
 * routing.
 */

import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import ProjectDetailPage from "@/app/projects/[id]/page";
import { server } from "@/tests/msw/server";
import {
  sampleDemographics,
  sampleInterview,
  sampleProject,
} from "@/tests/fixtures/sampleInterview";

// `next/navigation` shim — the page uses `<Link>` from next/link which
// renders an anchor; that doesn't need router state, but the project
// page calls `use(params)` so we pass a resolved Promise as `params`.
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

const API = "*/api/v1";

/**
 * Mount the page with the params promise already wrapped in a way that
 * `use()` resolves on the first render — Promise.resolve(...) suspends
 * once in React 19 + jsdom and never re-renders inside the
 * Testing-Library `act()` flush. Constructing the promise so its `then`
 * runs synchronously gets us past the suspension cleanly.
 */
function resolvedPromise<T>(value: T): Promise<T> {
  // Cast to `Promise<T>` so the type matches the page's `params` prop
  // while sidestepping the suspension wait.
  const p: Promise<T> = new Promise((resolve) => resolve(value));
  // React's `use()` reads the `status` + `value` slots from the
  // promise's internal cache. Pre-resolving makes the first read
  // succeed instead of suspending.
  (p as unknown as { status?: string; value?: T }).status = "fulfilled";
  (p as unknown as { status?: string; value?: T }).value = value;
  return p;
}

function renderProjectPage(projectId = sampleProject.id) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Suspense fallback={<div data-testid="suspense-fallback" />}>
        <ProjectDetailPage params={resolvedPromise({ id: projectId })} />
      </Suspense>
    </QueryClientProvider>,
  );
}

describe("ProjectDetailPage (v1.1 redesign)", () => {
  it("renders compact rows with name + gender + status, and no other demographic chips", async () => {
    // Two interviews so we can also confirm the list renders multiple
    // rows in <ul>/divide-y form.
    const second = {
      ...sampleInterview,
      id: "44444444-4444-4444-4444-444444444444",
      demographics: {
        ...sampleDemographics,
        name: "Casey Customer",
        gender: "male" as const,
        income: "100k_200k" as const,
        industry: "saas_software" as const,
        job_role: "engineer" as const,
        marital_status: "married" as const,
        country: "IN",
      },
      status: "transcribing" as const,
    };

    server.use(
      http.get(`${API}/projects/:projectId/interviews`, () =>
        HttpResponse.json({ items: [sampleInterview, second] }),
      ),
    );

    renderProjectPage();

    // Wait for the interview rows to land — that signals both queries
    // (project + project interviews) have resolved.
    await screen.findByTestId(`interview-row-${sampleInterview.id}`);

    const row1 = await screen.findByTestId(
      `interview-row-${sampleInterview.id}`,
    );
    const row2 = await screen.findByTestId(`interview-row-${second.id}`);

    // Name + gender are visible.
    expect(
      within(row1).getByText(sampleInterview.demographics.name),
    ).toBeInTheDocument();
    expect(within(row1).getByText(/non-binary/i)).toBeInTheDocument();

    expect(within(row2).getByText("Casey Customer")).toBeInTheDocument();
    expect(within(row2).getByText(/^male$/i)).toBeInTheDocument();

    // StatusBadge is rendered (labelled via aria-label="Status: …").
    expect(
      within(row1).getByLabelText(/^status: completed$/i),
    ).toBeInTheDocument();
    expect(
      within(row2).getByLabelText(/^status: transcribing/i),
    ).toBeInTheDocument();

    // No other demographic chips: industry / income / job-role / country
    // labels must NOT appear in the compact row.
    expect(within(row1).queryByText(/saas/i)).not.toBeInTheDocument();
    expect(within(row1).queryByText(/100k/i)).not.toBeInTheDocument();
    expect(
      within(row1).queryByText(/product manager/i),
    ).not.toBeInTheDocument();
    expect(within(row1).queryByText(/^US$/)).not.toBeInTheDocument();

    expect(within(row2).queryByText(/saas/i)).not.toBeInTheDocument();
    expect(within(row2).queryByText(/engineer/i)).not.toBeInTheDocument();
    expect(within(row2).queryByText(/^IN$/)).not.toBeInTheDocument();
  });

  it("each row links to /interviews/{id}", async () => {
    server.use(
      http.get(`${API}/projects/:projectId/interviews`, () =>
        HttpResponse.json({ items: [sampleInterview] }),
      ),
    );
    renderProjectPage();

    const row = await screen.findByTestId(
      `interview-row-${sampleInterview.id}`,
    );
    expect(row.tagName.toLowerCase()).toBe("a");
    expect(row).toHaveAttribute("href", `/interviews/${sampleInterview.id}`);
  });

  it("mounts the insights panel in its empty state on first load", async () => {
    // Default MSW handler returns the synthetic idle/null payload.
    server.use(
      http.get(`${API}/projects/:projectId/interviews`, () =>
        HttpResponse.json({ items: [sampleInterview] }),
      ),
    );
    renderProjectPage();

    // Wait for the insights query to resolve into the empty-state CTA.
    expect(
      await screen.findByTestId("insights-generate"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("insights-panel")).toBeInTheDocument();
  });
});
