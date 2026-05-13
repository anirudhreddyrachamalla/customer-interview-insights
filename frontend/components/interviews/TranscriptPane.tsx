"use client";

/**
 * Transcript pane — center column of the interview detail page.
 *
 * Renders one paragraph per AssemblyAI segment, with a speaker badge,
 * an `mm:ss` timestamp, and the segment text. The pane scrolls
 * internally (rather than the whole page) so that scrolling to a pain
 * point's segment doesn't yank the audio player out of view.
 *
 * Imperative API
 * --------------
 * The parent (`InterviewDetail`) gets a ref handle exposing:
 *
 *   scrollToIndex(i: number): void
 *
 * which scrolls the matching segment into the middle of the pane with a
 * smooth animation. The `highlightedIndices` prop drives the visual
 * highlight on the matching rows; the parent clears the set after ~3s
 * so the highlight is transient.
 *
 * States:
 *   - segments is a list  → render rows
 *   - segments === null and status is pre-completion → skeleton rows
 *     (the parent passes `loading`)
 *   - segments === null and status is failed → "Transcript unavailable"
 *
 * Implementation notes:
 *   - The row ref array is rebuilt from scratch each render. Storing it
 *     in a `useRef([])` and re-pointing entries via the callback ref
 *     keeps us correct even if the segment list changes length while
 *     the pane is mounted (it doesn't today, but defensive is cheap).
 *   - `scrollIntoView({block: "center"})` works inside the overflow
 *     container without scrolling the page.
 */

import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatTimestamp } from "@/lib/utils";
import type { Interview, TranscriptSegment } from "@/lib/api/types";

export interface TranscriptPaneHandle {
  scrollToIndex: (index: number) => void;
}

export interface TranscriptPaneProps {
  segments: TranscriptSegment[] | null;
  highlightedIndices: ReadonlySet<number>;
  /** When `segments` is null, this controls whether to render
   *  skeleton rows (true) or the "unavailable" empty state (false). */
  loading: boolean;
  /** Used purely to label the empty state ("Transcript unavailable…"
   *  when the pipeline failed). Other statuses fall through to the
   *  skeleton/loading branch. */
  status: Interview["status"];
}

export const TranscriptPane = forwardRef<
  TranscriptPaneHandle,
  TranscriptPaneProps
>(function TranscriptPane(
  { segments, highlightedIndices, loading, status },
  ref,
) {
  const rowRefs = useRef<(HTMLLIElement | null)[]>([]);

  // Reset the ref array length to match the current segments so stale
  // entries from a previous render don't linger after a refetch.
  if (segments && rowRefs.current.length !== segments.length) {
    rowRefs.current = new Array(segments.length).fill(null);
  }

  useImperativeHandle(
    ref,
    () => ({
      scrollToIndex(index: number) {
        const el = rowRefs.current[index];
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      },
    }),
    [],
  );

  // Speakers come back as raw labels ("A", "B", …). Render them as
  // `Speaker A` for readability without losing the underlying letter.
  const speakerLabel = useMemo(
    () => (s: string) => (s.length === 1 ? `Speaker ${s}` : s),
    [],
  );

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Transcript</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className="overflow-y-auto max-h-[calc(100vh-12rem)] pr-2"
          data-testid="transcript-scroll"
        >
          {segments && segments.length > 0 ? (
            <ol className="flex flex-col gap-4">
              {segments.map((seg, i) => {
                const highlighted = highlightedIndices.has(i);
                return (
                  <li
                    key={i}
                    ref={(el) => {
                      rowRefs.current[i] = el;
                    }}
                    data-testid={`transcript-segment-${i}`}
                    data-highlighted={highlighted ? "true" : undefined}
                    className={cn(
                      "rounded-md p-3 transition-colors",
                      highlighted
                        ? "bg-yellow-200 dark:bg-yellow-500/20"
                        : "bg-transparent",
                    )}
                  >
                    <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <Badge variant="secondary" className="font-mono">
                        {speakerLabel(seg.speaker)}
                      </Badge>
                      <span className="font-mono tabular-nums">
                        {formatTimestamp(seg.start)}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed text-foreground">
                      {seg.text}
                    </p>
                  </li>
                );
              })}
            </ol>
          ) : segments && segments.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Transcript is empty.
            </p>
          ) : loading ? (
            <div className="flex flex-col gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex flex-col gap-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {status === "failed"
                ? "Transcript unavailable — see error in pain points panel."
                : "Transcript is not available yet."}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
