"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { forceCollide, forceX, forceY } from "d3-force";
import type { ForceGraphMethods } from "react-force-graph-2d";
import type { GraphEdge, GraphNode } from "@/lib/types";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as typeof import("react-force-graph-2d").default;
type CanvasNode = GraphNode & { x?: number; y?: number };
type CanvasEdge = GraphEdge & { source: string | CanvasNode; target: string | CanvasNode };
const endpoint = (v: string | CanvasNode) => typeof v === "string" ? v : v.id;
const radius = (node: CanvasNode) => node.kind === "document" ? 8 + 3 * Math.log2(1 + (node.dependency_count ?? 1)) : node.kind === "requirement" ? 6 : 5;
const docPalette = ["--chart-1","--chart-2","--chart-3","--chart-4","--chart-5","--status-progress","--status-done","--impact-low","--muted-foreground","--primary"];
const hash = (value: string) => [...value].reduce((n,c) => ((n << 5) - n + c.charCodeAt(0)) | 0, 0);

export function ForceGraph({ nodes, edges, selectedId, mode, reducedMotion, onSelect, onOpen }: { nodes: GraphNode[]; edges: GraphEdge[]; selectedId: string; mode: "local" | "global"; reducedMotion: boolean; onSelect: (id: string) => void; onOpen: (node: GraphNode) => void }) {
  const graphRef = useRef<ForceGraphMethods<CanvasNode, CanvasEdge> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const selectedRef = useRef(selectedId);
  const down = useRef({ x: 0, y: 0, at: 0 });
  const dragged = useRef(false);
  const graphData = useMemo(() => ({ nodes: nodes.map(n => ({ ...n })), links: edges.map(e => ({ ...e })) }), [nodes, edges]);
  const neighbours = useMemo(() => { const ids=new Set<string>(); if(selectedId) ids.add(selectedId); for(const e of edges){const s=endpoint(e.source as unknown as CanvasEdge["source"]),t=endpoint(e.target as unknown as CanvasEdge["target"]);if(s===selectedId)ids.add(t);if(t===selectedId)ids.add(s);} return ids; }, [edges, selectedId]);
  const neighboursRef=useRef(neighbours);
  useEffect(() => { selectedRef.current=selectedId; neighboursRef.current=neighbours; }, [selectedId,neighbours]);
  useEffect(() => { const element=containerRef.current;if(!element)return;const observer=new ResizeObserver(([entry])=>setSize({width:Math.max(320,Math.floor(entry.contentRect.width)),height:Math.max(512,Math.floor(entry.contentRect.height))}));observer.observe(element);return()=>observer.disconnect(); },[]);
  useEffect(() => {
    const graph=graphRef.current; if(!graph)return;
    const charge=graph.d3Force("charge"); if(charge && "strength" in charge) (charge as unknown as { strength: (n: number) => unknown }).strength(-60);
    const link=graph.d3Force("link"); if(link && "distance" in link) (link as unknown as { distance: (fn: (edge: CanvasEdge) => number) => unknown }).distance(edge => 18 + 28 * (1-edge.confidence));
    graph.d3Force("collide", forceCollide<CanvasNode>().radius(node => radius(node)+4));
    graph.d3Force("x", forceX<CanvasNode>(0).strength(.06));
    graph.d3Force("y", forceY<CanvasNode>(0).strength(.06));
  }, [graphData, reducedMotion]);
  const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const visible = (node: CanvasNode) => mode === "global" || !selectedRef.current || neighboursRef.current.has(node.id);
  return <div ref={containerRef} className="relative h-[calc(100dvh-15rem)] min-h-[30rem] overflow-hidden bg-muted/15" data-testid="force-graph" data-reduced-motion={reducedMotion} onPointerDownCapture={e => { down.current={x:e.clientX,y:e.clientY,at:performance.now()};dragged.current=false; }} onPointerMoveCapture={e => { if(e.buttons && Math.hypot(e.clientX-down.current.x,e.clientY-down.current.y)>=4)dragged.current=true; }}>
    <ForceGraph2D ref={graphRef} graphData={graphData} width={size.width} height={size.height} warmupTicks={reducedMotion ? 160 : 0} cooldownTicks={reducedMotion ? 0 : 160} onEngineStop={() => graphRef.current?.zoomToFit(220,48)} enableNodeDrag={!reducedMotion}
      nodeRelSize={1} nodeVal={node => radius(node as CanvasNode)}
      linkColor={link => { const e=link as CanvasEdge, selected=selectedRef.current, connected=selected && (endpoint(e.source)===selected || endpoint(e.target)===selected || `doc:${e.document_id}`===selected); return css(connected ? "--foreground" : "--border"); }} linkWidth={link => { const e=link as CanvasEdge, selected=selectedRef.current; return selected && (endpoint(e.source)===selected || endpoint(e.target)===selected || `doc:${e.document_id}`===selected) ? 1.5 : .7; }} linkDirectionalArrowLength={2.5}
      onNodeDrag={() => { dragged.current=true; }} onNodeDragEnd={node => { node.fx=node.x; node.fy=node.y; }}
      onNodeHover={node => setHoveredId((node as CanvasNode | null)?.id ?? null)}
      onNodeClick={(raw,event) => { const node=raw as CanvasNode; const movement=Math.hypot(event.clientX-down.current.x,event.clientY-down.current.y); if(dragged.current || movement>=4 || performance.now()-down.current.at>=300)return; if(selectedRef.current===node.id && node.kind==="document")onOpen(node);else onSelect(node.id); }}
      onBackgroundClick={() => { if(!dragged.current)onSelect(""); }}
      nodeCanvasObject={(raw,ctx,scale) => { const node=raw as CanvasNode, x=node.x??0,y=node.y??0,r=radius(node),dim=!visible(node),selected=node.id===selectedRef.current,hovered=node.id===hoveredId; ctx.save();ctx.globalAlpha=dim?.12:1; const fill=node.kind==="requirement" ? css("--foreground") : node.kind==="section" ? css("--muted-foreground") : css(docPalette[Math.abs(hash(node.doc_type??"other"))%docPalette.length]); if(selected){ctx.beginPath();ctx.arc(x,y,r+6,0,Math.PI*2);ctx.fillStyle=css("--foreground");ctx.globalAlpha=.12;ctx.fill();ctx.globalAlpha=1;} ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=fill;ctx.fill(); if(node.change_source==="simulation"){ctx.setLineDash([3,2]);ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.strokeStyle=css("--sim");ctx.lineWidth=2;ctx.stroke();ctx.setLineDash([]);} else if(node.impact_level && node.impact_level!=="none"){ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.strokeStyle=css(`--impact-${node.impact_level}`);ctx.lineWidth=1.75;ctx.stroke();} if(node.state.startsWith("affected_")){ctx.beginPath();ctx.moveTo(x+r-1,y-r-3);ctx.lineTo(x+r+4,y-r+2);ctx.lineTo(x+r-3,y-r+4);ctx.closePath();ctx.fillStyle=css("--destructive");ctx.fill();} ctx.fillStyle=node.kind==="requirement"?css("--background"):css("--card");ctx.font=`600 ${Math.max(7,r*.7)}px sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(node.kind==="requirement"?"§":(node.doc_type??"D")[0].toUpperCase(),x,y); if(selected||hovered||scale>2.1){ctx.font=`500 ${11/scale}px sans-serif`;ctx.fillStyle=css("--foreground");ctx.fillText(node.label,x,y+r+10/scale);}ctx.restore(); }} />
    <div className="sr-only" aria-label="Graph nodes">{nodes.map(node => <button key={node.id} data-testid={`graph-node-${node.id}`} onClick={() => selectedId===node.id&&node.kind==="document"?onOpen(node):onSelect(node.id)}>{node.label}</button>)}</div>
  </div>;
}
