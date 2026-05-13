/**
 * Unit tests for the `overlappingIndices` helper exported from
 * `InterviewDetail.tsx`.
 *
 * v1.2 collapses this helper down to a single path: real segment
 * timestamps. The v1.1 all-zero-timestamp fallback (used for `.txt`
 * uploads) is gone because `.txt` and `.srt` transcript support is
 * removed in v1.2 — only `.vtt`-sourced transcripts remain, and those
 * always carry real `[start, end]` cue times. Pain-point → transcript
 * navigation for transcript-source interviews now flows through
 * `TranscriptPane.scrollToQuote`, not this helper.
 */

import { describe, expect, it } from "vitest";

import { overlappingIndices } from "@/components/interviews/InterviewDetail";
import type { PainPoint, TranscriptSegment } from "@/lib/api/types";

function pp(overrides: Partial<PainPoint>): PainPoint {
  return {
    id: "pp-1",
    interview_id: "iv-1",
    text: "x",
    supporting_quote: "",
    timestamp_start_sec: 0,
    timestamp_end_sec: 0,
    severity: 3,
    type: "pain_point",
    created_at: "2026-05-01T10:00:00Z",
    ...overrides,
  };
}

describe("overlappingIndices", () => {
  it("returns empty when there are no segments", () => {
    expect(overlappingIndices(null, pp({}))).toEqual([]);
    expect(overlappingIndices([], pp({}))).toEqual([]);
  });

  it("returns every segment that overlaps the pain point's [start, end] window", () => {
    const segments: TranscriptSegment[] = [
      { start: 0, end: 5, speaker: "A", text: "intro" },
      { start: 5, end: 12, speaker: "B", text: "the bit we care about" },
      { start: 12, end: 18, speaker: "A", text: "trailing" },
      { start: 20, end: 30, speaker: "B", text: "later" },
    ];
    const result = overlappingIndices(
      segments,
      pp({ timestamp_start_sec: 6, timestamp_end_sec: 14 }),
    );
    expect(result).toEqual([1, 2]);
  });

  it("returns just the boundary-touching segments when the window pins to an edge", () => {
    const segments: TranscriptSegment[] = [
      { start: 0, end: 5, speaker: "A", text: "intro" },
      { start: 5, end: 12, speaker: "B", text: "answer" },
      { start: 12, end: 18, speaker: "A", text: "follow-up" },
    ];
    const result = overlappingIndices(
      segments,
      pp({ timestamp_start_sec: 5, timestamp_end_sec: 5 }),
    );
    // Both segments touch t=5 — keep both so the caller can highlight
    // the boundary cue and the one starting at it.
    expect(result).toEqual([0, 1]);
  });

  it("returns an empty list when no segment overlaps the pain point window", () => {
    const segments: TranscriptSegment[] = [
      { start: 0, end: 5, speaker: "A", text: "intro" },
      { start: 6, end: 10, speaker: "B", text: "first answer" },
    ];
    const result = overlappingIndices(
      segments,
      pp({ timestamp_start_sec: 20, timestamp_end_sec: 30 }),
    );
    expect(result).toEqual([]);
  });
});
