"use client";

/**
 * `/impacts` — the review queue.
 *
 * Grouped by document rather than listed flat, because the unit of work is a
 * document: a reviewer who opens the retention policy wants to settle every
 * clause in it while the regulation is still in their head, not meet it again
 * four rows later. PRD section 10.1 rule 9 — table density, tabular numerals,
 * enough rows visible to compare.
 *
 * `none` findings are excluded by default. They are the record that a
 * dependency *was* checked and found unaffected (PRD section 8.3), which
 * matters for coverage but is not work.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, CalendarClock, FileText } from "lucide-react";

import { ConfidenceMeter } from "@/components/ui/confidence-meter";
import { SeverityBadge, SeverityCounts, SeverityRail } from "@/components/ui/severity-badge";
import { SourceBadge, StatusBadge } from "@/components/ui/status-badge";
import { EmptyState, LoadingSkeleton, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { severityRank, STATUS_LABELS } from "@/lib/severity";
import type { ImpactListItem, ReviewStatus, Severity } from "@/lib/types";

type Filter = "open" | "mine" | "all";

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "any", label: "Any status" },
  ...(
    [
      "detected",
      "awaiting_review",
      "in_review",
      "needs_analysis",
      "patch_proposed",
      "awaiting_approval",
      "resolved",
      "dismissed",
    ] as ReviewStatus[]
  ).map((status) => ({ value: status, label: STATUS_LABELS[status] })),
];

function daysUntil(value: string | null): number | null {
  if (!value) return null;
  const due = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(due.getTime())) return null;
  const today = new Date();
  return Math.round(
    (due.getTime() - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / 86_400_000,
  );
}

function DueChip({ dueDate }: { dueDate: string }) {
  const remaining = daysUntil(dueDate);
  if (remaining === null) return null;
  const overdue = remaining < 0;
  return (
    <span
      className={
        overdue
          ? "inline-flex items-center gap-1 text-xs font-medium tabular-nums text-impact-critical"
          : "inline-flex items-center gap-1 text-xs tabular-nums text-muted-foreground"
      }
    >
      <CalendarClock aria-hidden className="size-3" />
      {overdue ? `${Math.abs(remaining)}d overdue` : `due in ${remaining}d`}
    </span>
  );
}

interface DocumentGroup {
  documentId: string;
  documentName: string;
  ownerName: string;
  items: ImpactListItem[];
  worst: Severity;
  soonest: number | null;
}

export function ImpactsQueuePage() {
  const { user } = useSession();
  const [filter, setFilter] = useState<Filter>("open");
  const [status, setStatus] = useState("any");
  const [items, setItems] = useState<ImpactListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);
      const query = new URLSearchParams({ limit: "200" });
      if (filter !== "all" && status === "any") query.set("open_only", "true");
      if (status !== "any") query.set("review_status", status);
      try {
        const result = await api.get<{ items: ImpactListItem[] }>(
          `/impacts?${query.toString()}`,
          { signal },
        );
        if (signal.aborted) return;
        setItems(result.items.filter((item) => item.impact_level !== "none"));
        setError(null);
      } catch (err) {
        if (signal.aborted) return;
        setError(
          err instanceof ApiRequestError ? err.message : "Could not load the review queue.",
        );
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [filter, status],
  );

  useEffect(() => {
    const controller = new AbortController();
    // Deferred like every other page here, so the fetch's first setState
    // lands after the render that scheduled it rather than cascading.
    queueMicrotask(() => void load(controller.signal));
    return () => controller.abort();
  }, [load]);

  const visible = useMemo(
    () =>
      filter === "mine" && user
        ? items.filter((item) => item.assigned_to === user.id || item.owner_id === user.id)
        : items,
    [items, filter, user],
  );

  // Documents first, worst-and-soonest first inside each. Severity leads
  // because it is what the reviewer triages on; the due date breaks ties,
  // since two critical findings differ by how much time is left.
  const groups = useMemo<DocumentGroup[]>(() => {
    const byDocument = new Map<string, DocumentGroup>();
    for (const item of visible) {
      const existing = byDocument.get(item.document_id);
      const due = daysUntil(item.due_date);
      if (existing) {
        existing.items.push(item);
        if (severityRank(item.severity) > severityRank(existing.worst)) existing.worst = item.severity;
        if (due !== null && (existing.soonest === null || due < existing.soonest)) existing.soonest = due;
      } else {
        byDocument.set(item.document_id, {
          documentId: item.document_id,
          documentName: item.document_name,
          ownerName: item.owner_name,
          items: [item],
          worst: item.severity,
          soonest: due,
        });
      }
    }
    const groupList = [...byDocument.values()];
    for (const group of groupList) {
      group.items.sort(
        (a, b) =>
          severityRank(b.severity) - severityRank(a.severity) ||
          (daysUntil(a.due_date) ?? 9_999) - (daysUntil(b.due_date) ?? 9_999),
      );
    }
    groupList.sort(
      (a, b) =>
        severityRank(b.worst) - severityRank(a.worst) ||
        (a.soonest ?? 9_999) - (b.soonest ?? 9_999) ||
        b.items.length - a.items.length,
    );
    return groupList;
  }, [visible]);

  const counts = useMemo(() => {
    const bucket = { critical: 0, high: 0, medium: 0, low: 0, none: 0 } as Record<Severity, number>;
    for (const item of visible) bucket[item.severity] += 1;
    return bucket;
  }, [visible]);

  return (
    <PageFrame>
      <PageHeader title="Review queue" description="Passages that appear to rely on a rule that has changed. Nothing here has altered your documents — reviewing decides what, if anything, should." />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs value={filter} onValueChange={(value) => setFilter(value as Filter)}>
          <TabsList>
            <TabsTrigger value="open">Still open</TabsTrigger>
            <TabsTrigger value="mine">Mine</TabsTrigger>
            <TabsTrigger value="all">Everything</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-3">
          <SeverityCounts counts={counts} />
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-52" aria-label="Filter by status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {error ? (
        <p className="mt-6 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : loading ? (
        <Surface><LoadingSkeleton rows={5} /></Surface>
      ) : groups.length === 0 ? (
        <Surface>
        <EmptyState title="Nothing is waiting for you here" description={<>
          <span>
            {filter === "mine"
              ? "No open findings are assigned to you or sit on a document you own."
              : filter === "open"
                ? "No open findings. Ripple keeps checking your documents as regulations change."
                : "No findings have been recorded yet."}
          </span></>} action={
          <Link
            href="/documents"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            See the documents being monitored
            <ArrowRight className="size-3.5" />
          </Link>} />
        </Surface>
      ) : (
        <div className="space-y-5">
          {groups.map((group) => (
            <Surface key={group.documentId}>
              <header className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
                <div className="flex min-w-0 items-center gap-2.5">
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <Link
                    href={`/documents/${group.documentId}`}
                    className="truncate font-medium hover:underline"
                  >
                    {group.documentName}
                  </Link>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {group.ownerName}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {group.items.length} {group.items.length === 1 ? "clause" : "clauses"}
                  </span>
                  <SeverityBadge severity={group.worst} />
                </div>
              </header>
              <ul className="divide-y">
                {group.items.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={`/impacts/${item.id}`}
                      className="group flex items-stretch gap-3 px-4 py-3 transition-colors hover:bg-muted/40"
                    >
                      <SeverityRail severity={item.severity} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <p className="min-w-0 text-sm font-medium group-hover:underline">
                            {item.clause_label}
                            {item.page_number ? (
                              <span className="ml-1.5 text-xs font-normal tabular-nums text-muted-foreground">
                                p. {item.page_number}
                              </span>
                            ) : null}
                          </p>
                          <div className="flex shrink-0 flex-wrap items-center gap-2">
                            {item.due_date ? <DueChip dueDate={item.due_date} /> : null}
                            <SourceBadge source={item.source} />
                            <SeverityBadge severity={item.severity} />
                            <StatusBadge
                              status={item.review_status}
                              label={item.review_status_label}
                            />
                          </div>
                        </div>
                        {item.clause_excerpt ? (
                          <p className="mt-1.5 line-clamp-2 text-sm leading-6">
                            “{item.clause_excerpt}”
                          </p>
                        ) : null}
                        <p className="mt-1 line-clamp-2 text-sm leading-6 text-muted-foreground">
                          {item.reason}
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-3">
                          <ConfidenceMeter
                            compact
                            confidence={item.confidence}
                            severity={item.severity}
                          />
                          <span className="text-xs text-muted-foreground">
                            {item.change_summary}
                          </span>
                        </div>
                      </div>
                      <ArrowRight className="mt-1 size-4 shrink-0 self-start text-muted-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Surface>
          ))}
        </div>
      )}
    </PageFrame>
  );
}
