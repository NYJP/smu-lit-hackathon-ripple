"use client";

/**
 * Honest placeholder for a route whose backend is still a 501 stub
 * (see the wave README). Rather than hard-coding wave text that could
 * drift from the API, this calls the real endpoint and renders whatever
 * `api/errors.py: not_implemented()` actually says — the single source of
 * truth for "which build-order wave this arrives in." No fabricated
 * lists, counts, or sample findings (see the wave brief).
 */

import { useEffect, useState } from "react";

import { api, ApiRequestError } from "@/lib/api";

interface NotBuiltYetProps {
  title: string;
  /** The list endpoint this page will eventually render, e.g. "/documents". */
  endpoint: string;
}

export function NotBuiltYet({ title, endpoint }: NotBuiltYetProps) {
  const [message, setMessage] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"not-implemented" | "other" | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get(endpoint)
      .then(() => {
        // Nothing in this wave returns 200 from a stubbed route. If that
        // ever changes, this page will simply say so plainly rather than
        // silently rendering nothing.
        if (!cancelled) {
          setErrorKind("other");
          setMessage("This endpoint now returns data, but the page that renders it has not been built yet.");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiRequestError && err.isNotImplemented) {
          setErrorKind("not-implemented");
          setMessage(err.message);
        } else if (err instanceof ApiRequestError) {
          setErrorKind("other");
          setMessage(err.message);
        } else {
          setErrorKind("other");
          setMessage("Could not reach the Ripple API.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [endpoint]);

  return (
    <div className="mx-auto max-w-2xl py-16">
      <h1 className="text-xl font-medium">{title}</h1>
      <div className="mt-6 rounded-md border border-dashed p-6 text-sm">
        {message === null ? (
          <p className="text-muted-foreground">Checking {endpoint}…</p>
        ) : (
          <>
            <p className="font-medium">
              {errorKind === "not-implemented" ? "Not built yet" : "Unavailable"}
            </p>
            <p className="mt-2 text-muted-foreground">{message}</p>
          </>
        )}
      </div>
    </div>
  );
}
