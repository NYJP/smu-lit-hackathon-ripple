"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Network, RotateCcw, Table2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { EmptyState, LoadingSkeleton, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";
import { api } from "@/lib/api";
import type { GraphNode, GraphResponse } from "@/lib/types";
import { ForceGraph } from "./force-graph";
import { GraphFilters } from "./graph-filters";
import { GraphInspector } from "./graph-inspector";
import { GraphLegend } from "./graph-legend";
import { GraphTable } from "./graph-table";
import { useGraphState } from "./use-graph-state";

type Team = { id: string; name: string };
const endpoint = (v: unknown) => typeof v === "string" ? v : (v as {id?:string})?.id ?? "";

export function DependencyGraph() {
  const router=useRouter(), { state, update }=useGraphState();
  const [data,setData]=useState<GraphResponse|null>(null), [error,setError]=useState(""), [teams,setTeams]=useState<Team[]>([]), [view,setView]=useState("graph"), [reset,setReset]=useState(0);
  const [narrow,setNarrow]=useState(false);
  const reducedMotion=typeof window!=="undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => { const media=window.matchMedia("(max-width: 1023px)"), sync=()=>setNarrow(media.matches);sync();media.addEventListener("change",sync);return()=>media.removeEventListener("change",sync); }, []);
  useEffect(() => { api.get<{items:Team[]}>("/teams").then(v=>setTeams(v.items)).catch(()=>setTeams([])); }, []);
  useEffect(() => {
    const controller=new AbortController(), params=new URLSearchParams({limit:"250",seed:state.seed});
    if(state.severity)params.set("severity",state.severity);if(state.team)params.set("team_id",state.team);if(state.owner)params.set("owner_id",state.owner);if(state.status)params.set("review_status",state.status);if(state.sim)params.set("simulation_id",state.sim);
    queueMicrotask(() => { setError(""); api.get<GraphResponse>(`/graph?${params}`,{signal:controller.signal}).then(setData).catch(e=>{if(e?.name!=="AbortError")setError("The dependency graph could not be loaded.");}); });
    return () => controller.abort();
  }, [state.seed,state.severity,state.team,state.owner,state.status,state.sim]);
  const shown=useMemo(() => { if(!data)return null; const term=state.q.trim().toLowerCase(); if(!term)return data; const ids=new Set(data.nodes.filter(n=>n.label.toLowerCase().includes(term)||n.owner?.toLowerCase().includes(term)||n.requirement_text?.toLowerCase().includes(term)).map(n=>n.id)); const edges=data.edges.filter(e=>ids.has(endpoint(e.source))||ids.has(endpoint(e.target))||ids.has(`doc:${e.document_id}`)); for(const e of edges){ids.add(endpoint(e.source));ids.add(endpoint(e.target));ids.add(`doc:${e.document_id}`);} return {...data,nodes:data.nodes.filter(n=>ids.has(n.id)),edges}; },[data,state.q]);
  const selected=shown?.nodes.find(n=>n.id===state.node) ?? null;
  const owners=useMemo(() => { const map=new Map<string,string>();for(const n of data?.nodes??[])if(n.owner_id&&n.owner)map.set(n.owner_id,n.owner);return [...map].map(([id,name])=>({id,name})); },[data]);
  const select=(id:string) => update({node:id,mode:id?"local":"global"});
  const open=(node:GraphNode) => router.push(`/documents/${node.id.slice(4)}`);
  return <PageFrame className="max-w-[96rem]"><PageHeader eyebrow="Relationship map" title="Dependency graph" description="Trace how regulatory change reaches internal documents." />
    <div className="flex flex-wrap items-center justify-between gap-3"><GraphLegend nodes={shown?.nodes} /><Button variant="outline" size="sm" onClick={()=>setReset(v=>v+1)}><RotateCcw />Re-centre</Button></div>
    <GraphFilters state={state} teams={teams} owners={owners} onChange={update} />
    {error ? <Surface><EmptyState title="Graph unavailable" description={error} action={<Button onClick={()=>setReset(v=>v+1)}>Try again</Button>} /></Surface> : !shown ? <Surface><LoadingSkeleton rows={6} /></Surface> : !shown.nodes.length ? <Surface><EmptyState title="No dependencies found" description="Adjust the filters or choose all dependencies." /></Surface> : <>
      <Tabs value={view} onValueChange={setView}><TabsList><TabsTrigger value="graph"><Network />Visual graph</TabsTrigger><TabsTrigger value="table"><Table2 />Table view</TabsTrigger></TabsList>
        <TabsContent value="graph"><div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_19rem]"><Surface className="overflow-hidden"><ForceGraph key={reset} nodes={shown.nodes} edges={shown.edges} selectedId={state.node} mode={state.mode} reducedMotion={reducedMotion} onSelect={select} onOpen={open} /></Surface><aside className="sticky top-20 hidden self-start lg:block"><GraphInspector selected={selected} nodes={shown.nodes} edges={shown.edges} /></aside></div>
          <Sheet open={narrow && Boolean(selected)} onOpenChange={openState=>{if(narrow&&!openState)select("");}}><SheetContent className="lg:hidden"><SheetHeader><SheetTitle>Node details</SheetTitle><SheetDescription>Connected evidence and actions.</SheetDescription></SheetHeader><div className="overflow-y-auto"><GraphInspector embedded selected={selected} nodes={shown.nodes} edges={shown.edges} /></div></SheetContent></Sheet>
        </TabsContent>
        <TabsContent value="table"><GraphTable nodes={shown.nodes} edges={shown.edges} onSelect={select} /></TabsContent>
      </Tabs>
      <p aria-live="polite" className="text-xs text-muted-foreground">{shown.nodes.length} nodes · {shown.edges.length} links{shown.truncated.nodes_omitted ? ` · ${shown.truncated.nodes_omitted} nodes and ${shown.truncated.edges_omitted} links omitted` : ""}{shown.hidden_document_count ? ` · ${shown.hidden_document_count} documents hidden by the cap` : ""}</p>
    </>}
  </PageFrame>;
}
