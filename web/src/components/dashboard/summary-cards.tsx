import { CheckCheck, ClipboardCheck, FileStack, ShieldAlert, Stamp } from "lucide-react";
import { MetricCard } from "@/components/ui/workspace";
import type { DashboardData } from "./types";

export function SummaryCards({ cards }: { cards: DashboardData["cards"] }) {
  return <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-6">
    <div className="sm:col-span-2 lg:col-span-2"><MetricCard emphasized label="Action required" value={cards.action_required} href="/impacts" icon={ShieldAlert} supporting="Prioritised for you" /></div>
    <MetricCard compact label="Review required" value={cards.review_required} href="/impacts" icon={ClipboardCheck} supporting="Open" />
    <MetricCard compact label="Awaiting approval" value={cards.awaiting_approval} href="/impacts" icon={Stamp} supporting="Ready" />
    <MetricCard compact label="Resolved this week" value={cards.resolved_recently} href="/impacts" icon={CheckCheck} supporting="7 days" />
    <MetricCard compact label="Monitored" value={cards.documents_monitored} href="/documents" icon={FileStack} supporting="Documents" />
  </div>;
}
