import { Network } from "lucide-react";
import { EmptyState, InlineAction, SectionHeader, Surface } from "@/components/ui/workspace";
import { SeverityBadge } from "@/components/ui/severity-badge";
import type { DashboardData } from "./types";

export function GraphPreview({ graph }: { graph: DashboardData["graph_preview"] }) {
  return <Surface className="p-4"><SectionHeader title="Dependency preview" description={`${graph.nodes.length} connected items`} action={<InlineAction href="/graph">Open graph</InlineAction>} />
    {graph.nodes.length ? <div className="mt-4 grid gap-2 sm:grid-cols-2">{graph.nodes.slice(0, 8).map(node => <div key={node.id} className="flex min-w-0 items-center gap-2 rounded-lg bg-muted/50 px-3 py-2"><span className="size-2 shrink-0 rounded-full bg-foreground" /><span className="min-w-0 flex-1 truncate text-xs font-medium">{node.label}</span><SeverityBadge severity={node.severity} /></div>)}</div> : <EmptyState className="min-h-36" icon={Network} title="No active connections" description="Connections will appear as impacts are detected." />}
  </Surface>;
}
