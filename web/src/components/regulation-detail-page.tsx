"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Download, LoaderCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, apiUrl, ApiRequestError } from "@/lib/api";

type Requirement = {
  id: string;
  requirement_text: string;
  requirement_type: string;
  source_section: string | null;
  source_page: number | null;
  is_current: number;
};

type Change = {
  id: string;
  summary: string;
  change_type: string;
  analysis_status: string;
};

type RegulationDetail = {
  regulation: {
    id: string;
    title: string;
    file_name: string;
    document_kind: string;
    status: string;
    page_count: number | null;
    jurisdiction: string | null;
    effective_date: string | null;
  };
  requirements: Requirement[];
  changes: Change[];
};

export function RegulationDetailPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<RegulationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<RegulationDetail>(`/regulations/${params.id}`)
      .then(setData)
      .catch((err) => setError(err instanceof ApiRequestError ? err.message : "Could not load this regulation."));
  }, [params.id]);

  if (error) {
    return <div className="mx-auto max-w-6xl px-5 py-8"><p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p></div>;
  }
  if (!data) {
    return <div className="mx-auto max-w-6xl px-5 py-16 text-center text-muted-foreground"><LoaderCircle className="mx-auto animate-spin" /></div>;
  }

  const fileUrl = apiUrl(`/files/regulations/${data.regulation.id}`);

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-8">
      <Link href="/regulations" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" />Regulations
      </Link>
      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm capitalize text-muted-foreground">
            {data.regulation.document_kind.replaceAll("_", " ")}
            {data.regulation.page_count ? ` · ${data.regulation.page_count} pages` : ""}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{data.regulation.title}</h1>
        </div>
        <Button asChild variant="outline"><a href={fileUrl}><Download />Download original</a></Button>
      </div>

      <div className="mt-7 overflow-hidden rounded-lg border">
        <iframe title={data.regulation.title} src={`${fileUrl}?inline=true`} className="h-[70vh] w-full bg-muted/20" />
      </div>

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">Extracted requirements</h2>
          <span className="text-sm text-muted-foreground">{data.requirements.length} requirements</span>
        </div>
        <div className="mt-3 divide-y rounded-lg border">
          {data.requirements.length ? data.requirements.map((requirement) => (
            <article key={requirement.id} className="p-4">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline" className="capitalize">{requirement.requirement_type}</Badge>
                {requirement.source_section ? <span>{requirement.source_section}</span> : null}
                {requirement.source_page ? <span>page {requirement.source_page}</span> : null}
                {!requirement.is_current ? <Badge variant="secondary">Superseded</Badge> : null}
              </div>
              <p className="mt-3 text-sm leading-6">{requirement.requirement_text}</p>
            </article>
          )) : <p className="p-6 text-center text-sm text-muted-foreground">No requirements were extracted from this file.</p>}
        </div>
      </section>
    </div>
  );
}
