"use client";

import { useCallback, useEffect, useState } from "react";

export type GraphMode = "local" | "global";
export type GraphFilters = { mode: GraphMode; node: string; sim: string; severity: string; team: string; owner: string; status: string; q: string; seed: "changes" | "mine" | "all" };

const read = (): GraphFilters => {
  const p = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
  return { mode: p.get("mode") === "local" ? "local" : "global", node: p.get("node") ?? "", sim: p.get("sim") ?? "", severity: p.get("severity") ?? "", team: p.get("team") ?? "", owner: p.get("owner") ?? "", status: p.get("status") ?? "", q: p.get("q") ?? "", seed: p.get("seed") === "mine" || p.get("seed") === "all" ? p.get("seed") as "mine" | "all" : "changes" };
};

export function useGraphState() {
  const [state, setState] = useState<GraphFilters>(read);
  useEffect(() => { const restore = () => setState(read()); window.addEventListener("popstate", restore); return () => window.removeEventListener("popstate", restore); }, []);
  const update = useCallback((patch: Partial<GraphFilters>, replace = false) => {
    const next = { ...state, ...patch };
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) if (value && !((key === "mode" && value === "global") || (key === "seed" && value === "changes"))) params.set(key, value);
    window.history[replace ? "replaceState" : "pushState"](null, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
    setState(next);
  }, [state]);
  return { state, update };
}
