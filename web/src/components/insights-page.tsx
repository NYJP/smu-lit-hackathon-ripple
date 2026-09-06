"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { SourceBadge } from "@/components/ui/status-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DependencyGraph } from "@/components/graph/dependency-graph";
import type { ChangeSource, ChangeType, Severity } from "@/lib/types";

type Change = {
  id: string;
  summary: string;
  change_type: ChangeType;
  source: ChangeSource;
  analysis_status: string;
  created_at: string;
  max_severity: Severity;
  impact_count?: number;
  counts?: Record<string, number>;
};

function Loading() { return <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>; }

export function ChangesView() {
  const [items, setItems] = useState<Change[] | null>(null);
  useEffect(() => { api.get<{ items: Change[] }>("/changes").then(result => setItems(result.items)).catch(() => setItems([])); }, []);
  if (!items) return <Loading />;
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div><p className="text-sm text-muted-foreground">Change feed</p><h1 className="text-2xl font-semibold tracking-tight">Regulatory changes</h1></div><div className="mt-7 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Change</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead>Severity</TableHead><TableHead className="text-right">Impacts</TableHead></TableRow></TableHeader><TableBody>{items.length ? items.map(item => <TableRow key={item.id}><TableCell className="font-medium"><Link className="hover:underline" href={`/changes/${item.id}`}>{item.summary}</Link></TableCell><TableCell className="capitalize">{item.change_type}</TableCell><TableCell><div className="flex items-center gap-2"><Badge variant="outline">{item.analysis_status}</Badge><SourceBadge source={item.source} /></div></TableCell><TableCell><SeverityBadge severity={item.max_severity} /></TableCell><TableCell className="text-right tabular-nums">{item.impact_count ?? ((item.counts?.high ?? 0) + (item.counts?.medium ?? 0) + (item.counts?.low ?? 0))}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className="py-12 text-center text-muted-foreground">No regulatory changes have been detected.</TableCell></TableRow>}</TableBody></Table></div></div>;
}

export function GraphView() {
  return <DependencyGraph />;
}
