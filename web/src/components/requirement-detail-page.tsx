"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowUpRight, Download, FileText, LoaderCircle, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiUrl, ApiRequestError } from "@/lib/api";

type Requirement = {
  requirement_text: string;
  requirement_type: string;
  subject: string;
  value: string | null;
  source_section: string | null;
  source_page: number | null;
};

type Dependency = {
  dependency_id: string;
  document_id: string;
  document_chunk_id: string;
  document_name: string;
  section_path: string | null;
  page_number: number | null;
  excerpt: string;
  evidence_span: string | null;
  evidence_start: number | null;
  evidence_end: number | null;
  relationship_type: string;
  confidence: number;
};

type RequirementDetail = {
  lineage: { id: string; public_ref: string };
  current_version: Requirement;
  dependencies: Dependency[];
  regulation: { id: string; title: string } | null;
};

function documentHref(dependency: Dependency) {
  const params = new URLSearchParams({ chunk: dependency.document_chunk_id });
  if (dependency.evidence_start !== null) params.set("start", String(dependency.evidence_start));
  if (dependency.evidence_end !== null) params.set("end", String(dependency.evidence_end));
  return `/documents/${dependency.document_id}?${params.toString()}`;
}

export function RequirementDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<RequirementDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<RequirementDetail>(`/requirements/${params.id}`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this requirement."));
  }, [params.id]);

  if (error) return <div className="mx-auto max-w-6xl px-5 py-8"><p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p></div>;
  if (!data) return <div className="mx-auto max-w-6xl px-5 py-16 text-center text-muted-foreground"><LoaderCircle className="mx-auto animate-spin" /></div>;

  const regulationFileUrl = data.regulation ? apiUrl(`/files/regulations/${data.regulation.id}`) : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-8">
      <Link href="/requirements" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />Requirements</Link>
      <div className="mt-5">
        <div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{data.lineage.public_ref}</Badge><Badge variant="secondary" className="capitalize">{data.current_version.requirement_type}</Badge></div>
        <h1 className="mt-3 max-w-4xl text-2xl font-semibold tracking-tight">{data.current_version.requirement_text}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{data.current_version.source_section ?? "Source section unavailable"}{data.current_version.value ? ` · ${data.current_version.value}` : ""}</p>
      </div>

      {data.regulation && regulationFileUrl ? <section className="mt-8">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs text-muted-foreground">Original regulation</p><Link href={`/regulations/${data.regulation.id}`} className="mt-1 inline-flex items-center gap-2 font-medium hover:underline"><Scale className="size-4" />{data.regulation.title}</Link></div><Button asChild variant="outline"><a href={regulationFileUrl}><Download />Download original</a></Button></div>
        <div className="mt-3 overflow-hidden rounded-lg border"><iframe title={data.regulation.title} src={`${regulationFileUrl}?inline=true${data.current_version.source_page ? `#page=${data.current_version.source_page}` : ""}`} className="h-[65vh] w-full bg-muted/20" /></div>
      </section> : null}

      <section className="mt-8">
        <div className="flex items-center justify-between"><h2 className="font-medium">Linked documents</h2><span className="text-sm text-muted-foreground">{data.dependencies.length} dependencies</span></div>
        <div className="mt-3 divide-y rounded-lg border">
          {data.dependencies.length ? data.dependencies.map((dependency) => (
            <Link key={dependency.dependency_id} href={documentHref(dependency)} className="group flex gap-4 p-4 transition-colors hover:bg-muted/40">
              <FileText className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium group-hover:underline">{dependency.document_name}</p>
                  <div className="flex items-center gap-2"><Badge variant="outline" className="capitalize">{dependency.relationship_type}</Badge><span className="text-xs text-muted-foreground">{Math.round(dependency.confidence * 100)}%</span><ArrowUpRight className="size-4 text-muted-foreground" /></div>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{dependency.section_path ?? "Document passage"}{dependency.page_number ? ` · page ${dependency.page_number}` : ""}</p>
                <p className="mt-3 line-clamp-3 text-sm leading-6">{dependency.excerpt}</p>
              </div>
            </Link>
          )) : <p className="p-8 text-center text-sm text-muted-foreground">No visible documents are linked to this requirement.</p>}
        </div>
      </section>
    </div>
  );
}
