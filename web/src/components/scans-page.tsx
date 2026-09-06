"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CircleCheck, LoaderCircle, Radar, RefreshCw } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Pending = { is_stale: boolean; gaps: Record<string, number>; estimated_cost_usd: number; running_scan_id: string | null };
type Scan = { id: string; trigger: string; scope: string; status: string; documents_scanned: number; requirements_scanned: number; dependencies_added: number; impacts_created: number; created_at: string };

export function ScansPageContent() {
  const [pending, setPending] = useState<Pending | null>(null), [items, setItems] = useState<Scan[]>([]), [running, setRunning] = useState(false), [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => { try { const [next, history] = await Promise.all([api.get<Pending>("/scans/pending"), api.get<{items: Scan[]}>("/scans")]); setPending(next); setItems(history.items); setError(null); } catch (err) { setError(err instanceof ApiRequestError ? err.message : "Could not load scans."); } }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  async function scan() { setRunning(true); setError(null); try { await api.post("/scans", { scope: "stale" }); await load(); } catch (err) { setError(err instanceof ApiRequestError ? err.message : "Could not start the scan."); } finally { setRunning(false); } }
  const gapTotal = pending ? Object.values(pending.gaps).reduce((total, value) => total + value, 0) : 0;

  return <PageFrame>
    <PageHeader eyebrow="Corpus health" title="Scans" description="Check the workspace for missing mappings, unevaluated impacts, and changed source text." actions={<Button onClick={() => void scan()} disabled={running || !!pending?.running_scan_id}>{running ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}Scan now</Button>} />
    {error ? <Surface><EmptyState icon={AlertCircle} title="Scan status unavailable" description={error} /></Surface> : null}
    <Surface tone={pending?.is_stale ? "default" : "subtle"} className="p-5"><div className="flex items-start justify-between gap-4"><div className="flex gap-3">{pending?.is_stale ? <Radar className="mt-0.5 size-5 text-destructive" /> : <CircleCheck className="mt-0.5 size-5 text-status-done" />}<div><h2 className="font-medium">{pending?.is_stale ? `${gapTotal} items need attention` : "Corpus is up to date"}</h2><p className="mt-1 text-sm text-muted-foreground">{pending?.running_scan_id ? "A scan is currently running." : "Run a scan after uploading or changing source material."}</p></div></div><Badge variant={pending?.is_stale ? "destructive" : "outline"}>{pending?.is_stale ? "Stale" : "Current"}</Badge></div></Surface>
    <section><h2 className="mb-3 text-sm font-semibold">Scan history</h2><Surface className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Status</TableHead><TableHead>Scope</TableHead><TableHead className="text-right">Documents</TableHead><TableHead className="text-right">Dependencies</TableHead><TableHead className="text-right">Impacts</TableHead></TableRow></TableHeader><TableBody>{items.length ? items.map(item => <TableRow key={item.id}><TableCell><Badge variant="outline">{item.status}</Badge></TableCell><TableCell className="capitalize">{item.scope}</TableCell><TableCell className="text-right">{item.documents_scanned}</TableCell><TableCell className="text-right">{item.dependencies_added}</TableCell><TableCell className="text-right">{item.impacts_created}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5}><EmptyState className="min-h-36" title="No scan history" description="Your first completed scan will appear here." /></TableCell></TableRow>}</TableBody></Table></Surface></section>
  </PageFrame>;
}
