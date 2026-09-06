"use client";

import { ListFilter, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Surface } from "@/components/ui/workspace";
import type { GraphFilters as State } from "./use-graph-state";

type Team = { id: string; name: string };
const statuses = ["detected", "awaiting_review", "in_review", "needs_analysis", "patch_proposed", "awaiting_approval"];

export function GraphFilters({ state, teams, owners, onChange }: { state: State; teams: Team[]; owners: Array<{id:string;name:string}>; onChange: (v: Partial<State>) => void }) {
  const selectClass = "h-8 rounded-lg border bg-background px-2 text-sm focus-visible:outline-ring";
  const active = state.severity || state.team || state.owner || state.sim || state.q || state.status || state.seed !== "changes";
  const advancedCount = [state.severity,state.team,state.owner,state.status,state.sim].filter(Boolean).length;
  return <Surface tone="subtle" className="p-2.5"><div className="flex flex-wrap items-center gap-2">
    <label className="relative min-w-48 flex-1"><span className="sr-only">Search graph</span><Search aria-hidden className="absolute left-2.5 top-2 size-4 text-muted-foreground" /><Input value={state.q} onChange={e => onChange({ q: e.target.value })} className="pl-8" placeholder="Search nodes" /></label>
    <label><span className="sr-only">Graph seed</span><select data-testid="graph-seed" className={selectClass} value={state.seed} onChange={e => onChange({ seed: e.target.value as State["seed"] })}><option value="changes">Changed</option><option value="mine">Relevant to me</option><option value="all">All dependencies</option></select></label>
    <details className="group relative"><summary className="flex h-8 cursor-pointer list-none items-center gap-1.5 rounded-lg border bg-background px-2.5 text-sm"><ListFilter className="size-3.5" />Filters{advancedCount ? <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{advancedCount}</span> : null}</summary><div className="absolute right-0 z-20 mt-2 grid min-w-56 gap-2 rounded-xl bg-popover p-3 shadow-md ring-1 ring-foreground/10">
      <label><span className="mb-1 block text-xs text-muted-foreground">Severity</span><select data-testid="severity-filter" className={`${selectClass} w-full`} value={state.severity} onChange={e => onChange({ severity: e.target.value })}><option value="">All severities</option>{["critical","high","medium","low","none"].map(v => <option key={v} value={v}>{v[0].toUpperCase()+v.slice(1)}</option>)}</select></label>
      <label><span className="mb-1 block text-xs text-muted-foreground">Review status</span><select className={`${selectClass} w-full`} value={state.status} onChange={e => onChange({status:e.target.value})}><option value="">All open statuses</option>{statuses.map(v => <option key={v} value={v}>{v.replaceAll("_", " ")}</option>)}</select></label>
      <label><span className="mb-1 block text-xs text-muted-foreground">Team</span><select className={`${selectClass} w-full`} value={state.team} onChange={e => onChange({ team: e.target.value })}><option value="">All teams</option>{teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <label><span className="mb-1 block text-xs text-muted-foreground">Owner</span><select className={`${selectClass} w-full`} value={state.owner} onChange={e => onChange({ owner: e.target.value })}><option value="">All owners</option>{owners.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
    </div></details>
    {active ? <Button variant="ghost" size="sm" onClick={() => onChange({ severity:"", team:"", owner:"", status:"", sim:"", q:"", seed:"changes", node:"", mode:"global" })}><X />Clear</Button> : null}
  </div></Surface>;
}
