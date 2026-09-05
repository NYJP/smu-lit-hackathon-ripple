"use client";
import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Requirement = { lineage_id: string; public_ref: string; requirement_text: string; requirement_type: string; subject: string; value: string | null; source_section: string | null; version: number; dependency_count: number };

export function RequirementsPageContent() {
  const [items, setItems] = useState<Requirement[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.get<{ items: Requirement[] }>("/requirements").then(result => setItems(result.items)).catch(err => { setItems([]); setError(err instanceof ApiRequestError ? err.message : "Could not load requirements."); }); }, []);
  return <div className="mx-auto w-full max-w-6xl px-5 py-8"><div><p className="text-sm text-muted-foreground">Regulatory obligations</p><h1 className="text-2xl font-semibold tracking-tight">Requirements</h1></div>{error ? <p className="mt-4 text-sm text-destructive">{error}</p> : null}<div className="mt-7 overflow-x-auto rounded-lg border"><Table><TableHeader><TableRow><TableHead>Reference</TableHead><TableHead>Requirement</TableHead><TableHead>Type</TableHead><TableHead>Source</TableHead><TableHead className="text-right">Dependencies</TableHead></TableRow></TableHeader><TableBody>{items === null ? <TableRow><TableCell colSpan={5} className="py-10 text-center"><LoaderCircle className="mx-auto animate-spin" /></TableCell></TableRow> : items.length ? items.map(item => <TableRow key={item.lineage_id}><TableCell><Badge variant="outline">{item.public_ref}</Badge></TableCell><TableCell className="max-w-xl font-medium">{item.requirement_text}{item.value ? <span className="ml-2 text-muted-foreground">({item.value})</span> : null}</TableCell><TableCell className="capitalize">{item.requirement_type}</TableCell><TableCell className="text-muted-foreground">{item.source_section ?? "—"}</TableCell><TableCell className="text-right tabular-nums">{item.dependency_count}</TableCell></TableRow>) : <TableRow><TableCell colSpan={5} className="py-12 text-center text-muted-foreground">No requirements have been extracted.</TableCell></TableRow>}</TableBody></Table></div></div>;
}
