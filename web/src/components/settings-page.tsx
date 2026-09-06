"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Database, LoaderCircle, RotateCcw } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState, PageFrame, PageHeader, Surface } from "@/components/ui/workspace";

type Scenario = { id: string; label: string; description: string };

export function SettingsPageContent() {
  const { user }=useSession(), router=useRouter();
  const [busy,setBusy]=useState<"reset"|"sample"|null>(null),[error,setError]=useState<string|null>(null),[scenarios,setScenarios]=useState<Scenario[]>([]),[scenarioId,setScenarioId]=useState("pdpf");
  useEffect(()=>{if(user?.role==="admin")api.get<{items:Scenario[]}>("/settings/sample-environments").then(result=>setScenarios(result.items)).catch(()=>setScenarios([]));},[user?.role]);
  if(user?.role!=="admin")return <PageFrame><Surface><EmptyState title="Settings unavailable" description="This page is only available to admin accounts."/></Surface></PageFrame>;
  async function run(action:"reset"|"sample"){setBusy(action);setError(null);try{await api.post(action==="reset"?"/settings/reset":"/settings/sample-environment",action==="sample"?{scenario_id:scenarioId}:undefined);router.push("/who");}catch(err){setError(err instanceof ApiRequestError?err.message:"Could not update the environment.");setBusy(null);}}

  return <PageFrame>
    {busy==="sample"?<div className="fixed inset-0 z-50 grid place-items-center bg-background/95 px-6 backdrop-blur-sm"><div className="w-full max-w-md text-center"><LoaderCircle className="mx-auto size-9 animate-spin"/><h2 className="mt-5 text-xl font-semibold">Building {scenarios.find(s=>s.id===scenarioId)?.label??"sample"} environment</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Loading files, extracting content, creating embeddings, linking dependencies, and calculating impacts.</p></div></div>:null}
    <PageHeader eyebrow="Local environment" title="Settings" description="Manage sample data and this local Ripple workspace." />
    {error?<Surface><EmptyState icon={AlertCircle} title="Environment update failed" description={error}/></Surface>:null}
    <div className="grid items-start gap-4 lg:grid-cols-[1.3fr_1fr]">
      <Surface className="p-5"><div className="flex gap-3"><Database className="mt-0.5 size-5"/><div><h2 className="font-medium">Load sample environment</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">Replace the current workspace with a complete demonstration corpus.</p></div></div><div className="mt-5 max-w-md"><Select value={scenarioId} onValueChange={setScenarioId}><SelectTrigger className="w-full"><SelectValue placeholder="Choose a sample scenario"/></SelectTrigger><SelectContent>{scenarios.map(s=><SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-sm text-muted-foreground">{scenarios.find(s=>s.id===scenarioId)?.description??"Select a bundled scenario."}</p></div><Button className="mt-5" disabled={busy!==null||scenarios.length===0} onClick={()=>void run("sample")}>{busy==="sample"?<LoaderCircle className="animate-spin"/>:<Database/>}Load selected scenario</Button></Surface>
      <Surface tone="subtle" className="p-5"><div className="flex gap-3"><RotateCcw className="mt-0.5 size-5 text-destructive"/><div><h2 className="font-medium">Reset environment</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">Remove regulations, documents, analysis, uploads, and sessions. This cannot be undone.</p></div></div><Button className="mt-5" variant="destructive" disabled={busy!==null} onClick={()=>void run("reset")}>{busy==="reset"?<LoaderCircle className="animate-spin"/>:<RotateCcw/>}Reset environment</Button></Surface>
    </div>
  </PageFrame>;
}
