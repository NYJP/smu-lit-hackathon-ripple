"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { forceCollide, forceX, forceY } from "d3-force";
import type { ForceGraphMethods } from "react-force-graph-2d";
import type { GraphEdge, GraphNode } from "@/lib/types";

type CanvasNode = GraphNode & { x?: number; y?: number };
type CanvasEdge = GraphEdge & { source: string | CanvasNode; target: string | CanvasNode };
const endpoint = (v: string | CanvasNode) => typeof v === "string" ? v : v.id;
// A document node is sized by how many requirements depend on it: log, so a
// hub reads as bigger without swamping the map, and clamped at both ends so
// nothing degenerates into a dot or a planet. Requirement and section nodes
// are fixed -- their size carries no meaning, so varying it would be noise.
const radius = (node: CanvasNode) => node.kind === "document" ? Math.min(19, 10 + 2.4 * Math.log2(1 + (node.dependency_count ?? 0))) : node.kind === "requirement" ? 7.5 : 6;
// Widest thing painted around a node: the selection halo at r + 6. Collision
// and link distance both work off this, not the bare radius, which is why
// nodes used to visibly intersect.
const painted = (node: CanvasNode) => radius(node) + 6;

// Every document type gets its own two-letter code and colour. Single letters
// collided (policy/playbook, template/training, checklist/clause_library),
// which is what made the glyphs unreadable as a key. DOC_TYPES is exported so
// the legend renders from exactly this table and cannot drift from it.
export const DOC_TYPES: Record<string, { glyph: string; token: string; label: string }> = {
  policy:         { glyph: "PO", token: "--doc-policy",         label: "Policy" },
  playbook:       { glyph: "PB", token: "--doc-playbook",       label: "Playbook" },
  sop:            { glyph: "SO", token: "--doc-sop",            label: "SOP" },
  template:       { glyph: "TP", token: "--doc-template",       label: "Template" },
  clause_library: { glyph: "CL", token: "--doc-clause-library", label: "Clause library" },
  checklist:      { glyph: "CK", token: "--doc-checklist",      label: "Checklist" },
  opinion:        { glyph: "OP", token: "--doc-opinion",        label: "Opinion" },
  advisory:       { glyph: "AD", token: "--doc-advisory",       label: "Advisory" },
  training:       { glyph: "TR", token: "--doc-training",       label: "Training" },
  other:          { glyph: "OT", token: "--doc-other",          label: "Other" },
};
const docType = (value: string | null | undefined) => DOC_TYPES[value ?? "other"] ?? DOC_TYPES.other;
type Box = { left: number; top: number; right: number; bottom: number };
const overlaps = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

/** Labels are painted in a single pass after every node, for two reasons: a
 *  label drawn inside nodeCanvasObject is overpainted by whichever nodes are
 *  drawn after it, and collisions can only be avoided if one pass owns the
 *  whole set. Nodes are visited in priority order -- selected, hovered, then
 *  largest first -- so when two labels compete for the same space the more
 *  important one keeps it and the other is simply not drawn. */
