"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FlaskConical, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SimulatedBadge } from "@/components/ui/status-badge";
import {
  EmptyState,
  LoadingSkeleton,
  PageFrame,
  PageHeader,
  Surface,
} from "@/components/ui/workspace";
import { api, ApiRequestError } from "@/lib/api";
import type { SimulationListItem } from "@/lib/types";

type RequirementOption = {
  lineage_id: string;
  public_ref: string;
  requirement_text: string;
  value: string | null;
};

export function SimulationsPage() {
  const router = useRouter();
  const [items, setItems] = useState<SimulationListItem[] | null>(null);
  const [requirements, setRequirements] = useState<RequirementOption[]>([]);
  const [name, setName] = useState("PDPF retention consultation");
  const [lineage, setLineage] = useState("");
  const [value, setValue] = useState("7 years");
  const [error, setError] = useState("");
  const load = () =>
    api
      .get<{ items: SimulationListItem[] }>("/simulations")
      .then((result) => setItems(result.items));
  useEffect(() => {
    queueMicrotask(() => {
      void load();
      api
        .get<{ items: RequirementOption[] }>("/requirements?limit=200")
        .then((result) => {
          setRequirements(result.items);
          setLineage((current) => current || result.items[0]?.lineage_id || "");
        });
    });
  }, []);
  async function create() {
    setError("");
    try {
      const result = await api.post<{ simulation_id: string }>("/simulations", {
        name,
        edits: [{ lineage_id: lineage, op: "modify", proposed_value: value }],
      });
      router.push(`/simulations/${result.simulation_id}`);
    } catch (err) {
      setError(
        err instanceof ApiRequestError
          ? err.message
          : "Could not create the simulation.",
      );
    }
  }
  async function discard(id: string) {
    await api.delete(`/simulations/${id}`);
    await load();
  }
  return (
    <PageFrame>
      <PageHeader
        eyebrow={
          <span className="inline-flex items-center gap-2">
            <FlaskConical className="size-4" />
            What-if workspace
          </span>
        }
        title="Simulations"
        description="Explore hypothetical regulatory changes without altering a guideline or document."
      />
      <Surface className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-52 flex-1 text-sm font-medium">
            Name
            <Input
              className="mt-1"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="min-w-56 flex-[2] text-sm font-medium">
            Requirement
            <select
              aria-label="Requirement"
              className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm"
              value={lineage}
              onChange={(event) => setLineage(event.target.value)}
            >
              {requirements.map((item) => (
                <option key={item.lineage_id} value={item.lineage_id}>
                  {item.public_ref} · {item.value ?? item.requirement_text}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-36 text-sm font-medium">
            Proposed value
            <Input
              className="mt-1"
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <Button onClick={create} disabled={!lineage || !name.trim()}>
            <Plus />
            New simulation
          </Button>
        </div>
        {error ? (
          <p className="mt-3 text-sm text-destructive">{error}</p>
        ) : null}
      </Surface>
      {!items ? (
        <Surface>
          <LoadingSkeleton />
        </Surface>
      ) : !items.length ? (
        <Surface>
          <EmptyState
            icon={FlaskConical}
            title="No simulations yet"
            description="Create a what-if above to see its ripple across dependent documents."
          />
        </Surface>
      ) : (
        <Surface className="divide-y overflow-hidden">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center gap-4 p-4"
            >
              <SimulatedBadge />
              <div className="min-w-48 flex-1">
                <Link
                  href={`/simulations/${item.id}`}
                  className="font-medium hover:underline"
                >
                  {item.name}
                </Link>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.edit_count} edit · {item.affected_document_count ?? 0}{" "}
                  affected documents ·{" "}
                  {new Date(item.created_at).toLocaleDateString()}
                </p>
              </div>
              <span className="capitalize text-sm text-muted-foreground">
                {item.status}
              </span>
              <Link
                className="text-sm font-medium text-primary hover:underline"
                href={`/simulations/${item.id}`}
              >
                Open
              </Link>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Discard ${item.name}`}
                onClick={() => void discard(item.id)}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </Surface>
      )}
    </PageFrame>
  );
}
