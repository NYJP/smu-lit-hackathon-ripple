"use client";

/**
 * Proposed wording: generate it, read the redline, edit it if it is wrong.
 *
 * Two things this component is careful about.
 *
 * First, it never claims the document has been changed. The heading says
 * "proposed", the approved state says "held as an overlay", and the wording a
 * reviewer approves is stored in `document_patches` — never written back into
 * the clause. Getting that language wrong in the UI would make the product
 * lie even though the backend behaves.
 *
 * Second, it shows the *difference*, not two blocks of prose. The generator
 * is prompted for the smallest edit that works (api/services/recommendations.py);
 * if that edit is small, the reviewer should be able to see that at a glance,
 * and if it is not, that itself is the signal to read carefully.
 */

import { useState } from "react";
import { LoaderCircle, Pencil, RotateCcw, Sparkles, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { diffWords, isUnchanged } from "@/lib/diff";
import type { DocumentPatch, RecommendationDetail } from "@/lib/types";

function Redline({ before, after }: { before: string; after: string }) {
  if (isUnchanged(before, after)) {
    return (
      <p className="text-sm text-muted-foreground">
        The proposed wording is identical to the current text.
      </p>
    );
  }
  return (
    <p className="text-sm leading-7">
      {diffWords(before, after).map((token, index) =>
        token.op === "equal" ? (
          <span key={index}>{token.text}</span>
        ) : token.op === "delete" ? (
          <del key={index} className="bg-impact-high/10 text-impact-high decoration-impact-high/60">
            {token.text}
          </del>
        ) : (
          <ins key={index} className="bg-status-done/10 font-medium text-status-done no-underline">
            {token.text}
          </ins>
        ),
      )}
    </p>
  );
}

export interface RedlineEditorProps {
  recommendation: RecommendationDetail | null;
  patch: DocumentPatch | null;
  /** False for a simulated change — a hypothetical must not produce real wording. */
  canGenerate: boolean;
  generating: boolean;
  onGenerate: () => void;
  /** Lifted so the decision bar can approve exactly what is on screen. */
  draft: string;
  onDraftChange: (value: string) => void;
  error: string | null;
}

export function RedlineEditor({
  recommendation,
  patch,
  canGenerate,
  generating,
  onGenerate,
  draft,
  onDraftChange,
  error,
}: RedlineEditorProps) {
  const [editing, setEditing] = useState(false);

  const current = recommendation?.current_text ?? "";
  const suggested = recommendation?.suggested_text ?? "";

  // A regenerate replaces the suggestion, so drop an edit made against the
  // old one rather than silently keeping a draft nobody can now trace. This
  // is the adjust-state-during-render pattern rather than an effect: the
  // reset must be visible in the same render as the new suggestion, or the
  // textarea flashes the previous wording first.
  const [seenSuggestion, setSeenSuggestion] = useState(suggested);
  if (seenSuggestion !== suggested) {
    setSeenSuggestion(suggested);
    setEditing(false);
  }

  const edited = draft !== suggested;

  return (
    <section aria-labelledby="proposed-wording" className="rounded-lg border">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <h2 id="proposed-wording" className="text-sm font-medium">
          Proposed wording
        </h2>
        <div className="flex items-center gap-2">
          {recommendation ? (
            <Button variant="ghost" size="sm" onClick={onGenerate} disabled={generating || !canGenerate}>
              {generating ? (
                <LoaderCircle className="size-3.5 animate-spin" />
              ) : (
                <RotateCcw className="size-3.5" />
              )}
              Regenerate
            </Button>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="border-b border-destructive/30 bg-destructive/5 px-4 py-2.5 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {!recommendation ? (
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            No wording has been proposed for this clause yet.
          </p>
          <Button className="mt-4" onClick={onGenerate} disabled={generating || !canGenerate}>
            {generating ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Generate proposed wording
          </Button>
          {!canGenerate ? (
            <p className="mx-auto mt-3 max-w-md text-xs text-muted-foreground">
              This finding came from a simulation. Promote the simulation first — a hypothetical
              change must not produce wording that could be approved into your documents.
            </p>
          ) : null}
        </div>
      ) : (
        <>
          {recommendation.generation_method === "deterministic_fallback" ? (
            <p className="flex items-start gap-2 border-b border-status-attention/25 bg-status-attention/5 px-4 py-2.5 text-xs text-muted-foreground">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-status-attention" />
              <span>
                The model was unavailable, so this only substitutes the superseded value literally.
                Read it in full before approving.
              </span>
            </p>
          ) : null}

          <div className="px-4 py-4">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {editing ? "Your wording, against the current text" : "Suggested edit"}
            </p>
            <div className="mt-2.5">
              <Redline before={current} after={draft} />
            </div>
          </div>

          <div className="border-t px-4 py-3">
            {editing ? (
              <>
                <label htmlFor="wording-draft" className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Edit the wording
                </label>
                <Textarea
                  id="wording-draft"
                  className="mt-2 min-h-28 text-sm"
                  value={draft}
                  onChange={(event) => onDraftChange(event.target.value)}
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      onDraftChange(suggested);
                      setEditing(false);
                    }}
                  >
                    Discard my edit
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    Approving now records the wording as yours, not the model&apos;s.
                  </span>
                </div>
              </>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  {edited
                    ? "You have edited this wording."
                    : "Approve this as it stands, or edit it first."}
                </p>
                <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                  <Pencil className="size-3.5" />
                  Edit wording
                </Button>
              </div>
            )}
          </div>

          <div className="border-t px-4 py-3">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Why this edit
            </p>
            <p className="mt-2 text-sm leading-6">{recommendation.rationale}</p>
            {recommendation.source_citations.length ? (
              <ul className="mt-3 space-y-2">
                {recommendation.source_citations.map((citation, index) => (
                  <li key={index} className="border-l-2 pl-3 text-xs leading-5 text-muted-foreground">
                    <span className="font-medium capitalize">{citation.source}</span>
                    {citation.section ? ` · ${citation.section}` : ""}
                    <span className="mt-0.5 block italic">“{citation.quote}”</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          {patch ? (
            <footer className="border-t border-status-done/25 bg-status-done/5 px-4 py-3">
              <p className="text-sm font-medium text-status-done">Approved wording is on record</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Approved by {patch.created_by_name}. It is stored as an overlay in Ripple — the
                clause in your uploaded document is unchanged, and the file on disk was never
                touched.
              </p>
            </footer>
          ) : null}
        </>
      )}
    </section>
  );
}
