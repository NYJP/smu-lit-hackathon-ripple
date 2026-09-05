"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { LoaderCircle, Search } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type ChunkResult = { chunk_id: string; document_id: string; document_name: string; section_path: string | null; page_number: number | null; snippet: string; score: number };
type RequirementResult = { lineage_id: string; public_ref: string; requirement_text: string; source_section: string | null; score: number };
type Results = { chunks: ChunkResult[]; requirements: RequirementResult[] };

export function SearchPageContent() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Results | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      setResults(await api.get<Results>(`/search?q=${encodeURIComponent(value)}&scope=all`));
    } catch (err) {
      setResults(null);
      setError(err instanceof ApiRequestError ? err.message : "Could not search the corpus.");
    } finally {
      setLoading(false);
    }
  }

  const count = (results?.chunks.length ?? 0) + (results?.requirements.length ?? 0);
  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <div><p className="text-sm text-muted-foreground">Corpus retrieval</p><h1 className="text-2xl font-semibold tracking-tight">Search</h1></div>
    <form onSubmit={submit} className="mt-7 flex max-w-2xl gap-2"><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search requirements and internal documents" aria-label="Search query" /><Button type="submit" disabled={loading || !query.trim()}>{loading ? <LoaderCircle className="animate-spin" /> : <Search />}Search</Button></form>
    {error ? <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p> : null}
    {results ? <div className="mt-7 space-y-7"><p className="text-sm text-muted-foreground">{count} {count === 1 ? "result" : "results"}</p>
      <ResultSection title="Requirements" empty="No matching requirements.">{results.requirements.map(item => <div key={item.lineage_id} className="border-b px-4 py-4 last:border-0"><div className="flex items-center gap-2"><Badge variant="outline">{item.public_ref}</Badge>{item.source_section ? <span className="text-xs text-muted-foreground">{item.source_section}</span> : null}</div><p className="mt-2 text-sm">{item.requirement_text}</p></div>)}</ResultSection>
      <ResultSection title="Documents" empty="No matching document passages.">{results.chunks.map(item => <div key={item.chunk_id} className="border-b px-4 py-4 last:border-0"><p className="font-medium">{item.document_name}</p><p className="mt-1 text-xs text-muted-foreground">{item.section_path ?? "Unsectioned"}{item.page_number ? ` · page ${item.page_number}` : ""}</p><p className="mt-2 text-sm text-muted-foreground">{item.snippet}</p></div>)}</ResultSection>
    </div> : <p className="mt-8 text-sm text-muted-foreground">Enter a question or phrase to search across visible documents and regulations.</p>}
  </div>;
}

function ResultSection({ title, empty, children }: { title: string; empty: string; children: ReactNode[] }) {
  return <section><h2 className="mb-3 text-sm font-medium">{title}</h2><div className="rounded-lg border">{children.length ? children : <p className="px-4 py-8 text-center text-sm text-muted-foreground">{empty}</p>}</div></section>;
}
