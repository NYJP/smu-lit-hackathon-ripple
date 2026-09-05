"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, BookOpen, Download, LoaderCircle } from "lucide-react";
import { api, apiUrl, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Dependency = { lineage_id: string; public_ref: string; confidence: number; relationship_type: string; evidence_start: number | null; evidence_end: number | null };
type Person = { id: string; display_name: string };
type Contribution = { start: number; end: number; contributed_at: string; user: Person | null };
type Chunk = { id: string; ordinal: number; content: string; section_path: string | null; page_number: number | null; chunk_type: string; dependencies: Dependency[]; contributions: Contribution[] };
type DocumentDetail = { document: { id: string; name: string; file_name: string; doc_type: string; mime_type: string; status: string; page_count: number | null; owner: Person; contributors: Person[] }; chunks: Chunk[] };
type Focus = { chunkId: string; start: number | null; end: number | null };
type Impact = { id: string; regulatory_change_id: string; document_chunk_id: string; impact_level: string; confidence: number; reason: string; conflicting_start: number | null; conflicting_end: number | null; change_summary: string; section_path: string | null; page_number: number | null; contributor: Person | null };
type HighlightRange = { start: number | null; end: number | null; contributor?: Person | null };

function focusFromLocation(): Focus | null {
  if (typeof window === "undefined") return null;
  const query = new URLSearchParams(window.location.search);
  const chunkId = query.get("chunk");
  if (!chunkId) return null;
  const start = query.get("start");
  const end = query.get("end");
  return { chunkId, start: start === null ? null : Number(start), end: end === null ? null : Number(end) };
}

function highlighted(content: string, ranges: HighlightRange[]) {
  if (!ranges.length) return content;
  const valid = ranges
    .filter((range): range is { start: number; end: number; contributor?: Person | null } => range.start !== null && range.end !== null && range.start >= 0 && range.end > range.start && range.end <= content.length)
    .sort((left, right) => left.start - right.start);
  if (!valid.length) {
    return <mark className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content}</mark>;
  }
  const rendered = [];
  let cursor = 0;
  for (const range of valid) {
    const start = Math.max(cursor, range.start);
    if (range.end <= start) continue;
    if (start > cursor) rendered.push(content.slice(cursor, start));
    rendered.push(<span key={`${start}-${range.end}`} className="group/author relative inline">
      <mark className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content.slice(start, range.end)}</mark>
      {range.contributor ? <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 hidden w-max max-w-56 -translate-x-1/2 rounded-md bg-popover px-3 py-2 text-xs text-popover-foreground shadow-lg ring-1 ring-foreground/10 group-hover/author:block">Written by <span className="font-medium">{range.contributor.display_name}</span></span> : null}
    </span>);
    cursor = range.end;
  }
  if (cursor < content.length) rendered.push(content.slice(cursor));
  return <>{rendered}</>;
}

function policySources(content: string, dependencies: Dependency[]) {
  const sources = dependencies
    .filter((dependency): dependency is Dependency & { evidence_start: number; evidence_end: number } => dependency.evidence_start !== null && dependency.evidence_end !== null && dependency.evidence_start >= 0 && dependency.evidence_end > dependency.evidence_start && dependency.evidence_end <= content.length)
    .sort((left, right) => left.evidence_start - right.evidence_start);
  if (!sources.length) return content;
  const rendered = [];
  let cursor = 0;
  for (const source of sources) {
    if (source.evidence_start < cursor) continue;
    if (source.evidence_start > cursor) rendered.push(content.slice(cursor, source.evidence_start));
    rendered.push(<span key={`${source.lineage_id}-${source.evidence_start}`} className="group/source relative inline">
      <Link href={`/requirements/${source.lineage_id}`} className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <mark className="cursor-pointer rounded-sm bg-sky-200 px-0.5 text-foreground underline decoration-sky-600 decoration-dotted underline-offset-2 dark:bg-sky-500/35">{content.slice(source.evidence_start, source.evidence_end)}</mark>
        <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-64 -translate-x-1/2 rounded-md bg-popover p-3 text-left text-xs text-popover-foreground shadow-lg ring-1 ring-foreground/10 group-hover/source:block group-focus-within/source:block"><span className="block font-medium">{source.public_ref}</span><span className="mt-1 block capitalize text-muted-foreground">{source.relationship_type} dependency · {Math.round(source.confidence * 100)}% confidence</span><span className="mt-2 block text-primary">Click to open requirement</span></span>
      </Link>
    </span>);
    cursor = source.evidence_end;
  }
  if (cursor < content.length) rendered.push(content.slice(cursor));
  return <>{rendered}</>;
}

