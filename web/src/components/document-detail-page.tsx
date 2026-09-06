"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, BookOpen, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  SeverityBadge,
  SeverityCounts,
  SeverityRail,
} from "@/components/ui/severity-badge";
import {
  EmptyState,
  LoadingSkeleton,
  PageFrame,
  PageHeader,
  SectionHeader,
  Surface,
} from "@/components/ui/workspace";
import { api, apiUrl, ApiRequestError } from "@/lib/api";
import { maxSeverity, severityCounts } from "@/lib/severity";
import type { DocumentPatch, ReviewStatus, Severity } from "@/lib/types";

type Person = { id: string; display_name: string };
type Dependency = {
  lineage_id: string;
  public_ref: string;
  relationship_type: string;
  confidence: number;
  evidence_start: number | null;
  evidence_end: number | null;
};
type Impact = {
  id: string;
  document_chunk_id: string;
  impact_level: string;
  severity: Severity;
  review_status: ReviewStatus;
  review_status_label: string;
  confidence: number;
  reason: string;
  conflicting_start: number | null;
  conflicting_end: number | null;
  change_summary: string;
  clause_label: string;
  page_number: number | null;
  contributor: Person | null;
};
type Chunk = {
  id: string;
  ordinal: number;
  content: string;
  clause_label: string;
  page_number: number | null;
  chunk_type: string;
  severity: Severity;
  dependencies: Dependency[];
  impacts: Impact[];
  patches: DocumentPatch[];
};
type Detail = {
  document: {
    id: string;
    name: string;
    file_name: string;
    doc_type: string;
    mime_type: string;
    owner: Person;
    contributors: Person[];
    patch_count: number;
  };
  chunks: Chunk[];
  patches: DocumentPatch[];
};
type Focus = { chunkId: string; start: number | null; end: number | null };
const tint: Record<Severity, string> = {
  critical: "bg-impact-critical/5",
  high: "bg-impact-high/5",
  medium: "bg-impact-medium/5",
  low: "bg-impact-low/5",
  none: "",
};
const underline: Record<Severity, string> = {
  critical: "decoration-impact-critical",
  high: "decoration-impact-high",
  medium: "decoration-impact-medium",
  low: "decoration-impact-low",
  none: "decoration-muted-foreground",
};
function initialFocus(): Focus | null {
  if (typeof window === "undefined") return null;
  const q = new URLSearchParams(location.search),
    chunkId = q.get("chunk");
  return chunkId
    ? {
        chunkId,
        start: q.has("start") ? Number(q.get("start")) : null,
        end: q.has("end") ? Number(q.get("end")) : null,
      }
    : null;
}
function renderSpans(content: string, items: Impact[]) {
  const ranges = items
      .filter(
        (i) =>
          i.conflicting_start !== null &&
          i.conflicting_end !== null &&
          i.conflicting_start >= 0 &&
          i.conflicting_end! <= content.length,
      )
      .sort((a, b) => a.conflicting_start! - b.conflicting_start!),
    out: React.ReactNode[] = [];
  let cursor = 0;
  for (const item of ranges) {
    const start = Math.max(cursor, item.conflicting_start!),
      end = item.conflicting_end!;
    if (end <= start) continue;
    if (start > cursor) out.push(content.slice(cursor, start));
    out.push(
      <span
        data-affected-span
        key={item.id}
        className={`font-medium underline decoration-2 underline-offset-4 ${underline[item.severity]}`}
      >
        {content.slice(start, end)}
      </span>,
    );
    cursor = end;
  }
  if (cursor < content.length) out.push(content.slice(cursor));
  return out.length ? out : content;
}
function renderSources(content: string, deps: Dependency[]) {
  const ranges = deps
      .filter(
        (d) =>
          d.evidence_start !== null &&
          d.evidence_end !== null &&
          d.evidence_start >= 0 &&
          d.evidence_end! <= content.length,
      )
      .sort((a, b) => a.evidence_start! - b.evidence_start!),
    out: React.ReactNode[] = [];
  let cursor = 0;
  for (const dep of ranges) {
    if (dep.evidence_start! < cursor) continue;
    if (dep.evidence_start! > cursor)
      out.push(content.slice(cursor, dep.evidence_start!));
    out.push(
      <Link
        key={`${dep.lineage_id}-${dep.evidence_start}`}
        href={`/requirements/${dep.lineage_id}`}
        className="bg-primary/5 underline decoration-primary decoration-dotted underline-offset-2"
        title={`${dep.public_ref} · ${dep.relationship_type}`}
      >
        {content.slice(dep.evidence_start!, dep.evidence_end!)}
      </Link>,
    );
    cursor = dep.evidence_end!;
  }
  if (cursor < content.length) out.push(content.slice(cursor));
  return out.length ? out : content;
}
function renderOverlay(content: string, patches: DocumentPatch[]) {
  const applied = patches
      .filter((p) => p.status === "applied")
      .sort((a, b) => a.char_start - b.char_start),
    out: React.ReactNode[] = [];
  let cursor = 0;
  for (const patch of applied) {
    if (patch.char_start < cursor) continue;
    out.push(content.slice(cursor, patch.char_start));
    out.push(
      <span
        key={patch.id}
        className="border-b-2 border-status-done bg-status-done/5"
        title="Approved wording overlay"
      >
        {patch.patched_text}
      </span>,
    );
    cursor = patch.char_end;
  }
  out.push(content.slice(cursor));
  return applied.length ? out : content;
}

