/**
 * Workflow status, kept visually distinct from severity.
 *
 * Status answers "where is this in the queue"; severity answers "how bad could
 * it be". They must never share a colour family or the two collapse into one
 * ambiguous signal — so status paints in the --status-* tokens and severity in
 * the --impact-* tokens, and neither borrows the other.
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";

import { STATUS_LABELS, STATUS_TONES } from "@/lib/severity";
import type { ChangeSource, ReviewStatus } from "@/lib/types";

const statusBadgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1.5 rounded-4xl border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        attention: "border-status-attention/25 bg-status-attention/10 text-status-attention",
        progress: "border-status-progress/25 bg-status-progress/10 text-status-progress",
        done: "border-status-done/25 bg-status-done/10 text-status-done",
        neutral: "border-border bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface StatusBadgeProps
  extends Omit<React.ComponentProps<"span">, "children">,
    VariantProps<typeof statusBadgeVariants> {
  status: ReviewStatus;
  /** Server-supplied label wins when present, so the two never disagree. */
  label?: string;
}

function StatusBadge({ status, label, tone, className, ...props }: StatusBadgeProps) {
  return (
    <span
      data-slot="status-badge"
      data-status={status}
      className={cn(statusBadgeVariants({ tone: tone ?? STATUS_TONES[status] }), className)}
      {...props}
    >
      {label ?? STATUS_LABELS[status]}
    </span>
  );
}

/**
 * The amber "Simulated" chip PRD section 10.4 requires on every list, card and
 * detail header whose change came from a simulation. A lawyer must never look
 * at a screen and be unsure whether the rule actually changed — so this is
 * purple, shares no token with any severity, and says the word outright.
 */
function SimulatedBadge({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="simulated-badge"
      title="Hypothetical. Nothing in your guidelines or documents has changed."
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1.5 rounded-4xl border border-sim/30 bg-sim/10 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-sim",
        className,
      )}
      {...props}
    >
      <span aria-hidden className="text-[0.7em] leading-none">
        ◇
      </span>
      Simulated
    </span>
  );
}

/** Renders the simulated chip only when the change actually is one. */
function SourceBadge({ source, className }: { source: ChangeSource; className?: string }) {
  if (source !== "simulation") return null;
  return <SimulatedBadge className={className} />;
}

export { StatusBadge, SimulatedBadge, SourceBadge, statusBadgeVariants };
