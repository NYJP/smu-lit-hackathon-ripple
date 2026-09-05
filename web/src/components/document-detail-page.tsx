"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, Download, LoaderCircle } from "lucide-react";
import { api, apiUrl, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Dependency = { lineage_id: string; public_ref: string; confidence: number; relationship_type: string; evidence_start: number | null; evidence_end: number | null };
type Chunk = { id: string; ordinal: number; content: string; section_path: string | null; page_number: number | null; chunk_type: string; dependencies: Dependency[] };
type DocumentDetail = { document: { id: string; name: string; file_name: string; doc_type: string; mime_type: string; status: string; page_count: number | null; owner: { display_name: string } }; chunks: Chunk[] };
type Focus = { chunkId: string; start: number | null; end: number | null };
type Impact = { id: string; regulatory_change_id: string; document_chunk_id: string; impact_level: string; confidence: number; reason: string; conflicting_start: number | null; conflicting_end: number | null; change_summary: string; section_path: string | null; page_number: number | null };
type HighlightRange = { start: number | null; end: number | null };

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
    .filter((range): range is { start: number; end: number } => range.start !== null && range.end !== null && range.start >= 0 && range.end > range.start && range.end <= content.length)
    .sort((left, right) => left.start - right.start);
  if (!valid.length) {
    return <mark className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content}</mark>;
  }
  const merged = valid.reduce<Array<{ start: number; end: number }>>((result, range) => {
    const previous = result.at(-1);
    if (previous && range.start <= previous.end) previous.end = Math.max(previous.end, range.end);
    else result.push({ ...range });
    return result;
  }, []);
  const rendered = [];
  let cursor = 0;
  for (const range of merged) {
    if (range.start > cursor) rendered.push(content.slice(cursor, range.start));
    rendered.push(<mark key={`${range.start}-${range.end}`} className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content.slice(range.start, range.end)}</mark>);
    cursor = range.end;
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
  const pdfPage = focusedChunk?.page_number ? `#page=${focusedChunk.page_number}` : "";
  const rangesFor = (chunkId: string) => focus?.chunkId === chunkId
    ? [{ start: focus.start, end: focus.end }]
    : impacts.filter((impact) => impact.document_chunk_id === chunkId).map((impact) => ({ start: impact.conflicting_start, end: impact.conflicting_end }));
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <Link href="/documents" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Documents</Link>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">{data.document.doc_type.replaceAll("_", " ")} · {data.document.owner.display_name}</p><h1 className="text-2xl font-semibold tracking-tight">{data.document.name}</h1></div><Button asChild variant="outline"><a href={fileUrl}><Download />Download original</a></Button></div>
    <section className="mt-7">
      <div className="flex items-center justify-between"><h2 className="font-medium">Issues in this document</h2><Badge variant={impacts.length ? "destructive" : "outline"}>{impacts.length} {impacts.length === 1 ? "issue" : "issues"}</Badge></div>
      <div className="mt-3 divide-y rounded-lg border">
        {impacts.length ? impacts.map((impact) => <button key={impact.id} type="button" onClick={() => setFocus({ chunkId: impact.document_chunk_id, start: impact.conflicting_start, end: impact.conflicting_end })} className="flex w-full gap-4 p-4 text-left transition-colors hover:bg-muted/40">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium">{impact.change_summary}</p><div className="flex items-center gap-2"><Badge variant="destructive" className="capitalize">{impact.impact_level} impact</Badge><span className="text-xs text-muted-foreground">{Math.round(impact.confidence * 100)}%</span></div></div><p className="mt-2 text-sm leading-6">{impact.reason}</p><p className="mt-2 text-xs text-muted-foreground">{impact.section_path ?? "Affected passage"}{impact.page_number ? ` · page ${impact.page_number}` : ""} · Click to locate</p></div>
        </button>) : <p className="p-6 text-center text-sm text-muted-foreground">No open issues were found in this document.</p>}
      </div>
    </section>
    <div className="mt-7 overflow-hidden rounded-lg border">{isPdf ? <iframe title={data.document.name} src={`${fileUrl}?inline=true${pdfPage}`} className="h-[70vh] w-full bg-muted/20" /> : <div className="max-h-[70vh] overflow-y-auto bg-muted/10 p-8"><div className="mx-auto max-w-3xl rounded-md bg-background p-8 shadow-sm">{data.chunks.map(chunk => <div key={`preview-${chunk.id}`} className="mb-5 last:mb-0">{chunk.chunk_type === "heading" ? <h2 className="font-serif text-lg font-semibold">{highlighted(chunk.content, rangesFor(chunk.id))}</h2> : <p className="whitespace-pre-wrap font-serif text-sm leading-7">{highlighted(chunk.content, rangesFor(chunk.id))}</p>}</div>)}</div></div>}</div>
    {focusedChunk ? <div className="mt-4 rounded-lg border border-yellow-300 bg-yellow-50 p-4 text-sm leading-6 dark:border-yellow-700 dark:bg-yellow-950/30"><p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Affected passage{focusedChunk.page_number ? ` · page ${focusedChunk.page_number}` : ""}</p><p className="whitespace-pre-wrap">{highlighted(focusedChunk.content, [{ start: focus?.start ?? null, end: focus?.end ?? null }])}</p></div> : null}
    <section className="mt-8"><div className="flex items-center justify-between"><h2 className="font-medium">Document text</h2><span className="text-sm text-muted-foreground">Affected text is highlighted</span></div><div className="mt-3 divide-y rounded-lg border">{data.chunks.map(chunk => { const chunkImpacts = impacts.filter((impact) => impact.document_chunk_id === chunk.id); return <article id={`chunk-${chunk.id}`} key={chunk.id} className={chunkImpacts.length || focus?.chunkId === chunk.id ? "bg-yellow-50/70 p-4 ring-1 ring-inset ring-yellow-300 dark:bg-yellow-950/20 dark:ring-yellow-700" : "p-4"}><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="outline">{chunk.chunk_type}</Badge>{chunk.section_path ? <span>{chunk.section_path}</span> : null}{chunk.page_number ? <span>page {chunk.page_number}</span> : null}{chunkImpacts.length ? <Badge variant="destructive">{chunkImpacts.length} {chunkImpacts.length === 1 ? "issue" : "issues"}</Badge> : null}</div><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{highlighted(chunk.content, rangesFor(chunk.id))}</p>{chunkImpacts.map((impact) => <div key={impact.id} className="mt-3 rounded-md border border-destructive/20 bg-destructive/5 p-3"><p className="text-sm font-medium text-destructive">{impact.change_summary}</p><p className="mt-1 text-sm leading-5">{impact.reason}</p></div>)}{chunk.dependencies.length ? <div className="mt-3 flex flex-wrap gap-2">{chunk.dependencies.map(dep => <Badge key={dep.lineage_id} variant="secondary">{dep.public_ref} · {dep.relationship_type}</Badge>)}</div> : null}</article>; })}</div></section>
  </div>;
}
