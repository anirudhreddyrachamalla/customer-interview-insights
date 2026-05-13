/**
 * Utilities for the transcript pane on the interview-detail page.
 *
 * The single export here is `findQuoteRange`, a pure helper that locates
 * a substring inside a larger transcript using the same
 * "collapse whitespace + lowercase" normalisation the backend pipeline
 * uses to verify supporting quotes (`backend/app/services/pipeline.py`'s
 * `_collapse`).
 *
 * Normalisation has to be reversible: we need to highlight the
 * unnormalised slice of the original transcript, not the collapsed one.
 * The implementation builds a positional map alongside the normalised
 * string so we can translate a normalised [start, end) range back into
 * the original character offsets without ambiguity.
 */

/** Result of a quote lookup, expressed as character offsets into the
 *  original (unnormalised) haystack. */
export interface QuoteRange {
  /** Inclusive start index in the original haystack. */
  start: number;
  /** Exclusive end index in the original haystack. */
  end: number;
}

/**
 * Find the first occurrence of `needle` inside `haystack`, ignoring
 * case and treating any run of whitespace (including newlines) as a
 * single space — same rules the backend uses to verify supporting
 * quotes against `transcript_text`.
 *
 * Returns the matching character range in the **unnormalised**
 * `haystack` so callers can highlight the exact source slice. Returns
 * `null` when no match exists.
 */
export function findQuoteRange(
  haystack: string,
  needle: string,
): QuoteRange | null {
  const trimmedNeedle = needle.trim();
  if (trimmedNeedle.length === 0) return null;

  const haystackNorm = normaliseWithMap(haystack);
  const needleNorm = collapse(needle);
  if (needleNorm.length === 0) return null;

  const hitNorm = haystackNorm.text.indexOf(needleNorm);
  if (hitNorm === -1) return null;

  // Map the normalised [hitNorm, hitNorm + needleNorm.length) back to
  // original offsets. The map stores, for each normalised character,
  // the original index it came from. The match's end is the original
  // index *just after* the last matched normalised character.
  const start = haystackNorm.map[hitNorm];
  const lastNorm = hitNorm + needleNorm.length - 1;
  const lastOriginal = haystackNorm.map[lastNorm];
  return { start, end: lastOriginal + 1 };
}

/** Collapse whitespace runs to a single space + lowercase. Mirrors the
 *  backend's `_collapse` so quote matching agrees byte-for-byte. */
function collapse(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

interface NormalisedWithMap {
  /** Normalised text (collapsed + lowercased). */
  text: string;
  /** For each character in `text`, the index in the original input it
   *  came from. `map.length === text.length`. */
  map: number[];
}

/**
 * Normalise `s` like `collapse` does, but also record where each
 * normalised character originated in the input. This lets callers
 * translate a normalised match range back to original-text offsets.
 *
 * The mapping rules:
 *   - A run of one or more whitespace characters between non-whitespace
 *     becomes a single space; that space's `map` entry is the original
 *     index of the FIRST whitespace character in the run.
 *   - Non-whitespace characters map to their own index.
 *   - Leading whitespace is dropped (no entry in `map`).
 *   - Trailing whitespace is dropped (no entry in `map`).
 */
function normaliseWithMap(s: string): NormalisedWithMap {
  const out: string[] = [];
  const map: number[] = [];
  let i = 0;
  // Skip leading whitespace.
  while (i < s.length && isWhitespace(s[i])) i += 1;

  let pendingWsStart = -1;
  while (i < s.length) {
    const ch = s[i];
    if (isWhitespace(ch)) {
      if (pendingWsStart === -1) pendingWsStart = i;
      i += 1;
      continue;
    }
    if (pendingWsStart !== -1) {
      out.push(" ");
      map.push(pendingWsStart);
      pendingWsStart = -1;
    }
    out.push(ch.toLowerCase());
    map.push(i);
    i += 1;
  }
  // Any trailing whitespace is dropped — matches `String.prototype.trim`.

  return { text: out.join(""), map };
}

function isWhitespace(ch: string): boolean {
  return /\s/.test(ch);
}
