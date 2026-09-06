import type { DocType, ReviewStatus, Severity } from "@/lib/types";

export interface DashboardFeedItem {
  id: string; document_id: string; document_name: string; doc_type: DocType;
  change_summary: string; clause_label: string; affected_clause_count: number;
  severity: Severity; confidence: number; relevance: { reason: string; weight: number };
  due_date: string | null; review_status: ReviewStatus; review_status_label: string;
  next_action: string;
}
export interface DashboardData {
  scope: "me" | "all";
  cards: { action_required: number; review_required: number; awaiting_approval: number; resolved_recently: number; documents_monitored: number };
  feed: DashboardFeedItem[];
  graph_preview: { nodes: { id: string; kind: string; label: string; severity: Severity }[]; edges: { source: string; target: string; confidence: number }[] };
  recently_resolved: { id: string; document_name: string; change_summary: string; resolved_at: string }[];
  activity: { id: string; title: string; body: string | null; created_at: string; read_at: string | null }[];
  last_scan_at: string | null;
}
