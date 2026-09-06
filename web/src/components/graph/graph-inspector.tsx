import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { SimulatedBadge } from "@/components/ui/status-badge";
import { EmptyState, SectionHeader, Surface } from "@/components/ui/workspace";
import type { GraphEdge, GraphNode } from "@/lib/types";

const endpoint = (value: unknown) => typeof value === "string" ? value : (value as { id?: string })?.id;
export function GraphInspector({ selected, nodes, edges, embedded = false }: { selected: GraphNode | null; nodes: GraphNode[]; edges: GraphEdge[]; embedded?: boolean }) {
  if (!selected) return <Surface elevated={!embedded} tone={embedded ? "plain" : "default"} className="min-h-64"><h2 className="sr-only">Node inspector</h2><EmptyState title="Inspect a node" description="Select a document or requirement to see its one-hop evidence and actions." /></Surface>;
  const connected = edges.filter(e => endpoint(e.source) === selected.id || endpoint(e.target) === selected.id || (selected.kind === "document" && e.document_id === selected.id.slice(4)));
  const byId = new Map(nodes.map(n => [n.id,n]));
  return <Surface elevated={!embedded} tone={embedded ? "plain" : "default"} className="p-4" data-testid={embedded ? undefined : "graph-inspector"}><SectionHeader title={selected.label} description={selected.kind === "document" ? `${selected.doc_type?.replaceAll("_"," ")} · Owned by ${selected.owner}` : selected.regulation_title} />
    <div className="mt-3 flex flex-wrap gap-2">{selected.impact_level ? <SeverityBadge severity={selected.impact_level} withNoun /> : null}{selected.change_source === "simulation" ? <SimulatedBadge /> : null}</div>
    {selected.requirement_text ? <p className="mt-4 text-sm leading-6">{selected.requirement_text}</p> : null}
    <h3 className="mt-5 text-sm font-medium">{connected.length} linked {connected.length === 1 ? "dependency" : "dependencies"}</h3>
    <div className="mt-2 divide-y">{connected.map(edge => { const other=selected.kind === "requirement" ? byId.get(`doc:${edge.document_id}`) : byId.get(endpoint(edge.source) ?? ""); return <div key={edge.id} className="py-3"><div className="flex items-start justify-between gap-2"><p className="text-sm font-medium">{other?.label}</p>{edge.severity ? <SeverityBadge severity={edge.severity} /> : null}</div><p className="mt-1 text-xs text-muted-foreground">{edge.relationship_type} · {Math.round(edge.confidence*100)}% confidence{edge.contributor ? ` · Written by ${edge.contributor.display_name}` : ""}</p>{edge.impact_reason ? <p className="mt-2 text-sm leading-5">{edge.impact_reason}</p> : null}</div>;})}</div>
    <Button asChild className="mt-4" size="sm"><Link href={selected.kind === "document" ? `/documents/${selected.id.slice(4)}` : `/requirements/${selected.id.slice(4)}`}>Open {selected.kind}<ExternalLink /></Link></Button>
  </Surface>;
}
