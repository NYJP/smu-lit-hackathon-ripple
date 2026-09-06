import { CircleCheck } from "lucide-react";
import { EmptyState, Surface } from "@/components/ui/workspace";
import { FeedCard } from "./feed-card";
import type { DashboardFeedItem } from "./types";

export function ImpactFeed({ items }: { items: DashboardFeedItem[] }) {
  return <Surface className="overflow-hidden">{items.length ? <ul className="divide-y">{items.map(item => <FeedCard key={item.id} item={item} />)}</ul> : <EmptyState icon={CircleCheck} title="You're up to date" description="There are no open impacts in this view. Your monitored documents remain under watch." />}</Surface>;
}