export function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Detail | null>(null),
    [impacts, setImpacts] = useState<Impact[]>([]),
    [error, setError] = useState(""),
    [focus, setFocus] = useState<Focus | null>(initialFocus),
    [onlyAffected, setOnlyAffected] = useState(false),
    [showSources, setShowSources] = useState(false);
  useEffect(() => {
    queueMicrotask(() =>
      Promise.all([
        api.get<Detail>(`/documents/${id}`),
        api.get<{ items: Impact[] }>(
          `/impacts?document_id=${id}&open_only=true&limit=200`,
        ),
      ])
        .then(([detail, result]) => {
          setData(detail);
          setImpacts(result.items.filter((i) => i.impact_level !== "none"));
        })
        .catch((err) =>
          setError(
            err instanceof ApiRequestError
              ? err.message
              : "Could not load this document.",
          ),
        ),
    );
  }, [id]);
  useEffect(() => {
    if (focus)
      requestAnimationFrame(() =>
        document
          .getElementById(`chunk-${focus.chunkId}`)
          ?.scrollIntoView({ behavior: "smooth", block: "center" }),
      );
  }, [focus]);
  const affected = useMemo(
    () =>
      data?.chunks.filter((c) =>
        impacts.some((i) => i.document_chunk_id === c.id),
      ) ?? [],
    [data, impacts],
  );
  if (error)
    return (
      <PageFrame>
        <Surface>
          <EmptyState title="Document unavailable" description={error} />
        </Surface>
      </PageFrame>
    );
  if (!data)
    return (
      <PageFrame>
        <Surface>
          <LoadingSkeleton rows={7} />
        </Surface>
      </PageFrame>
    );
  const shown = onlyAffected ? affected : data.chunks,
    focusedIndex = focus
      ? affected.findIndex((c) => c.id === focus.chunkId)
      : -1,
    navigate = (delta: -1 | 1) => {
      if (!affected.length) return;
      const chunk =
          affected[
            focusedIndex < 0
              ? 0
              : (focusedIndex + delta + affected.length) % affected.length
          ],
        impact = impacts.find((i) => i.document_chunk_id === chunk.id);
      setFocus({
        chunkId: chunk.id,
        start: impact?.conflicting_start ?? null,
        end: impact?.conflicting_end ?? null,
      });
    };
  const fileUrl = apiUrl(`/files/documents/${id}`),
    isPdf =
      data.document.mime_type.includes("pdf") ||
      data.document.file_name.endsWith(".pdf");
  return (
    <PageFrame>
      <Link
        href="/documents"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Documents
      </Link>
      <PageHeader
        eyebrow={`${data.document.doc_type.replaceAll("_", " ")} · Owned by ${data.document.owner.display_name}`}
        title={data.document.name}
        description={`${impacts.length} affected clauses · ${data.document.patch_count ?? 0} approved wording overlays`}
        actions={
          <Button asChild variant="outline">
            <a href={fileUrl}>
              <Download />
              Download original
            </a>
          </Button>
        }
      />
      <section>
        <SectionHeader
          title="Affected clauses"
          description="Severity and exact evidence spans in the source text."
        />
        <Surface className="mt-3 divide-y overflow-hidden">
          {impacts.length ? (
            impacts.map((item) => (
              <button
                key={item.id}
                className="flex w-full gap-3 p-4 text-left hover:bg-muted/40"
                onClick={() =>
                  setFocus({
                    chunkId: item.document_chunk_id,
                    start: item.conflicting_start,
                    end: item.conflicting_end,
                  })
                }
              >
                <SeverityRail severity={item.severity} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={item.severity} withNoun />
                    <span className="font-medium">{item.change_summary}</span>
                  </div>
                  <p className="mt-2 text-sm">
                    {item.clause_label} · {item.reason}
                  </p>
                </div>
              </button>
            ))
          ) : (
            <EmptyState
              title="No affected clauses"
              description="No open impact findings were found in this document."
            />
          )}
        </Surface>
      </section>
      {isPdf ? (
        <Surface className="overflow-hidden">
          <iframe
            title={data.document.name}
            src={`${fileUrl}?inline=true`}
            className="h-[70vh] w-full bg-muted/20"
          />
        </Surface>
      ) : null}
      <section>
        <SectionHeader
          title="Document clause rail"
          description="The four-pixel rail and restrained tint show severity; only the exact affected text is underlined."
          action={
            <div className="flex flex-wrap gap-2">
              <Button
                variant={onlyAffected ? "secondary" : "outline"}
                aria-pressed={onlyAffected}
                onClick={() => setOnlyAffected((v) => !v)}
              >
                Only affected clauses
              </Button>
              <Button
                variant="outline"
                onClick={() => navigate(-1)}
                disabled={!affected.length}
              >
                Previous affected
              </Button>
              <Button
                variant="outline"
                onClick={() => navigate(1)}
                disabled={!affected.length}
              >
                Next affected
              </Button>
              <Button
                variant={showSources ? "secondary" : "outline"}
                aria-pressed={showSources}
                onClick={() => setShowSources((v) => !v)}
              >
                <BookOpen />
                {showSources ? "Hide policy sources" : "Show policy sources"}
              </Button>
            </div>
          }
        />
        <SeverityCounts
          className="mt-3"
          counts={severityCounts(impacts, (i) => i.severity)}
        />
        <Surface className="mt-3 divide-y overflow-hidden">
          {shown.map((chunk) => {
            const items = impacts.filter(
                (i) => i.document_chunk_id === chunk.id,
              ),
              severity = maxSeverity(items.map((i) => i.severity));
            return (
              <article
                id={`chunk-${chunk.id}`}
                key={chunk.id}
                className={`flex scroll-mt-20 ${tint[severity]}`}
              >
                <SeverityRail severity={severity} className="rounded-none" />
                <div className="min-w-0 flex-1 p-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline">{chunk.chunk_type}</Badge>
                    <span className="font-medium text-foreground/80">{chunk.clause_label}</span>
                    {chunk.page_number ? (
                      <span>page {chunk.page_number}</span>
                    ) : null}
                    {items.length ? (
                      <SeverityBadge severity={severity} />
                    ) : null}
                    {chunk.patches.some((p) => p.status === "applied") ? (
                      <Badge variant="secondary">Approved overlay</Badge>
                    ) : null}
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                    {showSources
                      ? renderSources(chunk.content, chunk.dependencies)
                      : chunk.patches.some((p) => p.status === "applied")
                        ? renderOverlay(chunk.content, chunk.patches)
                        : renderSpans(chunk.content, items)}
                  </p>
                  {items.map((item) => (
                    <div
                      key={item.id}
                      className="mt-3 border-l-2 border-current bg-muted/40 p-3"
                    >
                      <div className="flex flex-wrap gap-2">
                        <SeverityBadge severity={item.severity} withNoun />
                        <span className="text-sm font-medium">
                          {item.change_summary}
                        </span>
                      </div>
                      <p className="mt-1 text-sm">{item.reason}</p>
                    </div>
                  ))}
                </div>
              </article>
            );
          })}
        </Surface>
      </section>
    </PageFrame>
  );
}
