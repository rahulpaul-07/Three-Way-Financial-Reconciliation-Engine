import { useEffect, useState } from "react";
import { API_BASE, live, type Health } from "@/lib/api";

export type EngineState = "checking" | "live" | "waking" | "offline";

/**
 * Is the live engine reachable? A free-tier instance sleeps when idle and
 * takes about half a minute to wake, so a first miss against a remote API is
 * followed by one patient retry before the page settles on recorded data.
 */
export function useEngine() {
  const [state, setState] = useState<EngineState>("checking");
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await live.health(5000);
        if (!cancelled) { setHealth(h); setState("live"); }
        return;
      } catch { /* fall through */ }
      if (!API_BASE) { if (!cancelled) setState("offline"); return; }
      if (!cancelled) setState("waking");
      try {
        const h = await live.health(60_000);
        if (!cancelled) { setHealth(h); setState("live"); }
      } catch {
        if (!cancelled) setState("offline");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return { state, health };
}
