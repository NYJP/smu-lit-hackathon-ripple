"use client";

/**
 * The left pane of the review screen: what the regulator actually changed.
 *
 * PRD section 10.3 requires the regulatory source to sit beside the affected
 * clause, verbatim and attributable — a reviewer must never have to take our
 * word for what the rule now says. So this shows the old and new requirement
 * text, the literal old -> new value where the change carried one, and a link
 * back to the source PDF at its section.
 */

import Link from "next/link";
import { ArrowRight, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SourceBadge } from "@/components/ui/status-badge";
import { diffWords } from "@/lib/diff";
import type { RegulatoryChange, Requirement } from "@/lib/types";

/**
 * Extraction often stores the unit inside the value ("5 years") *and* in
 * `value_unit`, so naively joining them prints "5 years years". Append the
 * unit only when the value does not already carry it.
 */
function formatValue(value: string, unit: string | null): string {
  if (!unit) return value;
  return value.toLowerCase().includes(unit.toLowerCase()) ? value : `${value} ${unit}`;
}

function RedlineText({ before, after }: { before: string; after: string }) {
  return (
    <p className="text-sm leading-6">
      {diffWords(before, after).map((token, index) =>
        token.op === "equal" ? (
          <span key={index}>{token.text}</span>
        ) : token.op === "delete" ? (
          <del key={index} className="bg-impact-high/10 text-impact-high decoration-impact-high/60">
            {token.text}
          </del>
        ) : (
          <ins key={index} className="bg-status-done/10 text-status-done no-underline">
            {token.text}
          </ins>
        ),
      )}
    </p>
  );
}

function Panel({
  label,
  requirement,
  tone,
}: {
  label: string;
  requirement: Requirement | null;
  tone: "previous" | "current";
}) {
  return (
    <div className="rounded-lg border p-4">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      {requirement ? (
        <>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="capitalize">
              {requirement.requirement_type}
            </Badge>
            {requirement.source_section ? (
              <span className="text-xs text-muted-foreground">{requirement.source_section}</span>
            ) : null}
            {requirement.value ? (
              <span className="text-xs tabular-nums text-muted-foreground">
                {formatValue(requirement.value, requirement.value_unit)}
              </span>
            ) : null}
          </div>
          <p
            className={
              tone === "previous"
                ? "mt-3 text-sm leading-6 text-muted-foreground"
                : "mt-3 text-sm leading-6"
            }
          >
            {requirement.requirement_text}
          </p>
          {requirement.verbatim_text ? (
            <blockquote className="mt-3 border-l-2 pl-3 text-xs leading-5 text-muted-foreground italic">
              {requirement.verbatim_text}
            </blockquote>
          ) : null}
        </>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          No requirement was recorded for this version.
        </p>
      )}
    </div>
  );
}

export function RequirementDiff({
  change,
  regulation,
  previous,
  proposed,
}: {
  change: RegulatoryChange;
  regulation: { id: string; title: string } | null;
  previous: Requirement | null;
  proposed: Requirement | null;
}) {
  const section = proposed?.source_section ?? previous?.source_section ?? change.source_section;

  return (
    <section aria-labelledby="regulatory-source" className="rounded-lg border">
      <header className="border-b px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="regulatory-source" className="text-sm font-medium">
            What changed in the regulation
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="capitalize">
              {change.change_type.replaceAll("_", " ")}
            </Badge>
            <SourceBadge source={change.source} />
          </div>
        </div>
        <p className="mt-1.5 text-sm">{change.summary}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {section ?? "Source section unavailable"}
          {change.effective_date ? ` · Effective ${change.effective_date}` : " · No stated effective date"}
        </p>
      </header>

      {change.old_value || change.new_value ? (
        <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3 text-sm">
          <span className="rounded-md bg-impact-high/10 px-2 py-1 font-medium text-impact-high line-through decoration-impact-high/50">
            {change.old_value ?? "not stated"}
          </span>
          <ArrowRight aria-label="becomes" className="size-4 text-muted-foreground" />
          <span className="rounded-md bg-status-done/10 px-2 py-1 font-medium text-status-done">
            {change.new_value ?? "not stated"}
          </span>
        </div>
      ) : null}

      <div className="grid gap-4 p-4 md:grid-cols-2">
        <Panel label="Previous requirement" requirement={previous} tone="previous" />
        <Panel label="New requirement" requirement={proposed} tone="current" />
      </div>

      {previous?.requirement_text && proposed?.requirement_text ? (
        <div className="border-t px-4 py-3">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Redline
          </p>
          <div className="mt-2">
            <RedlineText before={previous.requirement_text} after={proposed.requirement_text} />
          </div>
        </div>
      ) : null}

      {regulation ? (
        <footer className="border-t px-4 py-3">
          <Link
            href={
              section
                ? `/regulations/${regulation.id}?section=${encodeURIComponent(section)}`
                : `/regulations/${regulation.id}`
            }
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="size-3.5" />
            Read {regulation.title} in the source PDF
          </Link>
        </footer>
      ) : null}
    </section>
  );
}
