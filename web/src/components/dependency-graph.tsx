"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { FileText, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";

type ApiNode = {
  id: string;
  label: string;
  kind: "requirement" | "document" | "section";
  state: string;
  impact_level: string | null;
  requirement_text?: string;
  regulation_title?: string;
  doc_type?: string;
  owner?: string;
};

type ApiEdge = {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  confidence: number;
  lineage_id: string;
  document_id: string;
  document_chunk_id: string;
  evidence_start: number | null;
  evidence_end: number | null;
  page_number: number | null;
  impact_level: string | null;
  impact_reason: string | null;
  change_summary: string | null;
  affected_start: number | null;
  affected_end: number | null;
  contributor: { id: string; display_name: string } | null;
};

type GraphData = { nodes: ApiNode[]; edges: ApiEdge[] };
type FlowData = { label: React.ReactNode; api: ApiNode };

const affected = (node: ApiNode) => node.state.startsWith("affected_");

function documentHref(edge: ApiEdge) {
  const query = new URLSearchParams({ chunk: edge.document_chunk_id });
  const start = edge.affected_start ?? edge.evidence_start;
  const end = edge.affected_end ?? edge.evidence_end;
  if (start !== null) query.set("start", String(start));
  if (end !== null) query.set("end", String(end));
  return `/documents/${edge.document_id}?${query.toString()}`;
}

function NodeLabel({ node }: { node: ApiNode }) {
  return <div className="flex items-start gap-2 text-left"><span className="mt-0.5">{node.kind === "requirement" ? <Scale className="size-4" /> : <FileText className="size-4" />}</span><div className="min-w-0"><p className="truncate text-xs font-semibold">{node.label}</p><p className="mt-1 text-[10px] capitalize opacity-70">{affected(node) ? `${node.impact_level} impact` : node.kind}</p></div></div>;
}

