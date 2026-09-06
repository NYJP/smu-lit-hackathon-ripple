import { Activity, CheckCircle2 } from "lucide-react";
import { EmptyState, SectionHeader, Surface } from "@/components/ui/workspace";
import type { DashboardData } from "./types";

export function ActivityList({ items }: { items: DashboardData["activity"] }) {
  return <Surface className="p-4"><SectionHeader title="Team activity" description="Recent work around your matters" />
    {items.length ? <ul className="mt-3 divide-y">{items.map(item => <li key={item.id} className="flex gap-2 py-2.5"><CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-status-done" /><div><p className="text-sm font-medium">{item.title}</p>{item.body ? <p className="mt-0.5 text-xs text-muted-foreground">{item.body}</p> : null}</div></li>)}</ul> : <EmptyState className="min-h-36" icon={Activity} title="Quiet for now" description="Assignments and review decisions will appear here." />}
  </Surface>;
}
