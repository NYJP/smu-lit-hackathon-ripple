"use client";

import { useEffect, useState } from "react";
import { Database, LoaderCircle, RotateCcw } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Scenario = { id: string; label: string; description: string };

export function SettingsPageContent() {
  const { user } = useSession();
  const [busy, setBusy] = useState<"reset" | "sample" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("pdpf");

  useEffect(() => {
    if (user?.role === "admin") api.get<{ items: Scenario[] }>("/settings/sample-environments").then((result) => setScenarios(result.items)).catch(() => setScenarios([]));
  }, [user?.role]);

  if (user?.role !== "admin") return <div className="mx-auto max-w-2xl py-16 text-sm text-muted-foreground">This page is only available to admin accounts.</div>;

  async function run(action: "reset" | "sample") {
    setBusy(action); setError(null);
    try {
      await api.post(action === "reset" ? "/settings/reset" : "/settings/sample-environment", action === "sample" ? { scenario_id: scenarioId } : undefined);
      window.location.href = "/who";
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not update the environment.");
      setBusy(null);
    }
  }

  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    {busy === "sample" ? <div className="fixed inset-0 z-50 grid place-items-center bg-background/95 px-6 backdrop-blur-sm"><div className="w-full max-w-md text-center"><LoaderCircle className="mx-auto size-9 animate-spin" /><h2 className="mt-5 text-xl font-semibold">Building {scenarios.find((scenario) => scenario.id === scenarioId)?.label ?? "sample"} environment</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Loading files, extracting content, creating embeddings, linking dependencies, and calculating impacts. The viewer will open only after every stage is complete.</p><div className="mt-6 grid grid-cols-2 gap-2 text-left text-xs text-muted-foreground"><span className="rounded-md border px-3 py-2">Regulations and files</span><span className="rounded-md border px-3 py-2">Requirements</span><span className="rounded-md border px-3 py-2">Vector embeddings</span><span className="rounded-md border px-3 py-2">Dependencies and impacts</span></div></div></div> : null}
    <div><p className="text-sm text-muted-foreground">Local environment</p><h1 className="text-2xl font-semibold tracking-tight">Settings</h1></div>
    {error ? <p className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p> : null}
    <div className="mt-7 max-w-3xl space-y-5">
      <section className="rounded-lg border p-5"><div className="flex gap-3"><RotateCcw className="mt-0.5 size-5 text-destructive" /><div><h2 className="font-medium">Reset environment</h2><p className="mt-1 text-sm text-muted-foreground">Remove all regulations, internal documents, analysis results, uploads, and sessions. The database schema and three default accounts are recreated.</p></div></div><div className="mt-4 flex flex-wrap gap-2"><Button variant="destructive" disabled={busy !== null} onClick={() => void run("reset")}>{busy === "reset" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />}Reset environment</Button></div></section>
      <section className="rounded-lg border p-5"><div className="flex gap-3"><Database className="mt-0.5 size-5" /><div><h2 className="font-medium">Load sample environment</h2><p className="mt-1 text-sm text-muted-foreground">Choose a scenario to replace the current environment with its regulations, documents, requirements, changes, and dependency graph.</p></div></div><div className="mt-5 max-w-md"><Select value={scenarioId} onValueChange={setScenarioId}><SelectTrigger className="w-full"><SelectValue placeholder="Choose a sample scenario" /></SelectTrigger><SelectContent>{scenarios.map((scenario) => <SelectItem key={scenario.id} value={scenario.id}>{scenario.label}</SelectItem>)}</SelectContent></Select><p className="mt-2 text-sm text-muted-foreground">{scenarios.find((scenario) => scenario.id === scenarioId)?.description ?? "Select a bundled scenario."}</p></div><Button className="mt-5" disabled={busy !== null || scenarios.length === 0} onClick={() => void run("sample")}>{busy === "sample" ? <LoaderCircle className="animate-spin" /> : <Database />}Load selected scenario</Button></section>
    </div>
  </div>;
}
