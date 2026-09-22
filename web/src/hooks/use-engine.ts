import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, live, type Health } from "@/lib/api";

export type EngineState = "checking" | "live" | "waking" | "offline";

// A free-tier instance is stopped after 15 minutes idle and takes roughly 30
// to 60 seconds to start again. The page keeps asking for that long rather
// than giving up once, because the second ask usually succeeds.
const WAKE_BUDGET_MS = 90_000;
const POLL_MS = 3_000;

export interface Engine {
  state: EngineState;
  health: Health | null;
  /** Seconds spent waiting for a sleeping instance, for the progress text. */
  waitedMs: number;
  /** Try again after giving up. */
  retry: () => void;
  /** Resolves when the engine answers, or rejects if it never does. */
  whenLive: () => Promise<void>;
}

export function useEngine(): Engine {
  const [state, setState] = useState<EngineState>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [waitedMs, setWaited] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const waiters = useRef<{ resolve: () => void; reject: (e: Error) => void }[]>([]);

  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    let timer: number | undefined;

    const settle = (ok: boolean) => {
      const list = waiters.current;
      waiters.current = [];
      list.forEach((w) => (ok ? w.resolve() : w.reject(new Error("The engine did not wake up."))));
    };

    (async () => {
      // index.html starts this request before the bundle loads, so by the
      // time this runs the instance has usually had a head start.
      const first = (window as unknown as { __wake?: Promise<Response> }).__wake;
      if (first) { try { await first; } catch { /* the poll below decides */ } }

      while (!cancelled && Date.now() - started < WAKE_BUDGET_MS) {
        try {
          const h = await live.health(Date.now() - started < 6000 ? 5000 : 20_000);
          if (cancelled) return;
          setHealth(h); setState("live"); settle(true);
          return;
        } catch {
          if (cancelled) return;
          // Nothing to wake when the API is same-origin: it is either up or
          // the page would not have loaded.
          if (!API_BASE) { setState("offline"); settle(false); return; }
          setState("waking");
          setWaited(Date.now() - started);
          await new Promise((r) => { timer = window.setTimeout(r, POLL_MS); });
        }
      }
      if (!cancelled) { setState("offline"); settle(false); }
    })();

    return () => { cancelled = true; window.clearTimeout(timer); settle(false); };
  }, [attempt]);

  const retry = useCallback(() => { setWaited(0); setState("checking"); setAttempt((a) => a + 1); }, []);

  const whenLive = useCallback(() => {
    if (state === "live") return Promise.resolve();
    if (state === "offline") return Promise.reject(new Error("The engine is not reachable."));
    return new Promise<void>((resolve, reject) => { waiters.current.push({ resolve, reject }); });
  }, [state]);

  return { state, health, waitedMs, retry, whenLive };
}
