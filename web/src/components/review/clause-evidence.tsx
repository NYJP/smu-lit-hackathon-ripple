"use client";

/**
 * The right pane: the affected clause, in context, with the evidence chain.
 *
 * The acceptance rule this satisfies is "every displayed impact exposes
 * changed provision -> dependency evidence -> affected clause -> document".
 * The dependency's rationale and the clause's own words are both shown, so
 * the reviewer can disagree with the finding on the evidence rather than on
 * trust — and the surrounding clause text stays visible, because a sentence
 * read out of its section is how a wrong edit gets approved.
 */

import Link from "next/link";
import { ArrowUpRight, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ConfidenceMeter } from "@/components/ui/confidence-meter";
import { SeverityBadge } from "@/components/ui/severity-badge";
import { splitSpan } from "@/lib/diff";
import type {
  Contribution,
  Dependency,
  DocumentChunk,
  DocumentPatch,
  Impact,
  PersonRef,
} from "@/lib/types";

function clauseHref(documentId: string, chunk: DocumentChunk, impact: Impact) {
  const query = new URLSearchParams({ chunk: chunk.id });
  if (impact.conflicting_start !== null) query.set("start", String(impact.conflicting_start));
  if (impact.conflicting_end !== null) query.set("end", String(impact.conflicting_end));
  return `/documents/${documentId}?${query.toString()}`;
}

export function ClauseEvidence({
  impact,
  chunk,
  dependency,
  document,
  contributor,
  patch,
}: {
  impact: Impact;
  chunk: DocumentChunk;
  dependency: Dependency;
  document: { id: string; name: string; owner: PersonRef };
  contributor: Contribution | null;
  patch: DocumentPatch | null;
}) {
  // Server-decided (api/services/clauses.py) so the queue, this screen and the
  // document reader never name the same passage differently. The fallbacks are
  // only for a payload predating the field.
  const clauseLabel =
    impact.clause_label ??
    chunk.clause_label ??
    chunk.section_path ??
    chunk.section_title ??
    `Clause ${chunk.ordinal + 1}`;

  const { before, span, after } = splitSpan(
    chunk.content,
    impact.conflicting_start,
    impact.conflicting_end,
  );

  return (
    <section aria-labelledby="affected-clause" className="rounded-lg border">
      <header className="border-b px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 id="affected-clause" className="text-sm font-medium">
              The clause this affects
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {clauseLabel}
              {chunk.page_number ? ` · page ${chunk.page_number}` : ""}
              {contributor?.user ? ` · written by ${contributor.user.display_name}` : ""}
            </p>
          </div>
          <Link
            href={clauseHref(document.id, chunk, impact)}
            className="inline-flex shrink-0 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <FileText className="size-3.5" />
            <span className="max-w-50 truncate">{document.name}</span>
            <ArrowUpRight className="size-3.5" />
          </Link>
        </div>
      </header>

      <div className="px-4 py-4">
        <p className="text-sm leading-7">
          <span className="text-muted-foreground">{before}</span>
          {span ? (
            <mark className="bg-impact-high/15 px-0.5 text-foreground underline decoration-impact-high decoration-2 underline-offset-4">
              {span}
            </mark>
          ) : null}
          <span className="text-muted-foreground">{after}</span>
        </p>
        {!span ? (
          <p className="mt-2 text-xs text-muted-foreground">
            The analysis did not isolate a single sentence, so the whole clause is shown.
          </p>
        ) : null}
        {patch ? (
          <p className="mt-3 rounded-md border border-status-done/25 bg-status-done/5 px-3 py-2 text-xs text-muted-foreground">
            Approved wording is held as an overlay on this passage. The clause above is still
            exactly what the uploaded document says — Ripple does not edit your files.
          </p>
        ) : null}
      </div>

      <div className="border-t px-4 py-3">
        <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Why this clause was flagged
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={impact.severity} withNoun />
          <ConfidenceMeter confidence={impact.confidence} severity={impact.severity} />
        </div>
        <p className="mt-2.5 text-sm leading-6">{impact.reason}</p>
      </div>

      <div className="border-t px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Dependency evidence
          </p>
          <Badge variant="outline" className="capitalize">
            {dependency.relationship_type}
          </Badge>
          <ConfidenceMeter compact confidence={dependency.confidence} />
        </div>
        <p className="mt-2 text-sm leading-6">{dependency.rationale}</p>
        {dependency.evidence_span ? (
          <blockquote className="mt-2 border-l-2 pl-3 text-xs leading-5 text-muted-foreground italic">
            {dependency.evidence_span}
          </blockquote>
        ) : null}
      </div>
    </section>
  );
}
