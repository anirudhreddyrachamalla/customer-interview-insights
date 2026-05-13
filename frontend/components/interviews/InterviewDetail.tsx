"use client";

/**
 * Interview detail view — the working surface where the researcher
 * reads transcripts and skims pain points.
 *
 * Composition:
 *
 *   [Header]   audio filename, status badge, processed-at, back link
 *   [3-pane]   ┌─ DemographicsSummary + MeetingNotesCard
 *              │  TranscriptPane (center, with imperative scroll)
 *              └─ PainPointsPanel (right, sorted by severity)
 *
 * Behaviour:
 *
 *   - The data hook (`useInterview`) auto-polls every 3s while the
 *     pipeline is in `uploaded|transcribing|analyzing`, then stops.
 *   - Clicking a pain point computes which transcript segments overlap
 *     its `[start, end]` window, scrolls the transcript pane to the
 *     first one, and applies a yellow highlight to all overlapping
 *     segments for ~3 seconds.
 *   - When `status === "failed"`, we replace the transcript/pain-point
 *     columns with a destructive error card + Retry button. The retry
 *     mutation hits `POST /interviews/{id}/retry`; a 409 toasts an
 *     informative message rather than crashing.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { DemographicsSummary } from "@/components/interviews/DemographicsSummary";
import { MeetingNotesCard } from "@/components/interviews/MeetingNotesCard";
import { PainPointsPanel } from "@/components/interviews/PainPointsPanel";
import { StatusBadge } from "@/components/interviews/StatusBadge";
import {
  TranscriptPane,
  type TranscriptPaneHandle,
} from "@/components/interviews/TranscriptPane";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api/client";
import {
  POLLABLE_STATUSES,
  queryKeys,
  useInterview,
} from "@/lib/api/hooks";
import type {
  Interview,
  InterviewId,
  PainPoint,
  TranscriptSegment,
} from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/utils";

interface InterviewDetailProps {
  interviewId: InterviewId;
}

/** How long a highlight stays on the transcript after a pain-point
 *  click. Kept short so the user can immediately scan and move on. */
const HIGHLIGHT_DURATION_MS = 3000;

/** Compute which segment indices overlap a pain point's time window.
 *  Returns an empty array if there are no transcript segments yet. */
function overlappingIndices(
  segments: TranscriptSegment[] | null,
  pp: PainPoint,
): number[] {
  if (!segments) return [];
  const indices: number[] = [];
  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    if (
      seg.end >= pp.timestamp_start_sec &&
      seg.start <= pp.timestamp_end_sec
    ) {
      indices.push(i);
    }
  }
  return indices;
}

