import type { GraphNode } from "@/lib/types";
import { DOC_TYPES } from "./force-graph";

/** Only the document types actually on screen are keyed, so the legend stays
 *  a short row rather than a ten-item wall the reader has to filter mentally. */
export function GraphLegend({ nodes = [] }: { nodes?: GraphNode[] }) {
  const present = [...new Set(nodes.filter(node => node.kind === "document").map(node => node.doc_type ?? "other"))]
    .filter(type => type in DOC_TYPES)
    .sort((a, b) => DOC_TYPES[a].label.localeCompare(DOC_TYPES[b].label));
  return <div aria-label="Graph legend" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-impact-high bg-card" />Impact severity</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full bg-foreground" />Guideline</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-0 border-x-4 border-b-4 border-x-transparent border-b-destructive" />Detected change</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-dashed border-sim bg-card" />Simulation</span>
    {present.length ? <span aria-hidden className="h-3 w-px bg-border" /> : null}
    {present.map(type => <span key={type} className="inline-flex items-center gap-1.5">
      <span
        className="inline-flex size-4.5 items-center justify-center rounded-full text-[8px] font-semibold text-card"
        style={{ background: `var(${DOC_TYPES[type].token})` }}
      >{DOC_TYPES[type].glyph}</span>
      {DOC_TYPES[type].label}
    </span>)}
  </div>;
}
