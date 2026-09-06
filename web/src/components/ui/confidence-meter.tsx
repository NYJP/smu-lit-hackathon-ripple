/**
 * Confidence, shown as its own dimension.
 *
 * PRD section 10.4: every confidence figure appears as a whole-number
 * percentage next to its level, never alone. Section 10.1 rule 6: it is
 * context for reading order, never a score to rank or gamify on — so there is
 * no colour scale here and no corpus-wide accuracy number anywhere.
 *
 * The one judgement this component does make is calling out a serious finding
 * on thin evidence as "urgent review" rather than letting it read as a
 * confirmed breach.
 */

import * as React from "react";
import { cn } from "cn";

import { confidenceLabel, needsUrgentReview } from "@/lib/severity";
import type { Severity } from "@/lib/types";

export interface ConfidenceMeterProps extends React.ComponentProps<"div"> {
  /** 0..1, as stored. */
  confidence: number;
  /** Supply to surface the low-confidence-but-severe caveat. */
  severity?: Severity;
  /** Hide the four-segment bar and show the figure alone. */
  compact?: boolean;
}

function ConfidenceMeter({
  confidence,
  severity,
  compact = false,
  className,
  ...props
}: ConfidenceMeterProps) {
  const percent = Math.round(confidence * 100);
  const filled = Math.max(1, Math.ceil(confidence * 4));
  const urgent = severity ? needsUrgentReview(severity, confidence) : false;

  return (
    <div
      data-slot="confidence-meter"
      className={cn("inline-flex items-center gap-2 text-xs", className)}
      {...props}
    >
      {!compact && (
        <span aria-hidden className="inline-flex items-center gap-0.5">
          {[0, 1, 2, 3].map((index) => (
            <span
              key={index}
              className={cn(
                "h-2.5 w-1 rounded-[1px]",
                index < filled ? "bg-foreground/70" : "bg-border",
              )}
            />
          ))}
        </span>
      )}
      <span className="tabular-nums font-medium">{percent}%</span>
      <span className="text-muted-foreground">{confidenceLabel(confidence)}</span>
      {urgent && (
        <span
          className="rounded-4xl border border-status-attention/25 bg-status-attention/10 px-1.5 py-0.5 font-medium text-status-attention"
          title="Serious if correct, but the evidence is thin. Read this next — it is not a confirmed finding."
        >
          Urgent review
        </span>
      )}
    </div>
  );
}

export { ConfidenceMeter };
