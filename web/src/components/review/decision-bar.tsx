"use client";

/**
 * The decision bar — every action that moves this impact, in one place.
 *
 * The rule that shapes this component: it only ever offers moves the server's
 * state machine would accept. `capabilities.allowed_transitions` comes from
 * `api/services/workflow.ALLOWED_TRANSITIONS`, so a button that would 422 is
 * disabled with the reason showing, rather than offered and then refused.
 * Guessing here and apologising afterwards is how a reviewer stops trusting
 * the queue.
 *
 * Approve is deliberately the only primary action, and its helper text says
 * what approving does — writes the wording to Ripple's record, leaves the
 * document alone. `requires_human_decision` (a simulated change) removes it
 * entirely and says what to do instead.
 */

import { Check, LoaderCircle, Undo2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { STATUS_LABELS } from "@/lib/severity";
import type { ImpactCapabilities, ReviewStatus } from "@/lib/types";

/** The moves worth a button of their own; the rest live in the status menu. */
const QUICK_MOVES: ReviewStatus[] = ["in_review", "needs_analysis"];

export interface DecisionBarProps {
  status: ReviewStatus;
  capabilities: ImpactCapabilities;
  hasRecommendation: boolean;
  hasPatch: boolean;
  pending: string | null;
  note: string;
  onNoteChange: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onRevert: () => void;
  onTransition: (status: ReviewStatus) => void;
}

export function DecisionBar({
  status,
  capabilities,
  hasRecommendation,
  hasPatch,
  pending,
  note,
  onNoteChange,
  onApprove,
  onReject,
  onRevert,
  onTransition,
}: DecisionBarProps) {
  const busy = pending !== null;
  const allowed = new Set(capabilities.allowed_transitions);
  const canApprove = capabilities.approve_patch;

  // Say precisely why Approve is unavailable — "disabled for reasons unknown"
  // is the least useful thing a review screen can do.
  const approveBlockedReason = capabilities.accept_recommendation
    ? !hasRecommendation
      ? "Generate proposed wording before approving."
      : !allowed.has("resolved")
        ? `An impact that is ${STATUS_LABELS[status].toLowerCase()} has to be moved into review before it can be resolved.`
        : null
    : "This finding came from a simulation. Promote the simulation first — approving here would turn a hypothetical into a real record.";

  return (
    <section
      aria-label="Decision"
      className="sticky bottom-0 z-10 rounded-lg border bg-background/95 p-4 backdrop-blur supports-[backdrop-filter]:bg-background/80"
    >
      <label htmlFor="decision-note" className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Note for the record (optional)
      </label>
      <Textarea
        id="decision-note"
        className="mt-2 min-h-16 text-sm"
        placeholder="Why you are approving, rejecting or reassigning this."
        value={note}
        onChange={(event) => onNoteChange(event.target.value)}
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {hasPatch ? (
          <Button variant="outline" onClick={onRevert} disabled={busy}>
            {pending === "revert" ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Undo2 className="size-4" />
            )}
            Withdraw approved wording
          </Button>
        ) : (
          <Button onClick={onApprove} disabled={busy || !canApprove} title={approveBlockedReason ?? undefined}>
            {pending === "approve" ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            Approve wording
          </Button>
        )}

        {hasRecommendation && !hasPatch ? (
          <Button variant="outline" onClick={onReject} disabled={busy}>
            {pending === "reject" ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <X className="size-4" />
            )}
            Reject wording
          </Button>
        ) : null}

        {QUICK_MOVES.filter((move) => allowed.has(move)).map((move) => (
          <Button
            key={move}
            variant="ghost"
            onClick={() => onTransition(move)}
            disabled={busy}
          >
            {pending === move ? <LoaderCircle className="size-4 animate-spin" /> : null}
            Move to {STATUS_LABELS[move].toLowerCase()}
          </Button>
        ))}

        {allowed.has("dismissed") ? (
          <Button
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => onTransition("dismissed")}
            disabled={busy}
          >
            {pending === "dismissed" ? <LoaderCircle className="size-4 animate-spin" /> : null}
            Dismiss
          </Button>
        ) : null}
      </div>

      <p className="mt-2.5 text-xs text-muted-foreground">
        {hasPatch
          ? "Withdrawing removes the overlay and reopens this for review. Both acts stay in the record."
          : approveBlockedReason ??
            "Approving records the wording in Ripple and resolves this finding. Your document and the file on disk are not modified."}
      </p>
    </section>
  );
}
