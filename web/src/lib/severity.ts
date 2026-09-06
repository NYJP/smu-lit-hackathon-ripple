/**
 * Client mirror of api/services/severity.py and api/services/workflow.py.
 *
 * The server decides severity — this file never derives it, it only orders,
 * labels and describes what the server already sent. Keep SEVERITY_ORDER in
 * step with SEVERITY_ORDER in the Python module.
 *
 * Colour is never the only signal (PRD section 10.1 rule 10: every list and
 * the graph must print legibly in black and white), so each level also
 * carries a shape/glyph and each status carries a distinct word.
 */

import type { ReviewStatus, Severity } from "@/lib/types";

/** Ascending. Index into this rather than comparing severity strings. */
export const SEVERITY_ORDER: readonly Severity[] = ["none", "low", "medium", "high", "critical"];

export const SEVERITY_RANK: Record<Severity, number> = {
  none: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  none: "Not affected",
};

/**
 * The non-colour signal. Geometric, not decorative: a filled square reads as
 * heavier than a hollow circle in greyscale and at print resolution.
 */
export const SEVERITY_GLYPHS: Record<Severity, string> = {
  critical: "◆",
  high: "●",
  medium: "▲",
  low: "■",
  none: "○",
};

/** What each level actually means, in the register of PRD section 10.1 rule 5. */
export const SEVERITY_DESCRIPTIONS: Record<Severity, string> = {
  critical: "Appears to rely on a superseded rule that is already in force or commences within 30 days.",
  high: "States or relies on the superseded value, so the wording appears inconsistent.",
  medium: "Implements or depends on the rule without reproducing it; the approach may need review.",
  low: "Mentions the rule in passing; worth updating for accuracy.",
  none: "Checked against this change with no relevant effect found.",
};

export function severityRank(value: Severity | null | undefined): number {
  return value ? (SEVERITY_RANK[value] ?? 0) : 0;
}

export function maxSeverity(values: Array<Severity | null | undefined>): Severity {
  return values.reduce<Severity>(
    (best, value) => (severityRank(value) > severityRank(best) ? (value as Severity) : best),
    "none",
  );
}

/** Descending by severity — the order a reviewer should read in. */
export function bySeverityDesc<T>(pick: (item: T) => Severity | null | undefined) {
  return (a: T, b: T) => severityRank(pick(b)) - severityRank(pick(a));
}

export function severityCounts<T>(items: T[], pick: (item: T) => Severity | null | undefined) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0, none: 0 } as Record<Severity, number>;
  for (const item of items) {
    const value = pick(item);
    if (value) counts[value] += 1;
  }
  return counts;
}

// ------------------------------------------------------------------ status --

export const STATUS_LABELS: Record<ReviewStatus, string> = {
  detected: "Detected",
  awaiting_review: "Awaiting review",
  in_review: "In review",
  needs_analysis: "Needs more analysis",
  patch_proposed: "Proposed wording ready",
  awaiting_approval: "Awaiting approval",
  resolved: "Resolved",
  dismissed: "Dismissed",
  superseded: "Superseded",
};

/** Which token family a status paints in. Never a severity colour. */
export type StatusTone = "attention" | "progress" | "done" | "neutral";

export const STATUS_TONES: Record<ReviewStatus, StatusTone> = {
  detected: "attention",
  awaiting_review: "attention",
  in_review: "progress",
  needs_analysis: "attention",
  patch_proposed: "progress",
  awaiting_approval: "progress",
  resolved: "done",
  dismissed: "neutral",
  superseded: "neutral",
};

export const TERMINAL_STATUSES: readonly ReviewStatus[] = ["resolved", "dismissed", "superseded"];

export function isOpenStatus(status: ReviewStatus): boolean {
  return !TERMINAL_STATUSES.includes(status);
}

/**
 * The sentence a reviewer should read when severity is high but the evidence
 * is thin. PRD section 10.1 rule 6: confidence calibrates reading order, it is
 * never merged into the severity claim.
 */
export function confidenceLabel(confidence: number): string {
  if (confidence >= 0.9) return "Strong evidence";
  if (confidence >= 0.7) return "Good evidence";
  if (confidence >= 0.5) return "Moderate evidence";
  return "Weak evidence";
}

/**
 * A serious finding on thin evidence is something to *read next*, not a
 * confirmed breach. This is the phrase the UI uses instead.
 */
export function needsUrgentReview(severity: Severity, confidence: number): boolean {
  return severityRank(severity) >= SEVERITY_RANK.high && confidence < 0.7;
}
