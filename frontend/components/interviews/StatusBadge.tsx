/**
 * Visual status indicator for an interview's processing pipeline.
 *
 * Used in two places (so far):
 * - the interview list rows on `/projects/{id}` (task #7)
 * - the interview detail header on `/interviews/{id}` (task #8)
 *
 * Intentionally only depends on the `status` string, not on the full
 * `Interview` shape — so we can ship + test this before the interview
 * resource exists in the backend.
 */

import { Badge } from "@/components/ui/badge";
import type { InterviewStatus } from "@/lib/api/types";

type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "destructive"
  | "ghost"
  | "link";

interface StatusConfig {
  label: string;
  variant: BadgeVariant;
  /** Extra classes for variants that need to look distinct beyond the
   *  built-in palette (e.g. greenish "completed"). */
  className?: string;
}

const STATUS_CONFIG: Record<InterviewStatus, StatusConfig> = {
  uploaded: { label: "Uploaded", variant: "secondary" },
  transcribing: { label: "Transcribing…", variant: "outline" },
  analyzing: { label: "Analyzing…", variant: "outline" },
  completed: {
    label: "Completed",
    variant: "default",
    className:
      "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-50",
  },
  failed: { label: "Failed", variant: "destructive" },
};

export interface StatusBadgeProps {
  status: InterviewStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status];
  return (
    <Badge
      variant={config.variant}
      className={
        [config.className, className].filter(Boolean).join(" ") || undefined
      }
      aria-label={`Status: ${config.label}`}
      data-status={status}
    >
      {config.label}
    </Badge>
  );
}
