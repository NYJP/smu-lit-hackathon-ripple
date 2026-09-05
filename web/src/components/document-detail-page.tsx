"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Download, LoaderCircle } from "lucide-react";
import { api, apiUrl, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Dependency = { lineage_id: string; public_ref: string; confidence: number; relationship_type: string; evidence_start: number | null; evidence_end: number | null };
type Chunk = { id: string; ordinal: number; content: string; section_path: string | null; page_number: number | null; chunk_type: string; dependencies: Dependency[] };
type DocumentDetail = { document: { id: string; name: string; file_name: string; doc_type: string; mime_type: string; status: string; page_count: number | null; owner: { display_name: string } }; chunks: Chunk[] };
type Focus = { chunkId: string; start: number | null; end: number | null };

function highlighted(content: string, active: boolean, start: number | null, end: number | null) {
  if (!active) return content;
  if (start === null || end === null || start < 0 || end <= start || end > content.length) {
    return <mark className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content}</mark>;
  }
  return <>{content.slice(0, start)}<mark className="rounded-sm bg-yellow-200 px-0.5 text-foreground dark:bg-yellow-500/40">{content.slice(start, end)}</mark>{content.slice(end)}</>;
}

export function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  useEffect(() => { api.get<DocumentDetail>(`/documents/${params.id}`).then(setData).catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this document.")); }, [params.id]);
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const chunkId = query.get("chunk");
    if (!chunkId) { setFocus(null); return; }
    const start = query.get("start");
    const end = query.get("end");
    setFocus({ chunkId, start: start === null ? null : Number(start), end: end === null ? null : Number(end) });
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
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <Link href="/documents" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Documents</Link>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">{data.document.doc_type.replaceAll("_", " ")} · {data.document.owner.display_name}</p><h1 className="text-2xl font-semibold tracking-tight">{data.document.name}</h1></div><Button asChild variant="outline"><a href={fileUrl}><Download />Download original</a></Button></div>
    <div className="mt-7 overflow-hidden rounded-lg border">{isPdf ? <iframe title={data.document.name} src={`${fileUrl}?inline=true${pdfPage}`} className="h-[70vh] w-full bg-muted/20" /> : <div className="max-h-[70vh] overflow-y-auto bg-muted/10 p-8"><div className="mx-auto max-w-3xl rounded-md bg-background p-8 shadow-sm">{data.chunks.map(chunk => <div key={`preview-${chunk.id}`} className="mb-5 last:mb-0">{chunk.chunk_type === "heading" ? <h2 className="font-serif text-lg font-semibold">{highlighted(chunk.content, focus?.chunkId === chunk.id, focus?.start ?? null, focus?.end ?? null)}</h2> : <p className="whitespace-pre-wrap font-serif text-sm leading-7">{highlighted(chunk.content, focus?.chunkId === chunk.id, focus?.start ?? null, focus?.end ?? null)}</p>}</div>)}</div></div>}</div>
    {focusedChunk ? <div className="mt-4 rounded-lg border border-yellow-300 bg-yellow-50 p-4 text-sm leading-6 dark:border-yellow-700 dark:bg-yellow-950/30"><p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Affected passage{focusedChunk.page_number ? ` · page ${focusedChunk.page_number}` : ""}</p><p className="whitespace-pre-wrap">{highlighted(focusedChunk.content, true, focus?.start ?? null, focus?.end ?? null)}</p></div> : null}
    <section className="mt-8"><div className="flex items-center justify-between"><h2 className="font-medium">Extracted contents</h2><span className="text-sm text-muted-foreground">{data.chunks.length} chunks</span></div><div className="mt-3 divide-y rounded-lg border">{data.chunks.map(chunk => <article id={`chunk-${chunk.id}`} key={chunk.id} className={focus?.chunkId === chunk.id ? "bg-yellow-50/70 p-4 ring-1 ring-inset ring-yellow-300 dark:bg-yellow-950/20 dark:ring-yellow-700" : "p-4"}><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="outline">{chunk.chunk_type}</Badge>{chunk.section_path ? <span>{chunk.section_path}</span> : null}{chunk.page_number ? <span>page {chunk.page_number}</span> : null}</div><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{highlighted(chunk.content, focus?.chunkId === chunk.id, focus?.start ?? null, focus?.end ?? null)}</p>{chunk.dependencies.length ? <div className="mt-3 flex flex-wrap gap-2">{chunk.dependencies.map(dep => <Badge key={dep.lineage_id} variant="secondary">{dep.public_ref} · {dep.relationship_type}</Badge>)}</div> : null}</article>)}</div></section>
  </div>;
}
