"use client";

/**
 * Project insights centerpane — added in v1.1 (see SPEC_v1.1 §3).
 *
 * Mounted on `/projects/{id}` to the right of the compact interview
 * list. Owns the full lifecycle of the project-level Claude summary:
 *
 *   - `idle` + null markdown    → empty state + "Generate insights" CTA
 *   - `generating`              → skeleton + cadence hint (the polling
 *                                  is wired in `useProjectInsights`,
 *                                  refetching every 3s until status
 *                                  flips to `idle` or `failed`)
 *   - `idle` + markdown         → render summary via `react-markdown`,
 *                                  with a Refresh CTA, generated-at
 *                                  label, and a small "Stale" hint when
 *                                  new interviews have landed since
 *                                  the last refresh
 *   - `failed`                  → error card + "Try again" CTA
 *
 * The mutation handles the two documented 409 paths (already-running
 * and not-enough-completed-interviews) as toasts; anything else falls
 * back to the message in the problem body.
 *
 * Markdown is rendered with `react-markdown`'s defaults — raw HTML is
 * sanitised away, which is fine because Claude only emits headings,
 * bullets, and inline emphasis. Adding `remark-gfm` later would let
 * Claude use tables; not needed for v0.
 */

import { useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import {
  useProjectInsights,
  useRefreshInsights,
} from "@/lib/api/hooks";
import type { ProjectId } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";

interface ProjectInsightsPanelProps {
  projectId: ProjectId;
}

export function ProjectInsightsPanel({ projectId }: ProjectInsightsPanelProps) {
  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useProjectInsights(projectId);
  const refresh = useRefreshInsights(projectId);

  const handleRefresh = useCallback(() => {
    refresh.mutate(undefined, {
      onError: (err) => {
        if (err instanceof ApiError) {
          if (err.status === 409) {
            toast.error(
              err.problem.detail ??
                "Insights refresh already in progress.",
            );
            return;
          }
          toast.error(
            err.problem.detail ??
              err.problem.title ??
              "Could not refresh insights.",
          );
          return;
        }
        toast.error(
          err instanceof Error ? err.message : "Could not refresh insights.",
        );
      },
    });
  }, [refresh]);

  if (isLoading) {
    return (
      <Card className="h-full" data-testid="insights-panel">
        <CardHeader>
          <CardTitle>Project insights</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/4" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    const detail =
      error instanceof ApiError
        ? error.problem.detail ?? error.problem.title ?? error.message
        : error instanceof Error
          ? error.message
          : "Something went wrong loading project insights.";
    return (
      <Card
        role="alert"
        className="h-full border-destructive/40"
        data-testid="insights-panel"
      >
        <CardHeader>
          <CardTitle>Couldn&apos;t load insights</CardTitle>
          <CardDescription>{detail}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={() => {
              void refetch();
            }}
            disabled={isFetching}
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const generatedRelative = data.generated_at
    ? formatRelativeTime(data.generated_at)
    : null;

  // ---- failed ---------------------------------------------------------
  if (data.status === "failed") {
    return (
      <Card
        role="alert"
        className="h-full border-destructive/40"
        data-testid="insights-panel"
      >
        <CardHeader>
          <CardTitle>Insights generation failed</CardTitle>
          <CardDescription>
            {data.error_message ??
              "The summary task failed but didn't report a specific error."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="destructive"
            onClick={handleRefresh}
            disabled={refresh.isPending}
            data-testid="insights-try-again"
          >
            {refresh.isPending ? "Retrying…" : "Try again"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // ---- generating -----------------------------------------------------
  if (data.status === "generating") {
    return (
      <Card className="h-full" data-testid="insights-panel">
        <CardHeader>
          <CardTitle>Project insights</CardTitle>
          <CardDescription aria-live="polite">
            Generating — this usually takes ~10-30s.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-5 w-1/4 mt-4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-10/12" />
        </CardContent>
      </Card>
    );
  }

  // ---- idle + no summary yet → empty state ---------------------------
  if (data.summary_markdown === null) {
    const canGenerate = data.interview_count_completed > 0;
    return (
      <Card
        className="h-full"
        data-testid="insights-panel"
        data-insights-state="empty"
      >
        <CardHeader>
          <CardTitle>Project insights</CardTitle>
          <CardDescription>
            {canGenerate
              ? "Generate a Claude summary of the common pain points, workarounds, and suggestions across this project."
              : "Add a completed interview to enable cross-interview insights."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            onClick={handleRefresh}
            disabled={refresh.isPending || !canGenerate}
            data-testid="insights-generate"
          >
            {refresh.isPending ? "Generating…" : "Generate insights"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // ---- idle + summary rendered ---------------------------------------
  return (
    <Card
      className="h-full"
      data-testid="insights-panel"
      data-insights-state="ready"
    >
      <CardHeader>
        <CardTitle>Project insights</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span data-testid="insights-meta">
            {generatedRelative
              ? `Generated ${generatedRelative}`
              : "Generated"}{" "}
            ·{" "}
            {data.interview_count_summarised}{" "}
            {data.interview_count_summarised === 1
              ? "interview"
              : "interviews"}
          </span>
          {data.is_stale ? (
            <span
              className="text-xs text-amber-600 dark:text-amber-400"
              data-testid="insights-stale-hint"
            >
              Stale — interviews have been added or completed since last
              refresh
            </span>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div
          className="prose prose-sm dark:prose-invert max-w-none [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-1"
          data-testid="insights-markdown"
        >
          <ReactMarkdown>{data.summary_markdown}</ReactMarkdown>
        </div>
        <div>
          <Button
            variant="secondary"
            onClick={handleRefresh}
            disabled={refresh.isPending}
            data-testid="insights-refresh"
          >
            {refresh.isPending ? "Refreshing…" : "Refresh"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
