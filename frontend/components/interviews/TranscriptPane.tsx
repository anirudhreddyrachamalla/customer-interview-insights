"use client";

/**
 * Transcript pane — rightmost column of the interview detail page.
 *
 * Two rendering modes, selected by `sourceKind`:
 *
 *  - `"audio"` (default): one paragraph per AssemblyAI segment, with a
 *    speaker badge, an `mm:ss` timestamp, and the segment text. The
 *    `scrollToIndex(i)` imperative method jumps to a row by index.
 *  - `"transcript"`: render `transcript_text` verbatim inside a
 *    `<pre>` so the VTT cue-by-cue format (timestamps + speaker labels
 *    + blank-line separators) shows up as the researcher uploaded it.
 *    The `scrollToQuote(quote)` imperative method finds + highlights a
 *    substring inside the preformatted block.
 *
 * The pane scrolls internally (rather than the whole page) so jumping
 * to a pain point's segment doesn't yank surrounding cards out of view.
 *
 * Imperative API
 * --------------
 * `InterviewDetail` gets a ref handle exposing both methods:
 *
 *   scrollToIndex(i: number): void
 *   scrollToQuote(q: string): void
 *
 * The inactive method (e.g. `scrollToIndex` in transcript mode) is a
 * no-op, so callers can dispatch based on `source_kind` without
 * branching on null handles.
 */

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { findQuoteRange } from "@/lib/transcript";
import { cn, formatTimestamp } from "@/lib/utils";
import type { Interview, TranscriptSegment } from "@/lib/api/types";

export interface TranscriptPaneHandle {
  scrollToIndex: (index: number) => void;
  scrollToQuote: (quote: string) => void;
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
  /** Where this interview's content came from. Drives which renderer
   *  the pane uses. Defaults to `"audio"` for backwards compatibility
   *  with v0/v1.1 call sites. */
  sourceKind?: Interview["source_kind"];
  /** Preformatted transcript text — only consulted when
   *  `sourceKind === "transcript"`. May be null while the pipeline is
   *  still running, in which case the loading/empty branches kick in. */
  transcriptText?: string | null;
}

/** How long a `scrollToQuote` highlight stays on the preformatted
 *  transcript before clearing. Mirrors the audio path. */
const HIGHLIGHT_DURATION_MS = 3000;

export const TranscriptPane = forwardRef<
  TranscriptPaneHandle,
  TranscriptPaneProps
>(function TranscriptPane(
  {
    segments,
    highlightedIndices,
    loading,
    status,
    sourceKind = "audio",
    transcriptText,
  },
  ref,
) {
  const isTranscriptMode = sourceKind === "transcript";

  // Audio mode --------------------------------------------------------
  const rowRefs = useRef<(HTMLLIElement | null)[]>([]);
  // Sync the ref-array length to the current segment count. The
  // callback ref on each row re-points its entry every render anyway,
  // so the truncation here only matters when the list shortens between
  // renders (e.g. an interview that briefly carried 4 segments, then
  // re-fetches with 3). We use an effect so we don't mutate refs
  // during render (which React's compiler / lint flags).
  useEffect(() => {
    const len = segments?.length ?? 0;
    if (rowRefs.current.length !== len) {
      rowRefs.current.length = len;
    }
  }, [segments]);

  // Transcript mode --------------------------------------------------
  // Stored as a `{start, end}` range into `transcriptText`. Cleared
  // after `HIGHLIGHT_DURATION_MS` so the highlight is transient.
  const [quoteRange, setQuoteRange] = useState<{
    start: number;
    end: number;
  } | null>(null);
  const quoteRef = useRef<HTMLSpanElement | null>(null);
  const quoteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (quoteTimer.current) clearTimeout(quoteTimer.current);
    },
    [],
  );
  // Re-center the highlight after the DOM has updated.
  useEffect(() => {
    if (quoteRange && quoteRef.current) {
      quoteRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [quoteRange]);

  useImperativeHandle(
    ref,
    () => ({
      scrollToIndex(index: number) {
        if (isTranscriptMode) return;
        const el = rowRefs.current[index];
        if (!el) return;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      },
      scrollToQuote(quote: string) {
        if (!isTranscriptMode) return;
        const text = transcriptText ?? "";
        if (text.length === 0) return;
        const range = findQuoteRange(text, quote);
        if (!range) {
          // Quote should have been pre-verified by the pipeline. If we
          // get here something has drifted — warn so the regression is
          // findable rather than silently broken.
          console.warn(
            "TranscriptPane.scrollToQuote: quote not found in transcript",
            { quote },
          );
          return;
        }
        setQuoteRange(range);
        if (quoteTimer.current) clearTimeout(quoteTimer.current);
        quoteTimer.current = setTimeout(() => {
          setQuoteRange(null);
        }, HIGHLIGHT_DURATION_MS);
      },
    }),
    [isTranscriptMode, transcriptText],
  );

  // Speakers come back as raw labels ("A", "B", …). Render them as
  // `Speaker A` for readability without losing the underlying letter.
  const speakerLabel = useMemo(
    () => (s: string) => (s.length === 1 ? `Speaker ${s}` : s),
    [],
  );

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader>
        <CardTitle>Transcript</CardTitle>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-hidden">
        <div
          className="h-full overflow-y-auto pr-2"
          data-testid="transcript-scroll"
        >
          {isTranscriptMode ? (
            <TranscriptModeContent
              transcriptText={transcriptText ?? null}
              loading={loading}
              status={status}
              quoteRange={quoteRange}
              quoteRef={quoteRef}
            />
          ) : segments && segments.length > 0 ? (
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

interface TranscriptModeContentProps {
  transcriptText: string | null;
  loading: boolean;
  status: Interview["status"];
  quoteRange: { start: number; end: number } | null;
  quoteRef: React.MutableRefObject<HTMLSpanElement | null>;
}

/** Preformatted transcript renderer used for `source_kind === "transcript"`.
 *  Renders the cue-by-cue VTT format inside a `<pre>` so blank lines /
 *  `[MM:SS] Speaker X` headers survive intact. */
function TranscriptModeContent({
  transcriptText,
  loading,
  status,
  quoteRange,
  quoteRef,
}: TranscriptModeContentProps) {
  if (transcriptText && transcriptText.length > 0) {
    if (quoteRange) {
      const before = transcriptText.slice(0, quoteRange.start);
      const match = transcriptText.slice(quoteRange.start, quoteRange.end);
      const after = transcriptText.slice(quoteRange.end);
      return (
        <pre
          data-testid="transcript-preformatted"
          className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed"
        >
          {before}
          <span
            ref={quoteRef}
            data-testid="transcript-quote-match"
            className="rounded-sm bg-yellow-200 dark:bg-yellow-500/20"
          >
            {match}
          </span>
          {after}
        </pre>
      );
    }
    return (
      <pre
        data-testid="transcript-preformatted"
        className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed"
      >
        {transcriptText}
      </pre>
    );
  }
  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <p className="text-sm text-muted-foreground">
      {status === "failed"
        ? "Transcript unavailable — see error in pain points panel."
        : "Transcript is not available yet."}
    </p>
  );
}