export function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<DocumentDetail | null>(null);
  const [impacts, setImpacts] = useState<Impact[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(focusFromLocation);
  const [showSources, setShowSources] = useState(false);
  useEffect(() => {
    Promise.all([
      api.get<DocumentDetail>(`/documents/${params.id}`),
      api.get<{ items: Impact[] }>(`/impacts?document_id=${params.id}&review_status=open&limit=200`),
    ]).then(([document, result]) => {
      setData(document);
      setImpacts(result.items.filter((impact) => impact.impact_level !== "none"));
    }).catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this document."));
  }, [params.id]);
  useEffect(() => {
    if (!data || !focus) return;
    window.requestAnimationFrame(() => document.getElementById(`chunk-${focus.chunkId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [data, focus]);
  if (error) return <div className="mx-auto max-w-6xl px-5 py-8"><p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="mx-auto max-w-6xl px-5 py-16 text-center text-muted-foreground"><LoaderCircle className="mx-auto animate-spin" /></div>;
  const fileUrl = apiUrl(`/files/documents/${data.document.id}`);
  const isPdf = data.document.mime_type.toLowerCase().includes("pdf") || data.document.file_name.toLowerCase().endsWith(".pdf");
  const focusedChunk = focus ? data.chunks.find((chunk) => chunk.id === focus.chunkId) : null;
  const focusedImpact = focus ? impacts.find((impact) => impact.document_chunk_id === focus.chunkId && (focus.start === null || impact.conflicting_start === focus.start)) : null;
  const focusStart = focus?.start;
  const focusedContribution = focusedChunk && focusStart !== null && focusStart !== undefined
    ? focusedChunk.contributions.find((item) => item.start < (focus?.end ?? focusStart + 1) && item.end > focusStart)
    : undefined;
  const focusedContributor = focusedImpact?.contributor ?? focusedContribution?.user ?? null;
  const pdfPage = focusedChunk?.page_number ? `#page=${focusedChunk.page_number}` : "";
  const rangesFor = (chunkId: string) => focus?.chunkId === chunkId
    ? [{ start: focus.start, end: focus.end, contributor: focusedContributor }]
    : impacts.filter((impact) => impact.document_chunk_id === chunkId).map((impact) => ({ start: impact.conflicting_start, end: impact.conflicting_end, contributor: impact.contributor }));
  const renderChunk = (chunk: Chunk) => showSources ? policySources(chunk.content, chunk.dependencies) : highlighted(chunk.content, rangesFor(chunk.id));
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <Link href="/documents" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Documents</Link>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">{data.document.doc_type.replaceAll("_", " ")} · Owned by {data.document.owner.display_name}</p><h1 className="text-2xl font-semibold tracking-tight">{data.document.name}</h1><div className="mt-3 flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">Contributors</span>{data.document.contributors.map((person) => <Badge key={person.id} variant="secondary">{person.display_name}</Badge>)}</div></div><Button asChild variant="outline"><a href={fileUrl}><Download />Download original</a></Button></div>
    <section className="mt-7">
      <div className="flex items-center justify-between"><h2 className="font-medium">Issues in this document</h2><Badge variant={impacts.length ? "destructive" : "outline"}>{impacts.length} {impacts.length === 1 ? "issue" : "issues"}</Badge></div>
      <div className="mt-3 divide-y rounded-lg border">
        {impacts.length ? impacts.map((impact) => <button key={impact.id} type="button" onClick={() => setFocus({ chunkId: impact.document_chunk_id, start: impact.conflicting_start, end: impact.conflicting_end })} className="flex w-full gap-4 p-4 text-left transition-colors hover:bg-muted/40">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{impact.change_summary}</p><div className="flex items-center gap-2"><Badge variant="destructive" className="capitalize">{impact.impact_level} impact</Badge><span className="text-xs text-muted-foreground">{Math.round(impact.confidence * 100)}%</span></div></div><p className="mt-2 text-sm leading-6">{impact.reason}</p><p className="mt-2 text-xs text-muted-foreground">Affected sentence written by {impact.contributor?.display_name ?? data.document.owner.display_name} · {impact.section_path ?? "Affected passage"}{impact.page_number ? ` · page ${impact.page_number}` : ""} · Click to locate</p></div>
        </button>) : <p className="p-6 text-center text-sm text-muted-foreground">No open issues were found in this document.</p>}
      </div>
    </section>
    <div className="mt-7 overflow-hidden rounded-lg border">{isPdf ? <iframe title={data.document.name} src={`${fileUrl}?inline=true${pdfPage}`} className="h-[70vh] w-full bg-muted/20" /> : <div className="max-h-[70vh] overflow-y-auto bg-muted/10 p-8"><div className="mx-auto max-w-3xl rounded-md bg-background p-8 shadow-sm">{data.chunks.map(chunk => <div key={`preview-${chunk.id}`} className="mb-5 last:mb-0">{chunk.chunk_type === "heading" ? <h2 className="font-serif text-lg font-semibold">{renderChunk(chunk)}</h2> : <p className="whitespace-pre-wrap font-serif text-sm leading-7">{renderChunk(chunk)}</p>}</div>)}</div></div>}</div>
    {focusedChunk ? <div className="mt-4 rounded-lg border border-yellow-300 bg-yellow-50 p-4 text-sm leading-6 dark:border-yellow-700 dark:bg-yellow-950/30"><p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Affected passage{focusedChunk.page_number ? ` · page ${focusedChunk.page_number}` : ""}{focusedContributor ? ` · Written by ${focusedContributor.display_name}` : ""}</p><p className="whitespace-pre-wrap">{highlighted(focusedChunk.content, [{ start: focus?.start ?? null, end: focus?.end ?? null, contributor: focusedContributor }])}</p></div> : null}
    <section className="mt-8"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-medium">Document text</h2><span className="text-sm text-muted-foreground">{showSources ? "Policy-linked clauses are highlighted in blue" : "Affected text is highlighted in yellow; hover it to see the author"}</span></div><Button type="button" variant={showSources ? "secondary" : "outline"} aria-pressed={showSources} onClick={() => setShowSources((current) => !current)}><BookOpen />{showSources ? "Hide policy sources" : "Show policy sources"}</Button></div><div className="mt-3 divide-y rounded-lg border">{data.chunks.map(chunk => { const chunkImpacts = impacts.filter((impact) => impact.document_chunk_id === chunk.id); const chunkContributors = Array.from(new Map(chunk.contributions.filter((item) => item.user).map((item) => [item.user!.id, item.user!])).values()); return <article id={`chunk-${chunk.id}`} key={chunk.id} className={chunkImpacts.length || focus?.chunkId === chunk.id ? "bg-yellow-50/70 p-4 ring-1 ring-inset ring-yellow-300 dark:bg-yellow-950/20 dark:ring-yellow-700" : "p-4"}><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="outline">{chunk.chunk_type}</Badge>{chunk.section_path ? <span>{chunk.section_path}</span> : null}{chunk.page_number ? <span>page {chunk.page_number}</span> : null}{chunkContributors.length ? <span>Written by {chunkContributors.map((person) => person.display_name).join(", ")}</span> : null}{chunkImpacts.length ? <Badge variant="destructive">{chunkImpacts.length} {chunkImpacts.length === 1 ? "issue" : "issues"}</Badge> : null}</div><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{renderChunk(chunk)}</p>{chunkImpacts.map((impact) => <div key={impact.id} className="mt-3 rounded-md border border-destructive/20 bg-destructive/5 p-3"><p className="text-sm font-medium text-destructive">{impact.change_summary}</p><p className="mt-1 text-sm leading-5">{impact.reason}</p><p className="mt-2 text-xs text-muted-foreground">Affected sentence written by {impact.contributor?.display_name ?? data.document.owner.display_name}</p></div>)}{chunk.dependencies.length ? <div className="mt-3 flex flex-wrap gap-2">{chunk.dependencies.map(dep => <Badge key={dep.lineage_id} variant="secondary">{dep.public_ref} · {dep.relationship_type}</Badge>)}</div> : null}</article>; })}</div></section>
  </div>;
}
