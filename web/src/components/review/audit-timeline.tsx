"use client";

/**
 * Who did what, when — the record PRD section 10.1 rule 4 requires.
 *
 * Two tables feed this. `impact_review_events` is the authoritative narrow
 * record of status moves; `audit_events` is the wider trail that also carries
 * the patch acts. The server merges them, and this renders them as one
 * sequence, because "approved" and "the patch that approval produced" are one
 * event to a reader and two rows to a database.
 *
 * Every entry names a person and a time. An event with neither is a defect,
 * not something to render as "system".
 */

import { STATUS_LABELS } from "@/lib/severity";
import type { AuditEvent, ReviewStatus } from "@/lib/types";

/** What each audited action reads as in a sentence. */
const ACTION_PHRASES: Record<string, string> = {
  "impact.update": "updated this review",
  "document_patch.applied": "approved wording, stored as an overlay",
  "document_patch.reverted": "withdrew the approved wording",
};

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function describe(event: AuditEvent): string {
  if (event.action === "impact.transition") {
    const detail = (event.detail ?? {}) as { previous_status?: ReviewStatus; new_status?: ReviewStatus };
    const from = detail.previous_status ? STATUS_LABELS[detail.previous_status] : null;
    const to = detail.new_status ? STATUS_LABELS[detail.new_status] : "a new status";
    return from ? `moved this from ${from.toLowerCase()} to ${to.toLowerCase()}` : `moved this to ${to.toLowerCase()}`;
  }
  return ACTION_PHRASES[event.action] ?? event.action.replaceAll(".", " ").replaceAll("_", " ");
}

function noteOf(event: AuditEvent): string | null {
  const detail = (event.detail ?? {}) as { note?: string | null };
  return detail.note?.trim() || null;
}

export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return (
      <section aria-labelledby="audit-trail" className="rounded-lg border">
        <header className="border-b px-4 py-3">
          <h2 id="audit-trail" className="text-sm font-medium">
            Record
          </h2>
        </header>
        <p className="px-4 py-6 text-sm text-muted-foreground">
          Nothing has happened to this finding yet beyond its detection.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="audit-trail" className="rounded-lg border">
      <header className="flex items-center justify-between border-b px-4 py-3">
        <h2 id="audit-trail" className="text-sm font-medium">
          Record
        </h2>
        <span className="text-xs tabular-nums text-muted-foreground">{events.length} entries</span>
      </header>
      <ol className="divide-y">
        {events.map((event) => {
          const note = noteOf(event);
          return (
            <li key={event.id} className="flex gap-3 px-4 py-3">
              <span
                aria-hidden
                className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/60"
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  <span className="font-medium">{event.actor_name ?? "An unnamed account"}</span>{" "}
                  {describe(event)}
                </p>
                <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">
                  {formatTime(event.created_at)}
                </p>
                {note ? (
                  <p className="mt-1.5 border-l-2 pl-2.5 text-xs leading-5 text-muted-foreground italic">
                    {note}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
