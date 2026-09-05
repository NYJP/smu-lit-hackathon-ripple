"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, FileText, GitBranch } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Dashboard = { impact_counts: Record<string, number>; documents_visible: number; recent_changes: Change[] };
type Change = { id: string; summary: string; change_type: string; analysis_status: string; created_at: string; impact_count?: number };

function Loading() { return <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>; }

export function DashboardView() {
  const [data, setData] = useState<Dashboard | null>(null);
  useEffect(() => { api.get<Dashboard>("/dashboard").then(setData).catch(() => setData({ impact_counts: {}, documents_visible: 0, recent_changes: [] })); }, []);
  if (!data) return <Loading />;
  const high = data.impact_counts.high ?? 0;
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div><p className="text-sm text-muted-foreground">Overview</p><h1 className="text-2xl font-semibold tracking-tight">Compliance dashboard</h1></div><div className="mt-7 grid gap-4 md:grid-cols-3"><Metric label="High-priority impacts" value={high} icon={<AlertTriangle className="text-destructive" />} /><Metric label="Visible documents" value={data.documents_visible} icon={<FileText />} /><Metric label="Recent changes" value={data.recent_changes.length} icon={<GitBranch />} /></div><div className="mt-7 rounded-lg border"><div className="border-b px-4 py-3"><h2 className="text-sm font-medium">Recent regulatory changes</h2></div>{data.recent_changes.length ? <div className="divide-y">{data.recent_changes.map(change => <div key={change.id} className="flex items-center justify-between gap-4 px-4 py-3"><div><p className="font-medium">{change.summary}</p><p className="mt-1 text-sm text-muted-foreground">{change.change_type} · {change.analysis_status}</p></div><Badge variant="outline">{change.impact_count ?? 0} impacts</Badge></div>)}</div> : <p className="px-4 py-8 text-center text-sm text-muted-foreground">No changes are ready to review.</p>}</div></div>;
}

function Metric({ label, value, icon }: { label: string; value: number; icon: ReactNode }) { return <div className="rounded-lg border p-4"><div className="flex items-center justify-between"><p className="text-sm text-muted-foreground">{label}</p>{icon}</div><p className="mt-3 text-2xl font-semibold tabular-nums">{value}</p></div>; }

export function ChangesView() {
  const [items, setItems] = useState<Change[] | null>(null);
  useEffect(() => { api.get<{ items: Change[] }>("/changes").then(result => setItems(result.items)).catch(() => setItems([])); }, []);
  if (!items) return <Loading />;
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div><p className="text-sm text-muted-foreground">Change feed</p><h1 className="text-2xl font-semibold tracking-tight">Regulatory changes</h1></div><div className="mt-7 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Change</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Impacts</TableHead></TableRow></TableHeader><TableBody>{items.length ? items.map(item => <TableRow key={item.id}><TableCell className="font-medium"><a className="hover:underline" href={`/changes/${item.id}`}>{item.summary}</a></TableCell><TableCell className="capitalize">{item.change_type}</TableCell><TableCell><Badge variant="outline">{item.analysis_status}</Badge></TableCell><TableCell className="text-right tabular-nums">{item.impact_count ?? 0}</TableCell></TableRow>) : <TableRow><TableCell colSpan={4} className="py-12 text-center text-muted-foreground">No regulatory changes have been detected.</TableCell></TableRow>}</TableBody></Table></div></div>;
}

export function GraphView() {
  const [data, setData] = useState<{ nodes: { id: string; label: string; kind: string; state: string }[]; edges: unknown[] } | null>(null);
  useEffect(() => { api.get<{ nodes: { id: string; label: string; kind: string; state: string }[]; edges: unknown[] }>("/graph").then(setData).catch(() => setData({ nodes: [], edges: [] })); }, []);
  if (!data) return <Loading />;
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div><p className="text-sm text-muted-foreground">Relationship map</p><h1 className="text-2xl font-semibold tracking-tight">Dependency graph</h1></div><div className="mt-7 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Node</TableHead><TableHead>Kind</TableHead><TableHead>State</TableHead></TableRow></TableHeader><TableBody>{data.nodes.length ? data.nodes.map(node => <TableRow key={node.id}><TableCell className="font-medium">{node.label}</TableCell><TableCell className="capitalize">{node.kind}</TableCell><TableCell className="capitalize"><Badge variant="outline">{node.state.replaceAll("_", " ")}</Badge></TableCell></TableRow>) : <TableRow><TableCell colSpan={3} className="py-12 text-center text-muted-foreground">No visible dependencies yet.</TableCell></TableRow>}</TableBody></Table></div><p className="mt-3 text-xs text-muted-foreground">{data.nodes.length} nodes · {data.edges.length} links</p></div>;
}
