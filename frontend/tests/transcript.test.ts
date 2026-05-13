/**
 * Unit tests for the `findQuoteRange` helper.
 *
 * The function is the pure search routine `TranscriptPane.scrollToQuote`
 * leans on for transcript-source interviews: locate a supporting quote
 * inside the cue-by-cue formatted `transcript_text`, tolerate the same
 * whitespace + casing slop the backend tolerates when verifying quotes.
 *
 * Coverage targets (per SPEC_v1.2 §Tests-frontend):
 *   - Exact-match hit returns the right byte range.
 *   - Whitespace differences (collapsed runs, newlines, leading/trailing
 *     pad) still find the source span.
 *   - Case differences match.
 *   - A genuinely-absent needle returns `null`.
 */

import { describe, expect, it } from "vitest";

import { findQuoteRange } from "@/lib/transcript";

describe("findQuoteRange", () => {
  it("returns the exact character range for an exact substring match", () => {
    const haystack = "Hello world, this is a transcript.";
    const range = findQuoteRange(haystack, "this is a transcript");
    expect(range).not.toBeNull();
    expect(haystack.slice(range!.start, range!.end)).toBe(
      "this is a transcript",
    );
  });

  it("matches across collapsed whitespace (newlines, runs of spaces)", () => {
    const haystack =
      "[00:00 - 00:05] Speaker A\nThe customer's words on this cue,\n" +
      "as written in the VTT.\n\n" +
      "[00:06 - 00:09] Speaker B\nThe interviewer's reply.";
    // Needle uses a single space where the source has a newline.
    const range = findQuoteRange(
      haystack,
      "customer's words on this cue, as written in the VTT.",
    );
    expect(range).not.toBeNull();
    // The matched original slice should start at "customer's" and end
    // right after "VTT." — i.e. it spans the newline.
    const slice = haystack.slice(range!.start, range!.end);
    expect(slice.startsWith("customer's")).toBe(true);
    expect(slice.endsWith("VTT.")).toBe(true);
    // Sanity: collapsing the slice yields the (lowercased) needle.
    expect(slice.replace(/\s+/g, " ").trim().toLowerCase()).toBe(
      "customer's words on this cue, as written in the vtt.",
    );
  });

  it("matches case-insensitively", () => {
    const haystack = "Honestly, the WORST part is the manual CSV exports.";
    const range = findQuoteRange(haystack, "the worst part IS the manual csv");
    expect(range).not.toBeNull();
    expect(haystack.slice(range!.start, range!.end)).toBe(
      "the WORST part is the manual CSV",
    );
  });

  it("returns null when the needle is not present in the haystack", () => {
    const haystack = "Anything you can tell me about onboarding?";
    expect(findQuoteRange(haystack, "totally absent phrase")).toBeNull();
  });

  it("returns null for an empty or whitespace-only needle", () => {
    expect(findQuoteRange("Anything you like", "")).toBeNull();
    expect(findQuoteRange("Anything you like", "   \n\t  ")).toBeNull();
  });
});
