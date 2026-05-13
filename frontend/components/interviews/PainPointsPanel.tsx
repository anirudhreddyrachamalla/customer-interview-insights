"use client";

/**
 * Right-hand column on the interview detail page. Renders the list of
 * pain points extracted by the LLM, sorted by severity (highest first),
 * with a click-to-highlight handler that scrolls the transcript pane to
 * the matching segment(s).
 *
 * Defensive sorting: the backend already orders by
 * `severity DESC, created_at ASC`, but we sort here too so a
 * misbehaving server doesn't reorder the panel under the user's
 * scroll. Stable sort with the `created_at` tiebreaker keeps adjacent
 * pain points consistent across re-fetches.
 *
 * Card semantics: each pain-point card is a focusable `role="button"`
 * so keyboard users can navigate and trigger the highlight via Enter
 * or Space. The card surface fires `onClickPainPoint(p)` once per
 * activation.
 */

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatTimestamp } from "@/lib/utils";
import type { InterviewStatus, PainPoint } from "@/lib/api/types";

export interface PainPointsPanelProps {
  painPoints: PainPoint[];
  /** Used only to decide whether an empty list means "no pain points
   *  were extracted" (completed) or "still processing — show skeletons"
   *  (anything else). */
  status?: InterviewStatus;
  onClickPainPoint?: (painPoint: PainPoint) => void;
  emptyMessage?: string;
}

/** Stable sort by severity DESC, then created_at ASC. */
function sortPainPoints(painPoints: readonly PainPoint[]): PainPoint[] {
  return [...painPoints].sort((a, b) => {
    if (a.severity !== b.severity) return b.severity - a.severity;
    return a.created_at.localeCompare(b.created_at);
  });
}

export function PainPointsPanel({
  painPoints,
  status,
  onClickPainPoint,
  emptyMessage,
}: PainPointsPanelProps) {
  const sorted = sortPainPoints(painPoints);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Pain points</CardTitle>
      </CardHeader>
      <CardContent>
        {sorted.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {sorted.map((pp) => (
              <PainPointCard
                key={pp.id}
                painPoint={pp}
                onClick={onClickPainPoint}
              />
            ))}
          </ul>
        ) : status === "completed" ? (
          <p className="text-sm text-muted-foreground">
            {emptyMessage ?? "No pain points were extracted."}
          </p>
        ) : status === "failed" ? (
          <p className="text-sm text-muted-foreground">
            {emptyMessage ??
              "Pain point extraction did not complete. See the error above."}
          </p>
        ) : (
          // Still processing — render skeleton placeholders so the user
          // sees the panel will eventually populate.
          <div className="flex flex-col gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="flex flex-col gap-2 rounded-md border border-border p-3"
              >
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface PainPointCardProps {
  painPoint: PainPoint;
  onClick?: (painPoint: PainPoint) => void;
}

function PainPointCard({ painPoint, onClick }: PainPointCardProps) {
  const interactive = Boolean(onClick);

  function activate() {
    if (onClick) onClick(painPoint);
  }

  return (
    <li
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={
        interactive
          ? `Pain point: ${painPoint.text}. Severity ${painPoint.severity} of 5. Click to jump to transcript.`
          : undefined
      }
      onClick={interactive ? activate : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                activate();
              }
            }
          : undefined
      }
      className={cn(
        "flex flex-col gap-2 rounded-md border border-border bg-card p-3 text-left",
        interactive &&
          "cursor-pointer transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      )}
      data-testid={`pain-point-${painPoint.id}`}
    >
      <div className="flex items-center justify-between gap-2">
        <SeverityDots severity={painPoint.severity} />
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {formatTimestamp(painPoint.timestamp_start_sec)} –{" "}
          {formatTimestamp(painPoint.timestamp_end_sec)}
        </span>
      </div>
      <p className="text-sm font-medium leading-snug text-foreground">
        {painPoint.text}
      </p>
      <blockquote className="border-l-2 border-border pl-3 text-xs italic leading-relaxed text-muted-foreground">
        “{painPoint.supporting_quote}”
      </blockquote>
    </li>
  );
}

interface SeverityDotsProps {
  severity: 1 | 2 | 3 | 4 | 5;
}

function SeverityDots({ severity }: SeverityDotsProps) {
  return (
    <div
      className="flex items-center gap-0.5"
      role="img"
      aria-label={`Severity ${severity} of 5`}
      data-testid="severity-dots"
      data-severity={severity}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={cn(
            "block size-2 rounded-full",
            i <= severity
              ? "bg-destructive"
              : "border border-muted-foreground/40 bg-transparent",
          )}
          aria-hidden
        />
      ))}
    </div>
  );
}
