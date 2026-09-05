"use client";

import { useState } from "react";
import { Database, LoaderCircle, RotateCcw } from "lucide-react";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import { Button } from "@/components/ui/button";

export function SettingsPageContent() {
  const { user } = useSession();
  const [busy, setBusy] = useState<"reset" | "sample" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (user?.role !== "admin") return <div className="mx-auto max-w-2xl py-16 text-sm text-muted-foreground">This page is only available to admin accounts.</div>;

  async function run(action: "reset" | "sample") {
    setBusy(action); setError(null);
    try {
      await api.post(action === "reset" ? "/settings/reset" : "/settings/sample-environment");
      window.location.href = "/who";
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not update the environment.");
      setBusy(null);
    }
  }

  return <div className="mx-auto w-full max-w-6xl px-5 py-8">
    <div><p className="text-sm text-muted-foreground">Local environment</p><h1 className="text-2xl font-semibold tracking-tight">Settings</h1></div>
    <div className="mt-7 max-w-3xl space-y-5">
      <section className="rounded-lg border p-5"><div className="flex gap-3"><RotateCcw className="mt-0.5 size-5 text-destructive" /><div><h2 className="font-medium">Reset environment</h2><p className="mt-1 text-sm text-muted-foreground">Remove all regulations, internal documents, analysis results, uploads, and sessions. The database schema and three default accounts are recreated.</p></div></div>{error ? <p className="mt-3 text-sm text-destructive">{error}</p> : null}<div className="mt-4 flex flex-wrap gap-2"><Button variant="destructive" disabled={busy !== null} onClick={() => void run("reset")}>{busy === "reset" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />}Reset environment</Button></div></section>
      <section className="rounded-lg border p-5"><div className="flex gap-3"><Database className="mt-0.5 size-5" /><div><h2 className="font-medium">Load sample environment</h2><p className="mt-1 text-sm text-muted-foreground">Start clean, then load the bundled regulations, internal documents, extracted requirements, changes, and dependency graph.</p></div></div><Button className="mt-5" disabled={busy !== null} onClick={() => void run("sample")}>{busy === "sample" ? <LoaderCircle className="animate-spin" /> : <Database />}Load sample environment</Button></section>
    </div>
  </div>;
}
