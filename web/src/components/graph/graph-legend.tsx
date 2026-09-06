export function GraphLegend() {
  return <div aria-label="Graph legend" className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-impact-high bg-card" />Impact severity</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full bg-foreground" />Requirement</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-0 border-x-4 border-b-4 border-x-transparent border-b-destructive" />Detected change</span>
    <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-dashed border-sim bg-card" />Simulation</span>
  </div>;
}
