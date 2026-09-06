"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, FileSearch, LoaderCircle, Search } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, PageFrame, PageHeader, SectionHeader, Surface } from "@/components/ui/workspace";

type ChunkResult = { chunk_id: string; document_id: string; document_name: string; section_path: string | null; page_number: number | null; snippet: string; score: number };
type RequirementResult = { lineage_id: string; public_ref: string; requirement_text: string; source_section: string | null; score: number };
type Results = { chunks: ChunkResult[]; requirements: RequirementResult[] };

export function SearchPageContent() {
  const [query, setQuery] = useState(""), [results, setResults] = useState<Results | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const value=query.trim();if(!value)return;setLoading(true);setError(null);try{setResults(await api.get<Results>(`/search?q=${encodeURIComponent(value)}&scope=all`));}catch(err){setResults(null);setError(err instanceof ApiRequestError?err.message:"Could not search the corpus.");}finally{setLoading(false);} }
  const count=(results?.chunks.length??0)+(results?.requirements.length??0);

  return <PageFrame>
    <PageHeader eyebrow="Corpus retrieval" title="Search" description="Find obligations and the internal passages connected to them." />
    <Surface tone="subtle" className="p-3"><form onSubmit={submit} className="flex gap-2"><Input className="h-10 bg-background" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Ask a question or search a phrase" aria-label="Search query" /><Button className="h-10" type="submit" disabled={loading||!query.trim()}>{loading?<LoaderCircle className="animate-spin"/>:<Search/>}Search</Button></form></Surface>
    {error ? <Surface><EmptyState icon={AlertCircle} title="Search unavailable" description={error} /></Surface> : null}
    {results ? <div className="space-y-6"><p className="text-sm tabular-nums text-muted-foreground">{count} {count===1?"result":"results"}</p><ResultSection title="Requirements" empty="No matching requirements.">{results.requirements.map(item=><div key={item.lineage_id} className="border-b px-4 py-4 last:border-0"><div className="flex items-center gap-2"><Badge variant="outline">{item.public_ref}</Badge>{item.source_section?<span className="text-xs text-muted-foreground">{item.source_section}</span>:null}</div><p className="mt-2 text-sm leading-6">{item.requirement_text}</p></div>)}</ResultSection><ResultSection title="Documents" empty="No matching document passages.">{results.chunks.map(item=><div key={item.chunk_id} className="border-b px-4 py-4 last:border-0"><p className="font-medium">{item.document_name}</p><p className="mt-1 text-xs text-muted-foreground">{item.section_path??"Unsectioned"}{item.page_number?` · page ${item.page_number}`:""}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{item.snippet}</p></div>)}</ResultSection></div>
      : <Surface tone="subtle"><EmptyState icon={FileSearch} title="Search the regulatory workspace" description="Try a duty, deadline, document name, or phrase such as “customer retention period”." /></Surface>}
  </PageFrame>;
}

function ResultSection({title,empty,children}:{title:string;empty:string;children:ReactNode[]}) { return <section className="space-y-3"><SectionHeader title={title}/><Surface>{children.length?children:<EmptyState className="min-h-32" title={empty} description="Try a broader phrase or another term."/>}</Surface></section>; }
