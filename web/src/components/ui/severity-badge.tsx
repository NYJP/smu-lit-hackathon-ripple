/**
 * The only place severity becomes a colour.
 *
 * Before this component every impact rendered `<Badge variant="destructive">`
 * regardless of level, in six different files, so medium and low were
 * indistinguishable from high. Import this instead of picking a badge variant.
 *
 * Colour is never the only carrier (PRD section 10.1 rule 10): each level also
 * gets a distinct glyph, so the scale survives greyscale printing and
 * colour-blind readers.
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";

import { SEVERITY_DESCRIPTIONS, SEVERITY_GLYPHS, SEVERITY_LABELS } from "@/lib/severity";
import type { Severity } from "@/lib/types";

const severityBadgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1.5 rounded-4xl border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      severity: {
        critical: "border-impact-critical/25 bg-impact-critical/10 text-impact-critical",
        high: "border-impact-high/25 bg-impact-high/10 text-impact-high",
        medium: "border-impact-medium/25 bg-impact-medium/10 text-impact-medium",
        low: "border-impact-low/25 bg-impact-low/10 text-impact-low",
        none: "border-border bg-muted text-muted-foreground",
      },
      emphasis: {
        // Tinted chip. The default: dense lists should not be a wall of colour.
        soft: "",
        // Filled. Reserve for the single most severe item on a screen.
        solid: "border-transparent text-background",
      },
    },
    compoundVariants: [
      { emphasis: "solid", severity: "critical", class: "bg-impact-critical" },
      { emphasis: "solid", severity: "high", class: "bg-impact-high" },
      { emphasis: "solid", severity: "medium", class: "bg-impact-medium" },
      { emphasis: "solid", severity: "low", class: "bg-impact-low" },
      { emphasis: "solid", severity: "none", class: "bg-muted-foreground" },
    ],
    defaultVariants: { severity: "none", emphasis: "soft" },
  },
);

export interface SeverityBadgeProps
  extends Omit<React.ComponentProps<"span">, "children">,
    Omit<VariantProps<typeof severityBadgeVariants>, "severity"> {
  severity: Severity;
  /** Append the word "impact", e.g. "High impact". */
  withNoun?: boolean;
  /** Hide the glyph. Only for places that already carry a shape signal. */
  hideGlyph?: boolean;
}

function SeverityBadge({
  severity,
  emphasis,
  withNoun = false,
  hideGlyph = false,
  className,
  ...props
}: SeverityBadgeProps) {
  // An endpoint that forgets to send `severity` must not render a blank pill —
  // fall back to `none` so the badge always says something legible.
  const level: Severity = severity && severity in SEVERITY_LABELS ? severity : "none";
  const label = SEVERITY_LABELS[level];
  return (
    <span
      data-slot="severity-badge"
      data-severity={level}
      title={SEVERITY_DESCRIPTIONS[level]}
      className={cn(severityBadgeVariants({ severity: level, emphasis }), className)}
      {...props}
    >
      {!hideGlyph && (
        <span aria-hidden className="text-[0.7em] leading-none">
          {SEVERITY_GLYPHS[level]}
        </span>
      )}
      {withNoun && level !== "none" ? `${label} impact` : label}
    </span>
  );
}

/**
 * A 4px vertical bar for the document reader's left severity rail, where a
 * badge per clause would overwhelm the text (PRD section 10.1 rule 1: the
 * document is the interface).
 */
function SeverityRail({
  severity,
  className,
  ...props
}: { severity: Severity } & React.ComponentProps<"span">) {
  return (
    <span
      aria-hidden
      data-severity={severity}
      className={cn(
        "block w-1 shrink-0 rounded-full",
        severity === "critical" && "bg-impact-critical",
        severity === "high" && "bg-impact-high",
        severity === "medium" && "bg-impact-medium",
        severity === "low" && "bg-impact-low",
        severity === "none" && "bg-border",
        className,
      )}
      {...props}
    />
  );
}

/** "2 critical · 1 high" — a compact count strip that omits empty levels. */
function SeverityCounts({
  counts,
  className,
  ...props
}: { counts: Partial<Record<Severity, number>> } & React.ComponentProps<"div">) {
  const entries = (["critical", "high", "medium", "low"] as const).filter(
    (level) => (counts[level] ?? 0) > 0,
  );
  if (entries.length === 0) {
    return (
      <div className={cn("text-xs text-muted-foreground", className)} {...props}>
        No affected passages
      </div>
    );
  }
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", className)} {...props}>
      {entries.map((level) => (
        <span key={level} className="inline-flex items-center gap-1.5 text-xs tabular-nums">
          <span
            aria-hidden
            className={cn(
              "size-2 rounded-full",
              level === "critical" && "bg-impact-critical",
              level === "high" && "bg-impact-high",
              level === "medium" && "bg-impact-medium",
              level === "low" && "bg-impact-low",
            )}
          />
          <span className="font-medium">{counts[level]}</span>
          <span className="text-muted-foreground">{SEVERITY_LABELS[level].toLowerCase()}</span>
        </span>
      ))}
    </div>
  );
}

export { SeverityBadge, SeverityCounts, SeverityRail, severityBadgeVariants };
