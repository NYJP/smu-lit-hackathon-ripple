"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertCircle, ListChecks } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { EmptyState, LoadingSkeleton, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Requirement = { lineage_id: string; public_ref: string; requirement_text: string; requirement_type: string; subject: string; value: string | null; source_section: string | null; version: number; dependency_count: number };

export function RequirementsPageContent() {
  const [items, setItems] = useState<Requirement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.get<{ items: Requirement[] }>("/requirements").then(result => setItems(result.items)).catch(err => { setItems([]); setError(err instanceof ApiRequestError ? err.message : "Could not load guidelines."); }); }, []);

  return <PageFrame>
    <PageHeader eyebrow="Regulatory workspace" title="Guidelines" description="Extracted obligations linked to the documents that depend on them." />
    {error ? <Surface><EmptyState icon={AlertCircle} title="Guidelines unavailable" description={error} /></Surface>
      : items === null ? <Surface><LoadingSkeleton rows={6} /></Surface>
      : items.length === 0 ? <Surface><EmptyState icon={ListChecks} title="No guidelines yet" description="Guidelines will appear after a regulation has been processed." /></Surface>
      : <Surface className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Reference</TableHead><TableHead>Guideline</TableHead><TableHead>Type</TableHead><TableHead>Source</TableHead><TableHead className="text-right">Dependencies</TableHead></TableRow></TableHeader><TableBody>{items.map(item => <TableRow key={item.lineage_id}><TableCell><Link href={`/guidelines/${item.lineage_id}`}><Badge variant="outline" className="hover:bg-secondary">{item.public_ref}</Badge></Link></TableCell><TableCell className="max-w-xl font-medium whitespace-normal"><Link className="hover:underline" href={`/guidelines/${item.lineage_id}`}>{item.requirement_text}</Link>{item.value ? <span className="ml-2 text-muted-foreground">({item.value})</span> : null}</TableCell><TableCell className="capitalize">{item.requirement_type}</TableCell><TableCell className="text-muted-foreground">{item.source_section ?? "—"}</TableCell><TableCell className="text-right tabular-nums"><Link className="hover:underline" href={`/guidelines/${item.lineage_id}`}>{item.dependency_count}</Link></TableCell></TableRow>)}</TableBody></Table></Surface>}
  </PageFrame>;
}
