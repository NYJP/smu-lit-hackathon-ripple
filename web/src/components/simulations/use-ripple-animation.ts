"use client";

import { useCallback, useEffect, useState } from "react";

export type RipplePhase = "idle" | "origin" | "travelling" | "arriving" | "settled";
const STAGE_MS = 300;

export function useRippleAnimation(targetCount: number, active: boolean) {
  const [phase, setPhase] = useState<RipplePhase>("idle");
  const [arrived, setArrived] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const skip = useCallback(() => { setArrived(targetCount); setPhase("settled"); }, [targetCount]);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(query.matches);
    sync(); query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!active) { queueMicrotask(() => { setPhase("idle"); setArrived(0); }); return; }
    if (reducedMotion || targetCount === 0) { queueMicrotask(skip); return; }
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const later = (fn: () => void, delay: number) => timers.push(setTimeout(() => { if (!cancelled) fn(); }, delay));
    queueMicrotask(() => setPhase("origin"));
    later(() => setPhase("travelling"), STAGE_MS);
    for (let index = 0; index < targetCount; index += 1) {
      later(() => { setPhase("arriving"); setArrived(index + 1); }, STAGE_MS * (index + 2));
    }
    later(() => setPhase("settled"), STAGE_MS * (targetCount + 2) + STAGE_MS / 2);
    return () => { cancelled = true; timers.forEach(clearTimeout); };
  }, [active, reducedMotion, skip, targetCount]);

  return { phase, arrived, reducedMotion, skip };
}