export function InterviewDetail({ interviewId }: InterviewDetailProps) {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useInterview(interviewId);
  const queryClient = useQueryClient();

  const transcriptPaneRef = useRef<TranscriptPaneHandle | null>(null);
  const [highlightedIndices, setHighlightedIndices] = useState<Set<number>>(
    () => new Set(),
  );

  // Clear the transient highlight after the timeout fires. Storing the
  // timer in a ref means clicking another pain point cancels the
  // pending clear cleanly rather than racing it.
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (highlightTimer.current) clearTimeout(highlightTimer.current);
    },
    [],
  );

  // Retry mutation. Seeds the cache directly with the 202 response so
  // polling can re-take the wheel without a wasted refetch.
  const retryMutation = useMutation<Interview, unknown, InterviewId>({
    mutationFn: (id) => api.post<Interview>(`/interviews/${id}/retry`),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.interview(data.id), data);
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        if (err.status === 409) {
          toast.error("Retry only allowed for failed interviews");
          return;
        }
        toast.error(
          err.problem.detail ??
            err.problem.title ??
            "Could not retry this interview.",
        );
        return;
      }
      toast.error(
        err instanceof Error ? err.message : "Could not retry this interview.",
      );
    },
  });

  const handlePainPointClick = useCallback(
    (pp: PainPoint) => {
      const segments = data?.transcript_segments ?? null;
      const indices = overlappingIndices(segments, pp);
      if (indices.length === 0) return;
      const next = new Set(indices);
      setHighlightedIndices(next);
      transcriptPaneRef.current?.scrollToIndex(indices[0]);
      if (highlightTimer.current) clearTimeout(highlightTimer.current);
      highlightTimer.current = setTimeout(() => {
        setHighlightedIndices(new Set());
      }, HIGHLIGHT_DURATION_MS);
    },
    [data?.transcript_segments],
  );

  // ---- Loading -------------------------------------------------------
  if (isLoading) {
    return (
      <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-8 py-10">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-1/4" />
        <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
          <div className="md:col-span-3 flex flex-col gap-4">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
          <div className="md:col-span-6">
            <Skeleton className="h-[60vh] w-full" />
          </div>
          <div className="md:col-span-3">
            <Skeleton className="h-[60vh] w-full" />
          </div>
        </div>
      </main>
    );
  }

  // ---- 404 / error ---------------------------------------------------
  if (isError) {
    const status = error instanceof ApiError ? error.status : undefined;
    if (status === 404) {
      return (
        <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center gap-6 px-8 py-24 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            Interview not found
          </h1>
          <p className="text-sm text-muted-foreground">
            The interview you&apos;re looking for doesn&apos;t exist or has been
            deleted.
          </p>
          <Button render={<Link href="/">Back to projects</Link>} />
        </main>
      );
    }
    const detail =
      error instanceof ApiError
        ? error.problem.detail ?? error.problem.title ?? error.message
        : error instanceof Error
          ? error.message
          : "Something went wrong loading this interview.";
    return (
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col gap-6 px-8 py-24">
        <Card role="alert" className="items-center text-center">
          <CardHeader className="items-center">
            <CardTitle>Couldn&apos;t load interview</CardTitle>
            <CardDescription>{detail}</CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center pb-4">
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
      </main>
    );
  }

  if (!data) return null;

  const isProcessing = POLLABLE_STATUSES.has(data.status);
  const isFailed = data.status === "failed";
  const processedRelative = data.processed_at
    ? formatRelativeTime(data.processed_at)
    : null;

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-8 py-10">
      {/* --- Header ----------------------------------------------------- */}
      <header className="flex flex-col gap-3">
        <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground">
            Projects
          </Link>{" "}
          /{" "}
          <Link
            href={`/projects/${data.project_id}`}
            className="hover:text-foreground"
          >
            Project
          </Link>{" "}
          /{" "}
          <span className="text-foreground">{data.audio_filename}</span>
        </nav>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {data.audio_filename}
            </h1>
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <StatusBadge status={data.status} />
              {data.status === "completed" && processedRelative ? (
                <span>Processed {processedRelative}</span>
              ) : null}
              {isProcessing ? (
                <span aria-live="polite">
                  Refreshing every 3s while the pipeline runs…
                </span>
              ) : null}
            </div>
          </div>
          <Button
            variant="secondary"
            render={
              <Link href={`/projects/${data.project_id}`}>
                Back to project
              </Link>
            }
          />
        </div>
      </header>

      {/* --- Failed banner --------------------------------------------- */}
      {isFailed ? (
        <Card role="alert" className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">
              Processing failed
            </CardTitle>
            <CardDescription>
              {data.error_message ??
                "The pipeline failed but didn't report a specific error."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={() => retryMutation.mutate(data.id)}
              disabled={retryMutation.isPending}
            >
              {retryMutation.isPending ? "Retrying…" : "Retry"}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {/* --- 3-pane grid ----------------------------------------------- */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-12">
        {/* Left: demographics + notes */}
        <aside className="md:col-span-3 flex flex-col gap-4">
          <DemographicsSummary demographics={data.demographics} />
          <MeetingNotesCard meetingNotes={data.meeting_notes} />
        </aside>

        {/* Center: transcript */}
        <section className="md:col-span-6">
          <TranscriptPane
            ref={transcriptPaneRef}
            segments={data.transcript_segments}
            highlightedIndices={highlightedIndices}
            loading={
              data.transcript_segments === null &&
              (data.status === "uploaded" ||
                data.status === "transcribing" ||
                data.status === "analyzing")
            }
            status={data.status}
          />
        </section>

        {/* Right: pain points */}
        <section className="md:col-span-3">
          <PainPointsPanel
            painPoints={data.pain_points}
            status={data.status}
            onClickPainPoint={handlePainPointClick}
          />
        </section>
      </div>
    </main>
  );
}