function drawLabels(ctx: CanvasRenderingContext2D, scale: number, nodes: CanvasNode[], selectedId: string, hoveredId: string | null, visible: (node: CanvasNode) => boolean, css: (name: string) => string) {
  // Size floor is in graph units, not screen pixels, so a label grows with the
  // zoom instead of shrinking to a speck beside a node filling the canvas --
  // and it is identical for every node, so a big document does not get a
  // bigger caption than the requirement next to it.
  const size = Math.max(11 / scale, 2.6), padX = size * .45, padY = size * .3;
  ctx.font = `500 ${size}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const priority = (node: CanvasNode) => node.id === selectedId ? 3 : node.id === hoveredId ? 2 : node.kind === "document" ? 1 : 0;
  // Every node is an obstacle, so a label is never laid over a circle -- but a
  // label must be allowed to sit under its OWN node, which it always touches.
  const nodeBoxes = new Map(nodes.map(node => {
    const x = node.x ?? 0, y = node.y ?? 0, extent = painted(node);
    return [node.id, { left: x - extent, top: y - extent, right: x + extent, bottom: y + extent }] as const;
  }));
  const boxes: Box[] = [];
  for (const node of [...nodes].sort((a, b) => priority(b) - priority(a) || radius(b) - radius(a))) {
    const forced = node.id === selectedId || node.id === hoveredId;
    const x = node.x ?? 0, y = node.y ?? 0;
    // Sit below the painted extent so the label clears this node's own impact
    // ring, selection halo, and affected marker.
    const width = ctx.measureText(node.label).width, top = y + painted(node) + 2 + 4 / scale;
    const box = { left: x - width / 2 - padX, top: top - padY, right: x + width / 2 + padX, bottom: top + size + padY };
    const blocked = boxes.some(existing => overlaps(existing, box))
      || [...nodeBoxes].some(([id, nodeBox]) => id !== node.id && overlaps(nodeBox, box));
    if (!forced && blocked) continue;
    boxes.push(box);
    const dim = !visible(node);
    ctx.globalAlpha = dim ? .12 : .92;
    ctx.fillStyle = css("--background");
    ctx.beginPath();
    ctx.roundRect(box.left, box.top, box.right - box.left, box.bottom - box.top, size * .35);
    ctx.fill();
    ctx.globalAlpha = dim ? .12 : 1;
    ctx.fillStyle = css("--foreground");
    ctx.fillText(node.label, x, top);
  }
  ctx.globalAlpha = 1;
}

export function ForceGraph({ nodes, edges, selectedId, mode, reducedMotion, onSelect, onOpen }: { nodes: GraphNode[]; edges: GraphEdge[]; selectedId: string; mode: "local" | "global"; reducedMotion: boolean; onSelect: (id: string) => void; onOpen: (node: GraphNode) => void }) {
  const graphRef = useRef<ForceGraphMethods<CanvasNode, CanvasEdge> | undefined>(undefined);
  // The canvas library is browser-only and so must be imported lazily. Doing it
  // here rather than through next/dynamic gives a state transition we can
  // depend on: until it resolves there is no child to hold graphRef, so the
  // force-configuring effect below would bail on mount and never re-run,
  // silently leaving the graph on the library's default forces.
  const [ForceGraph2D, setForceGraph2D] = useState<typeof import("react-force-graph-2d").default | null>(null);
  useEffect(() => { let live = true; void import("react-force-graph-2d").then(module => { if (live) setForceGraph2D(() => module.default); }); return () => { live = false; }; }, []);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const selectedRef = useRef(selectedId);
  const down = useRef({ x: 0, y: 0, at: 0 });
  const dragged = useRef(false);
  const graphData = useMemo(() => ({ nodes: nodes.map(n => ({ ...n })), links: edges.map(e => ({ ...e })) }), [nodes, edges]);
  const neighbours = useMemo(() => { const ids=new Set<string>(); if(selectedId) ids.add(selectedId); for(const e of edges){const s=endpoint(e.source as unknown as CanvasEdge["source"]),t=endpoint(e.target as unknown as CanvasEdge["target"]);if(s===selectedId)ids.add(t);if(t===selectedId)ids.add(s);} return ids; }, [edges, selectedId]);
  const neighboursRef=useRef(neighbours);
  const hoveredRef=useRef<string|null>(null);
  useEffect(() => { selectedRef.current=selectedId; neighboursRef.current=neighbours; }, [selectedId,neighbours]);
  useEffect(() => { hoveredRef.current=hoveredId; }, [hoveredId]);
  useEffect(() => { const element=containerRef.current;if(!element)return;const observer=new ResizeObserver(([entry])=>setSize({width:Math.max(320,Math.floor(entry.contentRect.width)),height:Math.max(512,Math.floor(entry.contentRect.height))}));observer.observe(element);return()=>observer.disconnect(); },[]);
  useEffect(() => {
    const graph=graphRef.current; if(!graph)return;
    const charge=graph.d3Force("charge"); if(charge && "strength" in charge) (charge as unknown as { strength: (n: number) => unknown }).strength(-260);
    // Link distance is measured centre to centre, so it has to clear both
    // radii before the confidence spacing is added -- a flat 18 pulled large
    // nodes straight through each other.
    const link=graph.d3Force("link"); if(link && "distance" in link) (link as unknown as { distance: (fn: (edge: CanvasEdge) => number) => unknown }).distance(edge => { const ends=[edge.source,edge.target].map(v => typeof v === "object" ? painted(v) : 16); return ends[0]+ends[1]+16+26*(1-edge.confidence); });
    // Links pull hard enough to drag nodes through each other, so soften them
    // and let collision own the minimum spacing.
    if(link && "strength" in link) (link as unknown as { strength: (n: number) => unknown }).strength(.25);
    graph.d3Force("collide", forceCollide<CanvasNode>().radius(node => painted(node)+5).strength(1).iterations(6));
    graph.d3Force("x", forceX<CanvasNode>(0).strength(.03));
    graph.d3Force("y", forceY<CanvasNode>(0).strength(.03));
    // Swapping forces onto an already-cooled simulation changes nothing until
    // it is reheated -- without this the collision force above never ran, which
    // is why nodes were still drawn overlapping.
    graph.d3ReheatSimulation();
  }, [ForceGraph2D, graphData, reducedMotion]);
  const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const visible = (node: CanvasNode) => mode === "global" || !selectedRef.current || neighboursRef.current.has(node.id);
  return <div ref={containerRef} className="relative h-[calc(100dvh-15rem)] min-h-[30rem] overflow-hidden bg-muted/15" data-testid="force-graph" data-reduced-motion={reducedMotion} onPointerDownCapture={e => { down.current={x:e.clientX,y:e.clientY,at:performance.now()};dragged.current=false; }} onPointerMoveCapture={e => { if(e.buttons && Math.hypot(e.clientX-down.current.x,e.clientY-down.current.y)>=4)dragged.current=true; }}>
    {ForceGraph2D ? <ForceGraph2D ref={graphRef} graphData={graphData} width={size.width} height={size.height} warmupTicks={reducedMotion ? 420 : 0} cooldownTicks={reducedMotion ? 0 : 420} onEngineStop={() => graphRef.current?.zoomToFit(220,48)} enableNodeDrag={!reducedMotion}
      nodeRelSize={1} nodeVal={node => radius(node as CanvasNode)}
      linkColor={link => { const e=link as CanvasEdge, selected=selectedRef.current, connected=selected && (endpoint(e.source)===selected || endpoint(e.target)===selected || `doc:${e.document_id}`===selected); return css(connected ? "--foreground" : "--border"); }} linkWidth={link => { const e=link as CanvasEdge, selected=selectedRef.current; return selected && (endpoint(e.source)===selected || endpoint(e.target)===selected || `doc:${e.document_id}`===selected) ? 1.5 : .7; }} linkDirectionalArrowLength={2.5}
      onRenderFramePost={(ctx,scale) => drawLabels(ctx as CanvasRenderingContext2D, scale, graphData.nodes as CanvasNode[], selectedRef.current, hoveredRef.current, visible, css)}
      onNodeDrag={() => { dragged.current=true; }} onNodeDragEnd={node => { node.fx=node.x; node.fy=node.y; }}
      onNodeHover={node => setHoveredId((node as CanvasNode | null)?.id ?? null)}
      onNodeClick={(raw,event) => { const node=raw as CanvasNode; const movement=Math.hypot(event.clientX-down.current.x,event.clientY-down.current.y); if(dragged.current || movement>=4 || performance.now()-down.current.at>=300)return; if(selectedRef.current===node.id && node.kind==="document")onOpen(node);else onSelect(node.id); }}
      onBackgroundClick={() => { if(!dragged.current)onSelect(""); }}
      nodeCanvasObject={(raw,ctx,scale) => { const node=raw as CanvasNode, x=node.x??0,y=node.y??0,r=radius(node),dim=!visible(node),selected=node.id===selectedRef.current,hovered=node.id===hoveredId; ctx.save();ctx.globalAlpha=dim?.12:1; const fill=node.kind==="requirement" ? css("--foreground") : node.kind==="section" ? css("--muted-foreground") : css(docType(node.doc_type).token); if(selected){ctx.beginPath();ctx.arc(x,y,r+6,0,Math.PI*2);ctx.fillStyle=css("--foreground");ctx.globalAlpha=.12;ctx.fill();ctx.globalAlpha=1;} ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill(); if(node.change_source==="simulation"){ctx.setLineDash([3,2]);ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.strokeStyle=css("--sim");ctx.lineWidth=2;ctx.stroke();ctx.setLineDash([]);} else if(node.impact_level && node.impact_level!=="none"){ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.strokeStyle=css(`--impact-${node.impact_level}`);ctx.lineWidth=1.75;ctx.stroke();} if(node.state.startsWith("affected_")){ctx.beginPath();ctx.moveTo(x+r-1,y-r-3);ctx.lineTo(x+r+4,y-r+2);ctx.lineTo(x+r-3,y-r+4);ctx.closePath();ctx.fillStyle=css("--destructive");ctx.fill();} if(node.kind==="document"){ctx.fillStyle=css("--card");ctx.font=`600 ${Math.max(6,r*.55)}px sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(docType(node.doc_type).glyph,x,y);} ctx.restore(); }} /> : null}
    <div className="sr-only" aria-label="Graph nodes">{nodes.map(node => <button key={node.id} data-testid={`graph-node-${node.id}`} onClick={() => selectedId===node.id&&node.kind==="document"?onOpen(node):onSelect(node.id)}>{node.label}</button>)}</div>
  </div>;
}
