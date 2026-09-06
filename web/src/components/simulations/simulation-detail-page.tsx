"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CircleStop,
  FlaskConical,
  Play,
  Save,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SeverityBadge, SeverityCounts } from "@/components/ui/severity-badge";
import { SimulatedBadge } from "@/components/ui/status-badge";
import {
  EmptyState,
  LoadingSkeleton,
  MetricCard,
  PageFrame,
  PageHeader,
  SectionHeader,
  Surface,
} from "@/components/ui/workspace";
import { api, ApiRequestError } from "@/lib/api";
import type {
  GraphResponse,
  Job,
  Severity,
  SimulationDetail,
} from "@/lib/types";
import { useRippleAnimation } from "./use-ripple-animation";

const stageLabels: Record<string, string> = {
  queued: "Queued",
  preparing_simulation: "Preparing hypothetical changes",
  evaluating_dependencies: "Evaluating dependent clauses",
  summarizing_results: "Summarizing the ripple",
  completed: "Analysis complete",
  failed: "Analysis failed",
};
const severityClass: Record<Severity, string> = {
  critical: "border-impact-critical",
  high: "border-impact-high",
  medium: "border-impact-medium",
  low: "border-impact-low",
  none: "border-border",
};

export function SimulationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<SimulationDetail | null>(null),
    [graph, setGraph] = useState<GraphResponse | null>(null),
    [job, setJob] = useState<Job | null>(null),
    [error, setError] = useState("");
  const [name, setName] = useState(""),
    [proposed, setProposed] = useState("");
  const load = useCallback(async () => {
    const detail = await api.get<SimulationDetail>(`/simulations/${id}`);
    setData(detail);
    setName(detail.simulation.name);
    setProposed(detail.edits[0]?.proposed_value ?? "");
    if (detail.simulation.status === "complete")
      setGraph(
        await api.get<GraphResponse>(`/graph?simulation_id=${id}&seed=all`),
      );
  }, [id]);
  useEffect(() => {
    queueMicrotask(
      () =>
        void load().catch((err) =>
          setError(
            err instanceof ApiRequestError
              ? err.message
              : "Could not load this simulation.",
          ),
        ),
    );
  }, [load]);
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "running")) return;
    const timer = setInterval(async () => {
      const next = await api.get<Job>(`/jobs/${job.id}`);
      setJob(next);
      if (next.status === "succeeded") {
        await load();
      }
      if (next.status === "failed")
        setError(next.error_message ?? "Simulation failed.");
    }, 400);
    return () => clearInterval(timer);
  }, [job, load]);
  const targets = useMemo(
    () => graph?.nodes.filter((node) => node.kind === "document") ?? [],
    [graph],
  );
  const ripple = useRippleAnimation(
    targets.length,
    Boolean(graph && data?.simulation.status === "complete"),
  );
  if (error && !data)
    return (
      <PageFrame>
        <Surface>
          <EmptyState title="Simulation unavailable" description={error} />
        </Surface>
      </PageFrame>
    );
  if (!data)
    return (
      <PageFrame>
        <Surface>
          <LoadingSkeleton rows={6} />
        </Surface>
      </PageFrame>
    );
  const detail = data,
    edit = detail.edits[0],
    counts = {
      high: detail.totals.high,
      medium: detail.totals.medium,
      low: detail.totals.low,
    };
  async function save() {
    await api.patch(`/simulations/${id}`, {
      name,
      edits: detail.edits.map((item, index) => ({
        lineage_id: item.lineage_id,
        op: item.op,
        proposed_requirement_text: item.proposed_requirement_text,
        proposed_value: index === 0 ? proposed : item.proposed_value,
        proposed_value_numeric:
          index === 0
            ? Number.parseFloat(proposed)
            : item.proposed_value_numeric,
        proposed_value_unit: item.proposed_value_unit,
      })),
    });
    await load();
  }
  async function run() {
    setError("");
    await save();
    const estimate = await api.post<{
      dependency_count: number;
      cached_count: number;
      estimated_cost_usd: number;
    }>(`/simulations/${id}/estimate`);
    if (
      !window.confirm(
        `Evaluate ${estimate.dependency_count} dependencies (${estimate.cached_count} cached) · estimated $${estimate.estimated_cost_usd.toFixed(4)}?`,
      )
    )
      return;
    const started = await api.post<{ job_id: string }>(
      `/simulations/${id}/run`,
    );
    setGraph(null);
    setJob(await api.get<Job>(`/jobs/${started.job_id}`));
  }
  async function discard() {
    await api.delete(`/simulations/${id}`);
    router.replace("/simulations");
  }
  return (
    <PageFrame className="max-w-7xl">
      <Link
        href="/simulations"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Simulations
      </Link>
      <PageHeader
        eyebrow={<SimulatedBadge />}
        title={data.simulation.name}
        description="Hypothetical only — nothing in your requirements, uploaded files, or documents has changed."
        actions={
          <>
            <Button variant="outline" onClick={() => void save()}>
              <Save />
              Save
            </Button>
            <Button
              onClick={() => void run()}
              disabled={job?.status === "queued" || job?.status === "running"}
            >
              <Play />
              Run simulation
            </Button>
          <Button variant="outline" className="border-destructive/30 text-destructive" onClick={() => void discard()}>
              <Trash2 />
              Discard
            </Button>
          </>
        }
      />
      <Surface className="border-sim/30 bg-sim/5 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <SimulatedBadge />
          <p className="text-sm font-medium">
            Simulation overlay — real records remain unchanged.
          </p>
        </div>
      </Surface>
      <Surface className="p-4">
        <SectionHeader
          title="Hypothetical edit"
          description={edit?.public_ref ?? "Requirement"}
        />
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Current
            </p>
            <p className="mt-2 text-sm leading-6">
              {edit?.current_requirement_text}
            </p>
            <p className="mt-2 font-medium">{edit?.current_value ?? "—"}</p>
          </div>
          <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Proposed
            <Input
              className="mt-2 normal-case"
              value={proposed}
              onChange={(event) => setProposed(event.target.value)}
            />
            <span className="mt-2 block normal-case text-sim">
              Simulated value
            </span>
          </label>
        </div>
      </Surface>
      {job ? (
        <Surface className="p-4" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="font-medium">
                {stageLabels[job.step ?? "queued"] ?? job.step}
              </p>
              <p className="text-sm text-muted-foreground">
                {Math.round(job.progress * 100)}% · job {job.id.slice(0, 8)}
              </p>
            </div>
            {job.status === "failed" ? (
              <Button variant="outline" onClick={() => void run()}>
                Retry
              </Button>
            ) : null}
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-sim transition-[width]"
              style={{ width: `${job.progress * 100}%` }}
            />
          </div>
        </Surface>
      ) : null}
      {graph ? (
        <section aria-labelledby="ripple-heading">
          <SectionHeader
            id="ripple-heading"
            title="Ripple path"
            description="The purple origin reaches each dependent document before the final impact rings settle."
            action={
              ripple.phase !== "settled" && !ripple.reducedMotion ? (
                <Button variant="outline" onClick={ripple.skip}>
                  <CircleStop />
                  Skip animation
                </Button>
              ) : undefined
            }
          />
          <Surface
            className="mt-3 p-4"
            data-testid="ripple"
            data-phase={ripple.phase}
            data-reduced-motion={ripple.reducedMotion}
          >
            <div className="flex items-center gap-3">
              <div
                className={`grid size-12 shrink-0 place-items-center rounded-full border-2 border-sim bg-sim/10 text-sim ${ripple.phase === "origin" ? "animate-ripple-pulse" : ""}`}
              >
                <FlaskConical className="size-5" />
              </div>
              <div className="min-w-0 flex-1 space-y-3">
                {targets.map((target, index) => (
                  <div
                    key={target.id}
                    className="relative flex min-w-0 items-center gap-3"
                  >
                    <span className="h-px min-w-8 flex-1 bg-border">
                      {ripple.phase === "travelling" &&
                      index === ripple.arrived ? (
                        <span
                          data-testid="travelling-dot"
                          className="block size-2 -translate-y-1/2 animate-ripple-travel rounded-full bg-sim"
                        />
                      ) : null}
                    </span>
                    <div
                      data-testid="ripple-target"
                      className={`flex min-w-44 max-w-72 items-center gap-2 border-l-4 p-2 ${index < ripple.arrived ? severityClass[target.impact_level ?? "none"] : "border-border"} ${ripple.phase === "arriving" && index === ripple.arrived - 1 ? "animate-ripple-pulse" : ""}`}
                    >
                      <SimulatedBadge />
                      <span className="truncate text-sm font-medium">
                        {target.label}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Surface>
        </section>
      ) : null}
      {graph && ripple.phase === "settled" ? (
        <section aria-labelledby="summary-heading">
          <SectionHeader
            id="summary-heading"
            title="Simulation summary"
            description="Final hypothetical impact across the current dependency map."
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <MetricCard
              label="Documents examined"
              value={data.totals.documents_examined}
              href={`/graph?sim=${id}`}
              icon={FlaskConical}
            />
            <MetricCard
              label="Affected"
              value={data.totals.affected_documents}
              href={`/graph?sim=${id}`}
              icon={FlaskConical}
            />
            <MetricCard
              label="Likely unaffected"
              value={data.totals.likely_unaffected}
              href={`/graph?sim=${id}`}
              icon={FlaskConical}
            />
          </div>
          <Surface className="mt-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <SeverityCounts counts={counts} />
              <span className="text-sm text-muted-foreground">
                Confidence{" "}
                {data.impacts.length
                  ? Math.round(
                      (data.impacts.reduce(
                        (sum, item) => sum + item.confidence,
                        0,
                      ) /
                        data.impacts.length) *
                        100,
                    )
                  : 0}
                %
              </span>
            </div>
          </Surface>
          <div className="mt-3 grid gap-3">
            {data.impacts
              .filter((item) => item.impact_level !== "none")
              .map((item) => (
                <Surface key={item.id} className="p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <SimulatedBadge />
                    <SeverityBadge severity={item.severity} withNoun />
                    <Link
                      href={`/documents/${item.document_id}?chunk=${item.document_chunk_id}&start=${item.conflicting_start ?? ""}&end=${item.conflicting_end ?? ""}`}
                      className="font-medium hover:underline"
                    >
                      {item.document_name}
                    </Link>
                  </div>
                  <p className="mt-2 text-sm">
                    {item.clause_label} · {item.reason}
                  </p>
                </Surface>
              ))}
          </div>
        </section>
      ) : null}
    </PageFrame>
  );
}
