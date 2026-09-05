"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, FileText, GitBranch } from "lucide-react";
import { api } from "@/lib/api";

type Dashboard = { impact_counts: Record<string, number>; documents_visible: number; recent_changes: Change[] };
type Change = { id: string; summary: string; change_type: string; analysis_status: string; created_at: string; impact_count?: number };

function Loading() { return <div className="py-16 text-sm text-muted-foreground">Loading…</div>; }

export function DashboardView() {
  const [data, setData] = useState<Dashboard | null>(null);
  useEffect(() => { api.get<Dashboard>("/dashboard").then(setData).catch(() => setData({ impact_counts: {}, documents_visible: 0, recent_changes: [] })); }, []);
  if (!data) return <Loading />;
  const high = data.impact_counts.high ?? 0;
  return <main className="space-y-8"><section><p className="text-sm text-muted-foreground">Overview</p><h1 className="text-3xl font-semibold tracking-tight">Compliance dashboard</h1></section><div className="grid gap-4 md:grid-cols-3"><Metric label="High-priority impacts" value={high} icon={<AlertTriangle className="text-red-600" />} /><Metric label="Visible documents" value={data.documents_visible} icon={<FileText />} /><Metric label="Recent changes" value={data.recent_changes.length} icon={<GitBranch />} /></div><section className="rounded-xl border bg-card"><div className="border-b p-5"><h2 className="font-medium">Recent regulatory changes</h2></div>{data.recent_changes.length ? <div className="divide-y">{data.recent_changes.map(change => <div key={change.id} className="flex items-center justify-between gap-4 p-5"><div><p className="font-medium">{change.summary}</p><p className="mt-1 text-sm text-muted-foreground">{change.change_type} · {change.analysis_status}</p></div></div>)}</div> : <p className="p-5 text-sm text-muted-foreground">No changes are ready to review.</p>}</section></main>;
}

function Metric({ label, value, icon }: { label: string; value: number; icon: ReactNode }) { return <div className="rounded-xl border bg-card p-5"><div className="flex items-center justify-between"><p className="text-sm text-muted-foreground">{label}</p>{icon}</div><p className="mt-4 text-3xl font-semibold">{value}</p></div>; }

export function ChangesView() {
  const [items, setItems] = useState<Change[] | null>(null);
  useEffect(() => { api.get<{ items: Change[] }>("/changes").then(result => setItems(result.items)).catch(() => setItems([])); }, []);
  if (!items) return <Loading />;
  return <main className="space-y-6"><section><p className="text-sm text-muted-foreground">Change feed</p><h1 className="text-3xl font-semibold tracking-tight">Regulatory changes</h1></section><section className="overflow-hidden rounded-xl border bg-card">{items.length ? items.map(item => <div key={item.id} className="flex items-center justify-between gap-6 border-b p-5 last:border-0"><div><p className="font-medium">{item.summary}</p><p className="mt-1 text-sm text-muted-foreground">{item.change_type} · {item.analysis_status}</p></div><a className="text-sm font-medium underline" href={`/changes/${item.id}`}>Review</a></div>) : <p className="p-6 text-sm text-muted-foreground">No regulatory changes have been detected.</p>}</section></main>;
}

export function GraphView() {
  const [data, setData] = useState<{ nodes: { id: string; label: string; kind: string; state: string }[]; edges: unknown[] } | null>(null);
  useEffect(() => { api.get<{ nodes: { id: string; label: string; kind: string; state: string }[]; edges: unknown[] }>("/graph").then(setData).catch(() => setData({ nodes: [], edges: [] })); }, []);
  if (!data) return <Loading />;
  return <main className="space-y-6"><section><p className="text-sm text-muted-foreground">Relationship map</p><h1 className="text-3xl font-semibold tracking-tight">Dependency graph</h1></section><section className="rounded-xl border bg-card p-5"><p className="mb-4 text-sm text-muted-foreground">{data.nodes.length} nodes · {data.edges.length} links</p><div className="grid gap-3 md:grid-cols-2">{data.nodes.map(node => <div key={node.id} className="rounded-lg border p-3"><p className="font-medium">{node.label}</p><p className="mt-1 text-xs text-muted-foreground">{node.kind} · {node.state.replaceAll("_", " ")}</p></div>)}</div>{!data.nodes.length && <p className="text-sm text-muted-foreground">No visible dependencies yet.</p>}</section></main>;
}
