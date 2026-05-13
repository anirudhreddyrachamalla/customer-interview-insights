"use client";

/**
 * Read-only display of the meeting notes captured at upload time.
 *
 * Mounted in the left column of `InterviewDetail`, directly below
 * `DemographicsSummary`. Notes are free-form text the analyst typed
 * before/during the interview — they are NOT fed to Claude, so this is
 * purely a display surface for context the human reviewer wanted to
 * remember.
 *
 * Rendering rules:
 *   - Non-null, non-whitespace string → render in a `<p>` with
 *     `whitespace-pre-wrap` so newlines authored in the upload textarea
 *     survive the round-trip. Width is constrained by the column.
 *   - Null OR whitespace-only → render the muted "No notes added"
 *     empty-state line so the card never looks broken.
 */

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface MeetingNotesCardProps {
  meetingNotes: string | null;
}

export function MeetingNotesCard({ meetingNotes }: MeetingNotesCardProps) {
  const hasNotes =
    typeof meetingNotes === "string" && meetingNotes.trim().length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Meeting notes</CardTitle>
      </CardHeader>
      <CardContent>
        {hasNotes ? (
          <p className="whitespace-pre-wrap text-sm text-foreground">
            {meetingNotes}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">No notes added</p>
        )}
      </CardContent>
    </Card>
  );
}
