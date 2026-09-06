import Link from "next/link";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { Surface, EmptyState } from "@/components/ui/workspace";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { GraphEdge, GraphNode } from "@/lib/types";

const href = (edge: GraphEdge) => { const q = new URLSearchParams({ chunk: edge.document_chunk_id }); const start=edge.affected_start ?? edge.evidence_start, end=edge.affected_end ?? edge.evidence_end; if(start!==null)q.set("start",String(start));if(end!==null)q.set("end",String(end));return `/documents/${edge.document_id}?${q}`; };
export function GraphTable({ nodes, edges, onSelect }: { nodes: GraphNode[]; edges: GraphEdge[]; onSelect: (id: string) => void }) {
  const byId = new Map(nodes.map(n => [n.id,n]));
  if (!edges.length) return <Surface><EmptyState title="No dependencies found" description="Adjust the filters or load a broader graph." /></Surface>;
  return <Surface><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Guideline</TableHead><TableHead>Document</TableHead><TableHead>Owner</TableHead><TableHead>Relationship</TableHead><TableHead>Confidence</TableHead><TableHead>Impact</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{edges.map(edge => { const req=byId.get(typeof edge.source === "string" ? edge.source : ""), doc=byId.get(`doc:${edge.document_id}`); return <TableRow key={edge.id}><TableCell><button className="text-left font-medium hover:underline" onClick={() => req && onSelect(req.id)}>{req?.label}</button></TableCell><TableCell><Link className="font-medium hover:underline" href={href(edge)}>{doc?.label}</Link></TableCell><TableCell>{doc?.owner}</TableCell><TableCell className="capitalize">{edge.relationship_type}</TableCell><TableCell>{Math.round(edge.confidence*100)}%</TableCell><TableCell>{edge.severity ? <SeverityBadge severity={edge.severity} /> : <span className="text-muted-foreground">Not affected</span>}</TableCell><TableCell>{edge.impact_reason ?? edge.change_summary ?? "Dependency evidence available"}</TableCell></TableRow>;})}</TableBody></Table></div></Surface>;
}
