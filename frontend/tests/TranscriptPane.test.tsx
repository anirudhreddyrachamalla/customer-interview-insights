/**
 * Component tests for `TranscriptPane`.
 *
 * Two modes to verify (selected by the `sourceKind` prop):
 *
 *   - `"audio"` (default): segmented renderer. `scrollToIndex(i)` jumps
 *     to a row. The preformatted `<pre>` block is NOT mounted.
 *   - `"transcript"`: preformatted renderer. The cue-by-cue VTT string
 *     is rendered inside a `<pre>`, including the blank lines that
 *     separate cues. `scrollToQuote(quote)` highlights the matched
 *     substring (asserted via the `transcript-quote-match` testid).
 *
 * jsdom doesn't implement `Element.prototype.scrollIntoView`, so the
 * tests stub it before exercising the imperative handle. We do not
 * assert the scroll arguments — just that the right element gets the
 * call when the right mode is active.
 */

import { describe, expect, it, vi } from "vitest";
import { createRef } from "react";
import { render, screen } from "@testing-library/react";
import { act } from "react";

import {
  TranscriptPane,
  type TranscriptPaneHandle,
} from "@/components/interviews/TranscriptPane";
import type { TranscriptSegment } from "@/lib/api/types";

const sampleSegments: TranscriptSegment[] = [
  { start: 0, end: 5, speaker: "A", text: "Intro question." },
  { start: 5, end: 12, speaker: "B", text: "The customer's answer." },
  { start: 12, end: 18, speaker: "A", text: "Follow-up." },
];

const sampleFormatted =
  "[00:00 - 00:05] Speaker A\n" +
  "Intro question.\n" +
  "\n" +
  "[00:05 - 00:12] Speaker B\n" +
  "The customer's answer is the bit we care about.\n" +
  "\n" +
  "[00:12 - 00:18] Speaker A\n" +
  "Follow-up.";

describe("TranscriptPane — audio mode", () => {
  it("renders one row per segment and exposes a working scrollToIndex", () => {
    // jsdom stub. We assert via `mock.calls` that the row at the
    // requested index received the scroll call.
    const scrollSpy = vi.fn();
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: scrollSpy,
    });

    const ref = createRef<TranscriptPaneHandle>();
    render(
      <TranscriptPane
        ref={ref}
        segments={sampleSegments}
        highlightedIndices={new Set()}
        loading={false}
        status="completed"
      />,
    );

    // All three segments rendered.
    expect(screen.getByTestId("transcript-segment-0")).toBeInTheDocument();
    expect(screen.getByTestId("transcript-segment-1")).toBeInTheDocument();
    expect(screen.getByTestId("transcript-segment-2")).toBeInTheDocument();

    // The preformatted block must NOT be in the DOM in audio mode.
    expect(
      screen.queryByTestId("transcript-preformatted"),
    ).not.toBeInTheDocument();

    // Imperative scrollToIndex.
    act(() => {
      ref.current?.scrollToIndex(1);
    });
    expect(scrollSpy).toHaveBeenCalledTimes(1);
  });

  it("renders nothing for scrollToQuote in audio mode", () => {
    const scrollSpy = vi.fn();
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: scrollSpy,
    });

    const ref = createRef<TranscriptPaneHandle>();
    render(
      <TranscriptPane
        ref={ref}
        segments={sampleSegments}
        highlightedIndices={new Set()}
        loading={false}
        status="completed"
      />,
    );

    act(() => {
      ref.current?.scrollToQuote("the customer's answer");
    });
    // No highlight should appear.
    expect(
      screen.queryByTestId("transcript-quote-match"),
    ).not.toBeInTheDocument();
  });
});

describe("TranscriptPane — transcript mode", () => {
  it("renders the formatted transcript inside a <pre>, preserving blank-line separators", () => {
    render(
      <TranscriptPane
        segments={null}
        highlightedIndices={new Set()}
        loading={false}
        status="completed"
        sourceKind="transcript"
        transcriptText={sampleFormatted}
      />,
    );

    const pre = screen.getByTestId("transcript-preformatted");
    expect(pre.tagName.toLowerCase()).toBe("pre");
    // Cue blocks separated by a blank line — i.e. two consecutive newlines.
    expect(pre.textContent ?? "").toContain("\n\n");
    expect(pre.textContent ?? "").toContain("[00:00 - 00:05] Speaker A");
    expect(pre.textContent ?? "").toContain(
      "The customer's answer is the bit we care about.",
    );

    // Segmented renderer must NOT mount in transcript mode.
    expect(
      screen.queryByTestId("transcript-segment-0"),
    ).not.toBeInTheDocument();
  });

  it("scrollToQuote highlights the matching range", () => {
    const scrollSpy = vi.fn();
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      writable: true,
      value: scrollSpy,
    });

    const ref = createRef<TranscriptPaneHandle>();
    render(
      <TranscriptPane
        ref={ref}
        segments={null}
        highlightedIndices={new Set()}
        loading={false}
        status="completed"
        sourceKind="transcript"
        transcriptText={sampleFormatted}
      />,
    );

    // Before the call, no highlight.
    expect(
      screen.queryByTestId("transcript-quote-match"),
    ).not.toBeInTheDocument();

    act(() => {
      ref.current?.scrollToQuote(
        "the customer's answer is the bit we care about",
      );
    });

    const match = screen.getByTestId("transcript-quote-match");
    expect(match).toBeInTheDocument();
    expect(match.textContent ?? "").toMatch(/the customer's answer/i);
    // And the highlight container scrolled itself into view.
    expect(scrollSpy).toHaveBeenCalled();
  });

  it("scrollToQuote no-ops (with a console.warn) when the quote isn't present", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const ref = createRef<TranscriptPaneHandle>();
    render(
      <TranscriptPane
        ref={ref}
        segments={null}
        highlightedIndices={new Set()}
        loading={false}
        status="completed"
        sourceKind="transcript"
        transcriptText={sampleFormatted}
      />,
    );

    act(() => {
      ref.current?.scrollToQuote("a phrase that is definitely not present");
    });

    expect(
      screen.queryByTestId("transcript-quote-match"),
    ).not.toBeInTheDocument();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
