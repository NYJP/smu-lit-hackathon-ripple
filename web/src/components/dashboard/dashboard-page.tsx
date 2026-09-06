"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, RefreshCw } from "lucide-react";

import { ActivityList } from "./activity-list";
import { GraphPreview } from "./graph-preview";
import { ImpactFeed } from "./impact-feed";
import { SummaryCards } from "./summary-cards";
import type { DashboardData } from "./types";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingSkeleton, PageFrame, PageHeader, SectionHeader, Surface } from "@/components/ui/workspace";
import { api, ApiRequestError } from "@/lib/api";
import { useSession } from "@/lib/session-context";

export function DashboardView() {
  const { user, revision } = useSession();
  const [scope, setScope] = useState<"me" | "all">("me");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.get<DashboardData>(`/dashboard?scope=${scope}&session_rev=${revision}`, { signal });
      if (!signal?.aborted) { setData(result); setError(null); }
    } catch (err) {
      if (!signal?.aborted) setError(err instanceof ApiRequestError ? err.message : "The dashboard could not be loaded.");
    }
  }, [scope, revision]);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => void load(controller.signal));
    return () => controller.abort();
  }, [load]);

  const firstName = user?.display_name.split(/\s+/)[0] ?? "there";
  return <PageFrame>
    <PageHeader title={`Hi, ${firstName}!`} description="Here's what's new today." actions={<div className="flex rounded-lg border p-0.5" aria-label="Dashboard scope"><Button size="sm" variant={scope === "me" ? "secondary" : "ghost"} onClick={() => setScope("me")}>For me</Button><Button size="sm" variant={scope === "all" ? "secondary" : "ghost"} onClick={() => setScope("all")}>All work</Button></div>} />

    {error ? <Surface><EmptyState icon={AlertCircle} title="Dashboard unavailable" description={error} action={<Button variant="outline" onClick={() => void load()}><RefreshCw aria-hidden className="size-4" />Try again</Button>} /></Surface> : !data ? <><LoadingSkeleton rows={2} className="grid sm:grid-cols-2 lg:grid-cols-5" /><Surface><LoadingSkeleton rows={5} /></Surface></> : <>
      <section aria-labelledby="daily-overview" className="space-y-3"><SectionHeader id="daily-overview" title="Daily overview" description={data.cards.action_required ? `${data.cards.action_required} items deserve your attention first.` : "No urgent action is waiting. Your monitored work is up to date."} /><SummaryCards cards={data.cards} /></section>
      <section aria-labelledby="whats-new" className="space-y-3"><SectionHeader id="whats-new" title="What's new today" description="Ranked by severity, your relationship to the document, and due date." /><ImpactFeed items={data.feed} /></section>
      <section aria-label="Secondary context" className="grid items-start gap-4 lg:grid-cols-2"><GraphPreview graph={data.graph_preview} /><ActivityList items={data.activity} /></section>
      <section className="grid items-start gap-4 lg:grid-cols-2">
        <Surface tone="subtle" className="p-4"><SectionHeader title="Recently resolved" description="Closed in the last seven days" />{data.recently_resolved.length ? <ul className="mt-3 divide-y">{data.recently_resolved.map(item => <li key={item.id} className="flex items-start gap-2 py-2.5"><CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-status-done" /><div className="min-w-0"><Link href={`/impacts/${item.id}`} className="text-sm font-medium hover:underline">{item.change_summary}</Link><p className="mt-0.5 truncate text-xs text-muted-foreground">{item.document_name}</p></div></li>)}</ul> : <EmptyState className="min-h-32" icon={CheckCircle2} title="No recent resolutions" description="Completed reviews will collect here." />}</Surface>
        <Surface tone="subtle" className="p-4"><SectionHeader title="Monitoring status" description="Coverage across this dashboard view" /><div className="mt-4 flex items-end justify-between gap-4"><div><p className="text-2xl font-semibold tabular-nums">{data.cards.documents_monitored}</p><p className="mt-1 text-sm text-muted-foreground">documents monitored</p></div><p className="text-right text-xs tabular-nums text-muted-foreground">Last scan<br />{data.last_scan_at ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(data.last_scan_at)) : "Not completed"}</p></div></Surface>
      </section>
    </>}
  </PageFrame>;
}
