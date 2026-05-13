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

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PAIN_POINT_TYPE_LABEL } from "@/lib/options";
import { cn, formatTimestamp } from "@/lib/utils";
import type { InterviewStatus, PainPoint, PainPointType } from "@/lib/api/types";

export interface PainPointsPanelProps {
  painPoints: PainPoint[];
  /** Used only to decide whether an empty list means "no pain points
   *  were extracted" (completed) or "still processing — show skeletons"
   *  (anything else). */
  status?: InterviewStatus;
  onClickPainPoint?: (painPoint: PainPoint) => void;
  emptyMessage?: string;
  /** When set, the panel only renders pain points of this type. Used by
   *  the v1.2 interview-detail layout to drive the three single-type
   *  columns (`pain_point` / `workaround` / `suggestion`). When unset,
   *  the panel renders every type (v1.1 behaviour). */
  type?: PainPointType;
  /** When true, the per-card classification badge is hidden. The v1.2
   *  detail page sets this on the single-type columns because the column
   *  header already communicates the type. */
  hideTypeBadge?: boolean;
  /** When set, the header reads `<label> · <count>`. Used by the
   *  detail-page columns to display the per-type count chip. */
  count?: number;
  /** Header label override. Defaults to "Pain points" for the all-types
   *  mode; the v1.2 detail page passes "Pain points" / "Workarounds" /
   *  "Suggestions" depending on the filter. */
  title?: string;
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
  type,
  hideTypeBadge,
  count,
  title,
}: PainPointsPanelProps) {
  const filtered = type ? painPoints.filter((pp) => pp.type === type) : painPoints;
  const sorted = sortPainPoints(filtered);
  const headerLabel = title ?? "Pain points";

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader>
        <CardTitle className="flex items-baseline gap-2">
          <span>{headerLabel}</span>
          {typeof count === "number" ? (
            <span
              data-testid="pain-points-count"
              className="text-xs font-normal text-muted-foreground"
            >
              · {count}
            </span>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 overflow-y-auto">
        {sorted.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {sorted.map((pp) => (
              <PainPointCard
                key={pp.id}
                painPoint={pp}
                onClick={onClickPainPoint}
                hideTypeBadge={hideTypeBadge}
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
  hideTypeBadge?: boolean;
}

function PainPointCard({ painPoint, onClick, hideTypeBadge }: PainPointCardProps) {
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
      {hideTypeBadge ? null : <PainPointTypeBadge type={painPoint.type} />}
      <p className="text-sm font-medium leading-snug text-foreground">
        {painPoint.text}
      </p>
      <blockquote className="border-l-2 border-border pl-3 text-xs italic leading-relaxed text-muted-foreground">
        “{painPoint.supporting_quote}”
      </blockquote>
    </li>
  );
}

/** Renders the classification badge under the timestamp row. The default
 *  `pain_point` type intentionally produces nothing — we don't want to
 *  add badge noise to the common case (SPEC_v1.1 §1 UI). */
function PainPointTypeBadge({ type }: { type: PainPointType | undefined }) {
  if (!type || type === "pain_point") return null;
  const label = PAIN_POINT_TYPE_LABEL[type] ?? type;
  const variant = type === "workaround" ? "outline" : "destructive";
  return (
    <div>
      <Badge
        variant={variant}
        data-pain-point-type={type}
        data-testid="pain-point-type-badge"
      >
        {label}
      </Badge>
    </div>
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
