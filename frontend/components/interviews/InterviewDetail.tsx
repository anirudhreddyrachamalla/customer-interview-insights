"use client";

/**
 * Interview detail view — the working surface where the researcher
 * reads transcripts and skims pain points.
 *
 * v1.2 layout — single-viewport workspace on `lg+`:
 *
 *   ┌──── Header (breadcrumb, status, processed-at) ────┐
 *   │ Failed banner (full-width, only on status=failed) │
 *   ├────┬────┬────┬────┬─────────────────────────────┐ │
 *   │ 3  │ 2  │ 2  │ 2  │             3              │ │
 *   │ Lt │ PP │ WA │ Sg │           Trnscrpt         │ │
 *   └────┴────┴────┴────┴─────────────────────────────┘
 *
 * Left rail = demographics + meeting notes. Middle three columns =
 * `PainPointsPanel` filtered to `pain_point` / `workaround` /
 * `suggestion`. Rightmost = `TranscriptPane`. Each column manages its
 * own internal overflow; the page never scrolls on `lg+`.
 *
 * Behaviour:
 *
 *   - `useInterview` auto-polls every 3s while the pipeline is in
 *     `uploaded|transcribing|analyzing`, then stops.
 *   - Clicking a pain point branches on `source_kind`:
 *       • `"audio"` → compute overlapping segment indices, call
 *         `transcriptPane.scrollToIndex(...)`, apply the transient
 *         yellow highlight on those rows.
 *       • `"transcript"` → call
 *         `transcriptPane.scrollToQuote(pp.supporting_quote)` which
 *         highlights the matching range inside the preformatted block.
 *   - `status === "failed"` shows a destructive banner above the grid
 *     with a Retry button (POST `/interviews/{id}/retry`). A 409 toasts
 *     "Retry only allowed for failed interviews" rather than crashing.
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
  useProject,
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
 *  Returns an empty array if there are no transcript segments yet.
 *
 *  Pure timestamp overlap — segments emitted by the audio pipeline (and
 *  the VTT parser via `Speaker X · MM:SS` cues) always have real
 *  `start`/`end` values, so we can rely on a straight bbox check. */
