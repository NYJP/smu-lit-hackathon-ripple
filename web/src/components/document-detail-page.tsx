"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Download, LoaderCircle } from "lucide-react";
import { api, apiUrl, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Dependency = { lineage_id: string; public_ref: string; confidence: number; relationship_type: string };
type Chunk = { id: string; ordinal: number; content: string; section_path: string | null; page_number: number | null; chunk_type: string; dependencies: Dependency[] };
type DocumentDetail = { document: { id: string; name: string; file_name: string; doc_type: string; mime_type: string; status: string; page_count: number | null; owner: { display_name: string } }; chunks: Chunk[] };

export function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.get<DocumentDetail>(`/documents/${params.id}`).then(setData).catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this document.")); }, [params.id]);
  if (error) return <div className="mx-auto max-w-6xl px-5 py-8"><p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="mx-auto max-w-6xl px-5 py-16 text-center text-muted-foreground"><LoaderCircle className="mx-auto animate-spin" /></div>;
  const fileUrl = apiUrl(`/files/documents/${data.document.id}`);
  const isPdf = data.document.mime_type.toLowerCase().includes("pdf") || data.document.file_name.toLowerCase().endsWith(".pdf");
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <Link href="/documents" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Documents</Link>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">{data.document.doc_type.replaceAll("_", " ")} · {data.document.owner.display_name}</p><h1 className="text-2xl font-semibold tracking-tight">{data.document.name}</h1></div><Button asChild variant="outline"><a href={fileUrl}><Download />Download original</a></Button></div>
    <div className="mt-7 overflow-hidden rounded-lg border">{isPdf ? <iframe title={data.document.name} src={`${fileUrl}?inline=true`} className="h-[70vh] w-full bg-muted/20" /> : <div className="max-h-[70vh] overflow-y-auto bg-muted/10 p-8"><div className="mx-auto max-w-3xl rounded-md bg-background p-8 shadow-sm">{data.chunks.map(chunk => <div key={`preview-${chunk.id}`} className="mb-5 last:mb-0">{chunk.chunk_type === "heading" ? <h2 className="font-serif text-lg font-semibold">{chunk.content}</h2> : <p className="whitespace-pre-wrap font-serif text-sm leading-7">{chunk.content}</p>}</div>)}</div></div>}</div>
    <section className="mt-8"><div className="flex items-center justify-between"><h2 className="font-medium">Extracted contents</h2><span className="text-sm text-muted-foreground">{data.chunks.length} chunks</span></div><div className="mt-3 divide-y rounded-lg border">{data.chunks.map(chunk => <article key={chunk.id} className="p-4"><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="outline">{chunk.chunk_type}</Badge>{chunk.section_path ? <span>{chunk.section_path}</span> : null}{chunk.page_number ? <span>page {chunk.page_number}</span> : null}</div><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{chunk.content}</p>{chunk.dependencies.length ? <div className="mt-3 flex flex-wrap gap-2">{chunk.dependencies.map(dep => <Badge key={dep.lineage_id} variant="secondary">{dep.public_ref} · {dep.relationship_type}</Badge>)}</div> : null}</article>)}</div></section>
  </div>;
}
