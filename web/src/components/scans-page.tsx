"use client";
import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Pending = { is_stale: boolean; gaps: Record<string, number>; estimated_cost_usd: number; running_scan_id: string | null };
type Scan = { id: string; trigger: string; scope: string; status: string; documents_scanned: number; requirements_scanned: number; dependencies_added: number; impacts_created: number; created_at: string };

export function ScansPageContent() {
  const [pending, setPending] = useState<Pending | null>(null); const [items, setItems] = useState<Scan[]>([]); const [running, setRunning] = useState(false); const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => { try { const [next, history] = await Promise.all([api.get<Pending>("/scans/pending"), api.get<{items: Scan[]}>("/scans")]); setPending(next); setItems(history.items); setError(null); } catch (err) { setError(err instanceof ApiRequestError ? err.message : "Could not load scans."); } }, []);
  useEffect(() => { void load(); }, [load]);
  async function scan() { setRunning(true); setError(null); try { await api.post("/scans", { scope: "stale" }); await load(); } catch (err) { setError(err instanceof ApiRequestError ? err.message : "Could not start the scan."); } finally { setRunning(false); } }
  const gapTotal = pending ? Object.values(pending.gaps).reduce((total, value) => total + value, 0) : 0;
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div className="flex items-end justify-between gap-4"><div><p className="text-sm text-muted-foreground">Corpus reconciliation</p><h1 className="text-2xl font-semibold tracking-tight">Scans</h1></div><Button onClick={() => void scan()} disabled={running || !!pending?.running_scan_id}>{running ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}Scan now</Button></div>{error ? <p className="mt-4 text-sm text-destructive">{error}</p> : null}<div className="mt-7 rounded-lg border p-4"><div className="flex items-center justify-between"><div><p className="font-medium">{pending?.is_stale ? `${gapTotal} items need attention` : "Corpus is up to date"}</p><p className="mt-1 text-sm text-muted-foreground">Checks missing mappings, unevaluated impacts, and changed source text.</p></div><Badge variant={pending?.is_stale ? "destructive" : "outline"}>{pending?.is_stale ? "Stale" : "Current"}</Badge></div></div><div className="mt-5 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Status</TableHead><TableHead>Scope</TableHead><TableHead className="text-right">Documents</TableHead><TableHead className="text-right">Dependencies</TableHead><TableHead className="text-right">Impacts</TableHead></TableRow></TableHeader><TableBody>{items.length ? items.map(item => <TableRow key={item.id}><TableCell><Badge variant="outline">{item.status}</Badge></TableCell><TableCell className="capitalize">{item.scope}</TableCell><TableCell className="text-right">{item.documents_scanned}</TableCell><TableCell className="text-right">{item.dependencies_added}</TableCell><TableCell className="text-right">{item.impacts_created}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">No scans have run yet.</TableCell></TableRow>}</TableBody></Table></div></div>;
}