export function overlappingIndices(
  segments: TranscriptSegment[] | null,
  pp: PainPoint,
): number[] {
  if (!segments || segments.length === 0) return [];

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
  const { data: project } = useProject(data?.project_id ?? "");
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

  const sourceKind = data?.source_kind ?? "audio";

  const handlePainPointClick = useCallback(
    (pp: PainPoint) => {
      if (sourceKind === "transcript") {
        // Preformatted-transcript path — highlight the substring inside
        // the cue-by-cue block. The pane no-ops if the quote can't be
        // matched (logs a console.warn for forensics).
        transcriptPaneRef.current?.scrollToQuote(pp.supporting_quote);
        return;
      }

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
    [data?.transcript_segments, sourceKind],
  );

  // ---- Loading -------------------------------------------------------
  if (isLoading) {
    return (
      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-4 px-6 py-6">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-1/4" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Skeleton className="h-[70vh] w-full lg:col-span-3" />
          <Skeleton className="h-[70vh] w-full lg:col-span-2" />
          <Skeleton className="h-[70vh] w-full lg:col-span-2" />
          <Skeleton className="h-[70vh] w-full lg:col-span-2" />
          <Skeleton className="h-[70vh] w-full lg:col-span-3" />
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
  const isTranscriptSource = data.source_kind === "transcript";
  const processedRelative = data.processed_at
    ? formatRelativeTime(data.processed_at)
    : null;

  // Pre-split the pain points by type so each column gets its own slice
  // (and we don't re-walk the array three times further down).
  const painPoints = data.pain_points;
  const painPointOnly = painPoints.filter((p) => p.type === "pain_point");
  const workaroundOnly = painPoints.filter((p) => p.type === "workaround");
  const suggestionOnly = painPoints.filter((p) => p.type === "suggestion");

  return (
    // The outer container reserves the viewport for the workspace. Header
    // + banner sit above the grid in normal flow; the grid itself is
    // sized with `h-[calc(100vh-…)]` so the columns can each manage
    // their own internal overflow without making the page scroll.
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-4 px-6 py-6">
      {/* --- Header ----------------------------------------------------- */}
      <header className="flex flex-col gap-2">
        <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
          <Link href="/" className="hover:text-foreground">
            Projects
          </Link>{" "}
          /{" "}
          <Link
            href={`/projects/${data.project_id}`}
            className="hover:text-foreground"
          >
            {project?.name ?? "Project"}
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
              {isTranscriptSource ? (
                <span data-testid="interview-source-kind">
                  Transcript upload
                </span>
              ) : null}
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

      {/* --- 5-region grid --------------------------------------------- */}
      {/*
       * Heights:
       *   - `lg:h-[calc(100vh-12rem)]` keeps the grid inside one viewport
       *     once the breakpoint kicks in. The 12rem reservation covers
       *     the header (breadcrumb + filename row + meta row + outer
       *     padding); a tiny bit of slack here is fine — overflow is
       *     handled per-column.
       *   - On smaller screens the height constraint is dropped and the
       *     grid stacks, so the page scrolls naturally.
       *
       * Each child uses `flex flex-col` + `min-h-0` so its inner
       * `overflow-y-auto` region can shrink to the column height.
       */}
      <div
        className={
          "grid grid-cols-1 gap-4 md:grid-cols-12 " +
          "lg:h-[calc(100vh-12rem)] lg:min-h-0"
        }
      >
        {/* Left rail: demographics + notes (col-3 on lg, col-4 on md) */}
        <aside
          className="flex flex-col gap-4 md:col-span-4 lg:col-span-3 lg:min-h-0 lg:overflow-y-auto"
          data-testid="interview-detail-left-rail"
        >
          <DemographicsSummary demographics={data.demographics} />
          <MeetingNotesCard meetingNotes={data.meeting_notes} />
        </aside>

        {/* Pain-point columns — pain_point / workaround / suggestion.
         *  On md they share a single row underneath the rail+transcript;
         *  on lg they sit in the middle three slots of the 12-col grid. */}
        <section
          className="flex min-h-0 flex-col md:col-span-4 lg:col-span-2"
          data-testid="interview-detail-pain-point-column"
        >
          <PainPointsPanel
            painPoints={painPointOnly}
            status={data.status}
            onClickPainPoint={handlePainPointClick}
            type="pain_point"
            hideTypeBadge
            count={painPointOnly.length}
            title="Pain points"
            emptyMessage="No pain points."
          />
        </section>
        <section
          className="flex min-h-0 flex-col md:col-span-4 lg:col-span-2"
          data-testid="interview-detail-workaround-column"
        >
          <PainPointsPanel
            painPoints={workaroundOnly}
            status={data.status}
            onClickPainPoint={handlePainPointClick}
            type="workaround"
            hideTypeBadge
            count={workaroundOnly.length}
            title="Workarounds"
            emptyMessage="No workarounds."
          />
        </section>
        <section
          className="flex min-h-0 flex-col md:col-span-4 lg:col-span-2"
          data-testid="interview-detail-suggestion-column"
        >
          <PainPointsPanel
            painPoints={suggestionOnly}
            status={data.status}
            onClickPainPoint={handlePainPointClick}
            type="suggestion"
            hideTypeBadge
            count={suggestionOnly.length}
            title="Suggestions"
            emptyMessage="No suggestions."
          />
        </section>

        {/* Transcript pane — rightmost column. */}
        <section
          className="flex min-h-0 flex-col md:col-span-8 lg:col-span-3"
          data-testid="interview-detail-transcript-column"
        >
          <TranscriptPane
            ref={transcriptPaneRef}
            segments={data.transcript_segments}
            transcriptText={data.transcript_text}
            sourceKind={data.source_kind}
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
      </div>
    </main>
  );
}
