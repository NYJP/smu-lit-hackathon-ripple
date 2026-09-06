"use client";

/**
 * `/impacts/[id]` — the review screen (PRD section 10.3).
 *
 * The layout follows the order a reviewer actually thinks in: what the
 * regulator changed, then which of our words that lands on, then what we
 * propose to say instead, then the decision, then the record. The regulatory
 * source and the affected clause sit side by side because the judgement being
 * made is a comparison, and a screen that makes you scroll between the two
 * halves of a comparison is a screen that gets rubber-stamped.
 *
 * The backend for all of this already existed and had no page — GET/PATCH
 * /impacts/{id} returned a full review payload, capabilities and history
 * included, that nothing rendered.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CalendarClock, LoaderCircle, TriangleAlert } from "lucide-react";

import { AuditTimeline } from "@/components/review/audit-timeline";
import { ClauseEvidence } from "@/components/review/clause-evidence";
import { DecisionBar } from "@/components/review/decision-bar";
import { RedlineEditor } from "@/components/review/redline-editor";
import { RequirementDiff } from "@/components/review/requirement-diff";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SeverityBadge } from "@/components/ui/severity-badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SourceBadge, StatusBadge } from "@/components/ui/status-badge";
import { LoadingSkeleton, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import type { ImpactDetail, RecommendationDetail, ReviewStatus } from "@/lib/types";

const UNASSIGNED = "__unassigned__";

/** Days until a due date; negative once it has passed. */
function daysUntil(value: string): number | null {
  const due = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(due.getTime())) return null;
  const today = new Date();
  const utcToday = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((due.getTime() - utcToday) / 86_400_000);
}

function DueDateChip({ dueDate }: { dueDate: string }) {
  const remaining = daysUntil(dueDate);
  if (remaining === null) return null;
  const overdue = remaining < 0;
  const soon = remaining >= 0 && remaining <= 7;
  return (
    <span
      className={
        overdue
          ? "inline-flex w-fit items-center gap-1.5 rounded-4xl border border-impact-critical/25 bg-impact-critical/10 px-2 py-0.5 text-xs font-medium text-impact-critical"
          : soon
            ? "inline-flex w-fit items-center gap-1.5 rounded-4xl border border-status-attention/25 bg-status-attention/10 px-2 py-0.5 text-xs font-medium text-status-attention"
            : "inline-flex w-fit items-center gap-1.5 rounded-4xl border px-2 py-0.5 text-xs font-medium text-muted-foreground"
      }
    >
      <CalendarClock aria-hidden className="size-3" />
      {overdue
        ? `${Math.abs(remaining)} ${Math.abs(remaining) === 1 ? "day" : "days"} overdue`
        : remaining === 0
          ? "Due today"
          : `Due in ${remaining} ${remaining === 1 ? "day" : "days"}`}
    </span>
  );
}

