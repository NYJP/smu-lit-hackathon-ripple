"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, FileText, LoaderCircle, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { api, ApiRequestError } from "@/lib/api";

type Requirement = {
  requirement_text: string;
  requirement_type: string;
  subject: string;
  value: string | null;
  source_section: string | null;
};

type ChangeDetail = {
  change: {
    id: string;
    summary: string;
    change_type: string;
    source: string;
    source_section: string | null;
    effective_date: string | null;
    analysis_status: string;
    created_at: string;
  };
  regulation: { id: string; title: string } | null;
  previous_requirement: Requirement | null;
  new_requirement: Requirement | null;
  counts: Record<"high" | "medium" | "low" | "none", number>;
  affected_documents: Array<{
    document_id: string;
    name: string;
    doc_type: string;
    impact_count: number;
    max_impact_level: string;
    owner: { id: string; display_name: string };
  }>;
};

type Impact = {
  impact_id: string;
  impact_level: string;
  confidence: number;
  reason: string;
  review_status: string;
  conflicting_start: number | null;
  conflicting_end: number | null;
  document_id: string;
  document_name: string;
  owner_name: string;
  contributor: { id: string; display_name: string } | null;
  chunk_id: string;
  chunk_content: string;
  section_path: string | null;
  page_number: number | null;
};

function passageHref(impact: Impact) {
  const query = new URLSearchParams({ chunk: impact.chunk_id });
  if (impact.conflicting_start !== null) query.set("start", String(impact.conflicting_start));
  if (impact.conflicting_end !== null) query.set("end", String(impact.conflicting_end));
  return `/documents/${impact.document_id}?${query.toString()}`;
}

function RequirementPanel({ label, requirement }: { label: string; requirement: Requirement | null }) {
  return <div className="rounded-lg border p-4">
    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
    {requirement ? <>
      <div className="mt-3 flex flex-wrap items-center gap-2"><Badge variant="outline" className="capitalize">{requirement.requirement_type}</Badge>{requirement.source_section ? <span className="text-xs text-muted-foreground">{requirement.source_section}</span> : null}</div>
      <p className="mt-3 text-sm leading-6">{requirement.requirement_text}</p>
      {requirement.value ? <p className="mt-3 text-xs text-muted-foreground">Value: {requirement.value}</p> : null}
    </> : <p className="mt-3 text-sm text-muted-foreground">No requirement for this version.</p>}
  </div>;
}

export function ChangeDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<ChangeDetail | null>(null);
  const [impacts, setImpacts] = useState<Impact[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<ChangeDetail>(`/changes/${params.id}`),
      api.get<{ items: Impact[] }>(`/changes/${params.id}/impacts?limit=200`),
    ]).then(([change, result]) => {
      setData(change);
      setImpacts(result.items.filter((impact) => impact.impact_level !== "none"));
    }).catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this regulatory change."));
  }, [params.id]);

  if (error) return <div className="mx-auto max-w-6xl px-5 py-8"><p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="mx-auto max-w-6xl px-5 py-16 text-center text-muted-foreground"><LoaderCircle className="mx-auto animate-spin" /></div>;

  const affectedCount = data.counts.high + data.counts.medium + data.counts.low;

  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <Link href="/changes" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Regulatory changes</Link>

    <div className="mt-5">
      <div className="flex flex-wrap items-center gap-2"><Badge variant="outline" className="capitalize">{data.change.change_type.replaceAll("_", " ")}</Badge><Badge variant="secondary" className="capitalize">{data.change.analysis_status}</Badge></div>
      <h1 className="mt-3 max-w-4xl text-2xl font-semibold tracking-tight">{data.change.summary}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{data.change.source_section ?? "Source section unavailable"}{data.change.effective_date ? ` · Effective ${data.change.effective_date}` : ""}</p>
    </div>

    {data.regulation ? <Link href={`/regulations/${data.regulation.id}`} className="mt-7 flex items-center gap-3 rounded-lg border p-4 transition-colors hover:bg-muted/40"><Scale className="size-5 text-muted-foreground" /><div className="min-w-0 flex-1"><p className="text-xs text-muted-foreground">Source regulation</p><p className="truncate font-medium">{data.regulation.title}</p></div><ArrowUpRight className="size-4 text-muted-foreground" /></Link> : null}

    <section className="mt-8">
      <h2 className="font-medium">Requirement change</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2"><RequirementPanel label="Previous requirement" requirement={data.previous_requirement} /><RequirementPanel label="New requirement" requirement={data.new_requirement} /></div>
    </section>

    <section className="mt-8">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-medium">Affected documents</h2><div className="flex items-center gap-2"><Badge variant="destructive">{affectedCount} affected passages</Badge><span className="text-sm text-muted-foreground">{data.affected_documents.length} documents</span></div></div>
      <div className="mt-3 divide-y rounded-lg border">
        {impacts.length ? impacts.map((impact) => <Link key={impact.impact_id} href={passageHref(impact)} className="group flex gap-4 p-4 transition-colors hover:bg-muted/40">
          <FileText className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium group-hover:underline">{impact.document_name}</p><p className="mt-1 text-xs text-muted-foreground">Affected sentence written by {impact.contributor?.display_name ?? impact.owner_name}{impact.section_path ? ` · ${impact.section_path}` : ""}{impact.page_number ? ` · page ${impact.page_number}` : ""}</p></div><div className="flex items-center gap-2"><Badge variant="destructive" className="capitalize">{impact.impact_level} impact</Badge><span className="text-xs text-muted-foreground">{Math.round(impact.confidence * 100)}%</span><ArrowUpRight className="size-4 text-muted-foreground" /></div></div>
            <p className="mt-3 text-sm leading-6">{impact.reason}</p>
            <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{impact.chunk_content}</p>
          </div>
        </Link>) : <p className="p-8 text-center text-sm text-muted-foreground">No affected passages were found for this change.</p>}
      </div>
    </section>
  </div>;
}
