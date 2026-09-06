import Link from "next/link";
import { CalendarClock, FileText, Sparkles } from "lucide-react";
import { ConfidenceMeter } from "@/components/ui/confidence-meter";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { Button } from "@/components/ui/button";
import type { DashboardFeedItem } from "./types";

function dateLabel(value: string | null) {
  if (!value) return "No due date";
  return `Due ${new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(new Date(value))}`;
}

export function FeedCard({ item }: { item: DashboardFeedItem }) {
  return <li className="group px-4 py-3.5 transition-colors hover:bg-muted/30">
    <div className="min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link href={`/impacts/${item.id}`} className="font-medium leading-5 group-hover:underline">{item.change_summary}</Link>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1"><FileText aria-hidden className="size-3" />{item.document_name}</span>
            <span>{item.clause_label}</span><span className="tabular-nums">{item.affected_clause_count} affected {item.affected_clause_count === 1 ? "clause" : "clauses"}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5"><SeverityBadge severity={item.severity} /><StatusBadge status={item.review_status} label={item.review_status_label} /></div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-1 text-xs font-medium"><Sparkles aria-hidden className="size-3.5 text-muted-foreground" />{item.relevance.reason}</span>
          <ConfidenceMeter compact confidence={item.confidence} severity={item.severity} />
          <span className="inline-flex items-center gap-1 text-xs tabular-nums text-muted-foreground"><CalendarClock aria-hidden className="size-3.5" />{dateLabel(item.due_date)}</span>
        </div>
        <Button asChild size="sm" variant="ghost" className="text-foreground"><Link href={`/impacts/${item.id}`}>{item.next_action}</Link></Button>
      </div>
    </div>
  </li>;
}