export function ReviewPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { roster } = useSession();

  const [data, setData] = useState<ImpactDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const detail = await api.get<ImpactDetail>(`/impacts/${params.id}`, { signal });
        if (signal?.aborted) return;
        setData(detail);
        // The draft follows the server unless the reviewer is mid-edit; the
        // decision bar approves exactly the text on screen, so the two must
        // never silently disagree.
        setDraft(
          detail.patch?.patched_text ??
            detail.recommendation?.edited_text ??
            detail.recommendation?.suggested_text ??
            "",
        );
        setError(null);
      } catch (err) {
        if (signal?.aborted) return;
        setError(
          err instanceof ApiRequestError ? err.message : "Could not load this review.",
        );
      }
    },
    [params.id],
  );

  useEffect(() => {
    const controller = new AbortController();
    // Deferred like every other page here, so the fetch's first setState
    // lands after the render that scheduled it rather than cascading.
    queueMicrotask(() => void load(controller.signal));
    return () => controller.abort();
  }, [load]);

  const run = useCallback(
    async (key: string, action: () => Promise<unknown>) => {
      setPending(key);
      setActionError(null);
      try {
        await action();
        await load();
      } catch (err) {
        setActionError(
          err instanceof ApiRequestError ? err.message : "That action could not be completed.",
        );
      } finally {
        setPending(null);
      }
    },
    [load],
  );

  const generate = useCallback(async () => {
    setGenerating(true);
    setActionError(null);
    try {
      await api.post<{ recommendation: RecommendationDetail }>(
        `/impacts/${params.id}/recommendation`,
      );
      await load();
    } catch (err) {
      setActionError(
        err instanceof ApiRequestError
          ? err.message
          : "Proposed wording could not be generated.",
      );
    } finally {
      setGenerating(false);
    }
  }, [params.id, load]);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-5 py-8">
        <Link
          href="/impacts"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Review queue
        </Link>
        <p className="mt-5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      </div>
    );
  }

  if (!data) {
    return (
      <PageFrame><Surface><LoadingSkeleton rows={5} /></Surface></PageFrame>
    );
  }

  const { impact, capabilities, document, chunk } = data;
  const next = data.other_open_impacts[0] ?? null;

  return (
    <PageFrame>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/impacts"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Review queue
        </Link>
        {next ? (
          <Link
            href={`/impacts/${next.id}`}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            Next affected clause
            <span className="text-xs">
              ({data.other_open_impacts.length} more in this document)
            </span>
            <ArrowRight className="size-4" />
          </Link>
        ) : null}
      </div>

      <PageHeader className="mt-5" title={document.name} description={<>{impact.clause_label ?? chunk.section_path ?? `Clause ${chunk.ordinal + 1}`} · owned by {document.owner.display_name}</>} eyebrow={<div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={impact.severity} withNoun />
          <StatusBadge status={impact.review_status} label={impact.review_status_label} />
          <SourceBadge source={data.change.source} />
          {impact.due_date ? <DueDateChip dueDate={impact.due_date} /> : null}
        </div>} />

      {data.change.analysis_status === "failed" ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3">
          <p className="flex items-start gap-2 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" />
            Analysis of this regulatory change did not finish, so the findings below may be
            incomplete.
          </p>
          <Button
            variant="outline"
            size="sm"
            disabled={pending !== null}
            onClick={() =>
              run("retry", () => api.post(`/changes/${data.change.id}/analyse`))
            }
          >
            {pending === "retry" ? <LoaderCircle className="size-3.5 animate-spin" /> : null}
            Retry analysis
          </Button>
        </div>
      ) : null}

      {document.status === "failed" && document.error_message ? (
        <p className="mt-5 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {document.error_message}
        </p>
      ) : null}

      {actionError ? (
        <p className="mt-5 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {actionError}
        </p>
      ) : null}

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-2">
        <RequirementDiff
          change={data.change}
          regulation={data.regulation}
          previous={data.previous_requirement}
          proposed={data.new_requirement}
        />
        <ClauseEvidence
          impact={impact}
          chunk={chunk}
          dependency={data.dependency}
          document={document}
          contributor={data.contributor}
          patch={data.patch}
        />
      </div>

      <Surface aria-label="Assignment" className="mt-5 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="assignee"
              className="text-xs font-medium tracking-wide text-muted-foreground uppercase"
            >
              Assigned to
            </label>
            <Select
              value={impact.assigned_to ?? UNASSIGNED}
              onValueChange={(value) =>
                run("assign", () =>
                  api.patch(`/impacts/${params.id}`, {
                    assigned_to: value === UNASSIGNED ? null : value,
                  }),
                )
              }
            >
              <SelectTrigger id="assignee" className="mt-2 w-full">
                <SelectValue placeholder="Nobody yet" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNASSIGNED}>Nobody yet</SelectItem>
                {roster.map((person) => (
                  <SelectItem key={person.id} value={person.id}>
                    {person.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label
              htmlFor="due-date"
              className="text-xs font-medium tracking-wide text-muted-foreground uppercase"
            >
              Due date
            </label>
            <Input
              id="due-date"
              type="date"
              className="mt-2"
              defaultValue={impact.due_date?.slice(0, 10) ?? ""}
              onBlur={(event) => {
                const value = event.target.value;
                if (value === (impact.due_date?.slice(0, 10) ?? "")) return;
                void run("due", () =>
                  api.patch(`/impacts/${params.id}`, { due_date: value || null }),
                );
              }}
            />
          </div>
        </div>
      </Surface>

      <div className="mt-5">
        <RedlineEditor
          recommendation={data.recommendation}
          patch={data.patch}
          canGenerate={capabilities.generate_recommendation && capabilities.accept_recommendation}
          generating={generating}
          onGenerate={generate}
          draft={draft}
          onDraftChange={setDraft}
          error={null}
        />
      </div>

      <div className="mt-5">
        <DecisionBar
          status={impact.review_status}
          capabilities={capabilities}
          hasRecommendation={data.recommendation !== null}
          hasPatch={data.patch !== null}
          pending={pending}
          note={note}
          onNoteChange={setNote}
          onApprove={() =>
            void run("approve", async () => {
              await api.post(`/impacts/${params.id}/patch`, {
                text: draft,
                note: note.trim() || null,
              });
              setNote("");
            })
          }
          onReject={() =>
            void run("reject", async () => {
              if (!data.recommendation) return;
              await api.patch(`/recommendations/${data.recommendation.id}`, {
                status: "rejected",
                decision_note: note.trim() || null,
              });
              setNote("");
            })
          }
          onRevert={() =>
            void run("revert", async () => {
              await api.delete(`/impacts/${params.id}/patch`);
              setNote("");
            })
          }
          onTransition={(status: ReviewStatus) =>
            void run(status, async () => {
              await api.patch(`/impacts/${params.id}`, {
                review_status: status,
                note: note.trim() || null,
              });
              setNote("");
              if (status === "dismissed") router.push("/impacts");
            })
          }
        />
      </div>

      {data.other_open_impacts.length ? (
        <Surface aria-labelledby="sibling-impacts" className="mt-5">
          <header className="border-b px-4 py-3">
            <h2 id="sibling-impacts" className="text-sm font-medium">
              Still open in {document.name}
            </h2>
          </header>
          <ul className="divide-y">
            {data.other_open_impacts.map((sibling) => (
              <li key={sibling.id}>
                <Link
                  href={`/impacts/${sibling.id}`}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/40"
                >
                  <SeverityBadge severity={sibling.severity} />
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {sibling.clause_label}
                    {sibling.conflicting_span ? ` — “${sibling.conflicting_span}”` : ""}
                  </span>
                  <StatusBadge
                    status={sibling.review_status}
                    label={sibling.review_status_label}
                  />
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </Surface>
      ) : null}

      <div className="mt-5">
        <AuditTimeline events={data.audit_trail} />
      </div>
    </PageFrame>
  );
}