export function DependencyGraph() {
  const [data, setData] = useState<GraphData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    api.get<GraphData>("/graph").then(setData).catch(() => setData({ nodes: [], edges: [] }));
  }, []);

  const flowNodes = useMemo<Node<FlowData>[]>(() => {
    if (!data) return [];
    const requirements = data.nodes.filter((node) => node.kind === "requirement");
    const documents = data.nodes.filter((node) => node.kind === "document");
    return [...requirements.map((node, index) => ({
      id: node.id,
      position: { x: 40, y: index * 145 + 35 },
      data: { label: <NodeLabel node={node} />, api: node },
      style: { width: 260, border: affected(node) ? "2px solid var(--impact-high)" : "1px solid var(--border)", borderRadius: 10, background: affected(node) ? "color-mix(in oklch, var(--impact-high) 12%, var(--card))" : "var(--card)", color: "var(--foreground)", boxShadow: affected(node) ? "0 0 0 4px color-mix(in oklch, var(--impact-high) 12%, transparent)" : "none" },
    })), ...documents.map((node, index) => ({
      id: node.id,
      position: { x: 560, y: index * 120 + 35 },
      data: { label: <NodeLabel node={node} />, api: node },
      style: { width: 260, border: affected(node) ? "2px solid var(--impact-high)" : "1px solid var(--border)", borderRadius: 10, background: affected(node) ? "color-mix(in oklch, var(--impact-high) 12%, var(--card))" : "var(--card)", color: "var(--foreground)", boxShadow: affected(node) ? "0 0 0 4px color-mix(in oklch, var(--impact-high) 12%, transparent)" : "none" },
    }))];
  }, [data]);

  const flowEdges = useMemo<Edge[]>(() => (data?.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: !!edge.impact_level,
    label: edge.relationship_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: edge.impact_level ? "var(--impact-high)" : "var(--muted-foreground)", strokeWidth: edge.impact_level ? 2.5 : 1.25 },
    labelStyle: { fill: "var(--muted-foreground)", fontSize: 10 },
    labelBgStyle: { fill: "var(--background)", fillOpacity: 0.9 },
  })), [data]);

  if (!data) return <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>;
  const selected = data.nodes.find((node) => node.id === selectedId) ?? null;
  const selectedEdges = selected?.kind === "requirement"
    ? data.edges.filter((edge) => edge.source === selected.id)
    : selected?.kind === "document"
      ? data.edges.filter((edge) => edge.document_id === selected.id.replace("doc:", ""))
      : [];
  const nodeById = new Map(data.nodes.map((node) => [node.id, node]));

  return <div className="mx-auto w-full max-w-7xl px-5 py-8">
    <div><p className="text-sm text-muted-foreground">Relationship map</p><h1 className="text-2xl font-semibold tracking-tight">Dependency graph</h1></div>
    <div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-muted-foreground"><span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-impact-high" />Affected by an open change</span><span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-full border bg-card" />Current dependency</span><span>Scroll to zoom · drag to pan · click a node for details</span></div>
    <div className="mt-5 h-[68vh] min-h-[520px] overflow-hidden rounded-lg border bg-muted/20">
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView fitViewOptions={{ padding: 0.18 }} minZoom={0.2} maxZoom={2.5} onNodeClick={(_, node) => setSelectedId(node.id)} onPaneClick={() => setSelectedId(null)} nodesDraggable>
        <Background gap={22} size={1} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(node) => affected((node.data as FlowData).api) ? "var(--impact-high)" : "var(--muted-foreground)"} />
      </ReactFlow>
    </div>
    <p className="mt-3 text-xs text-muted-foreground">{data.nodes.length} nodes · {data.edges.length} links</p>

    <details className="mt-6 rounded-lg border"><summary className="cursor-pointer px-4 py-3 text-sm font-medium">Dependency table</summary><div className="overflow-x-auto border-t"><Table><TableHeader><TableRow><TableHead>Requirement</TableHead><TableHead>Linked document</TableHead><TableHead>Relationship</TableHead><TableHead>Impact</TableHead></TableRow></TableHeader><TableBody>{data.edges.map((edge) => <TableRow key={edge.id}><TableCell><Link className="hover:underline" href={`/requirements/${edge.lineage_id}`}>{nodeById.get(edge.source)?.label}</Link></TableCell><TableCell><Link className="hover:underline" href={documentHref(edge)}>{nodeById.get(`doc:${edge.document_id}`)?.label}</Link></TableCell><TableCell className="capitalize">{edge.relationship_type}</TableCell><TableCell>{edge.impact_level ? <Badge variant="destructive" className="capitalize">{edge.impact_level}</Badge> : <span className="text-muted-foreground">None</span>}</TableCell></TableRow>)}</TableBody></Table></div></details>

    <Sheet open={!!selected} onOpenChange={(open) => { if (!open) setSelectedId(null); }}><SheetContent className="w-full overflow-y-auto sm:max-w-lg"><SheetHeader><SheetTitle>{selected?.label}</SheetTitle><SheetDescription>{selected?.kind === "document" ? `${selected.doc_type?.replaceAll("_", " ")} · Owned by ${selected.owner}` : selected?.regulation_title}</SheetDescription></SheetHeader>{selected ? <div className="space-y-5 px-4 pb-6">{affected(selected) ? <Badge variant="destructive" className="capitalize">{selected.impact_level} impact</Badge> : <Badge variant="outline">Not affected</Badge>}{selected.requirement_text ? <p className="text-sm leading-6">{selected.requirement_text}</p> : null}<div><h3 className="text-sm font-medium">{selected.kind === "requirement" ? "Linked documents" : "Linked requirements"}</h3><div className="mt-2 divide-y rounded-md border">{selectedEdges.map((edge) => { const counterpart = selected.kind === "requirement" ? nodeById.get(`doc:${edge.document_id}`) : nodeById.get(edge.source); return <div key={edge.id} className="p-3"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium">{counterpart?.label}</p>{edge.contributor ? <p className="mt-1 text-xs text-muted-foreground">Affected sentence written by {edge.contributor.display_name}</p> : selected.kind === "requirement" && counterpart?.owner ? <p className="mt-1 text-xs text-muted-foreground">Owned by {counterpart.owner}</p> : null}</div>{edge.impact_level ? <Badge variant="destructive" className="capitalize">{edge.impact_level}</Badge> : null}</div>{edge.change_summary ? <p className="mt-2 text-xs text-muted-foreground">{edge.change_summary}</p> : null}{edge.impact_reason ? <p className="mt-2 text-sm leading-5">{edge.impact_reason}</p> : null}<Button asChild variant="outline" size="sm" className="mt-3"><Link href={selected.kind === "requirement" ? documentHref(edge) : `/requirements/${edge.lineage_id}`}>{selected.kind === "requirement" ? "View affected passage" : "View requirement"}</Link></Button></div>; })}</div></div></div> : null}</SheetContent></Sheet>
  </div>;
}
