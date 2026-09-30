import { motion, useScroll, useSpring } from "framer-motion";
import { Github } from "lucide-react";
import { useEffect, useState } from "react";
import type { Engine, EngineState } from "@/hooks/use-engine";
import { cn } from "@/lib/utils";
import { REPO } from "./links";

const STATUS: Record<EngineState, { text: string; dot: string; title: string }> = {
  checking: { text: "Checking engine", dot: "bg-graphite animate-pulse", title: "Looking for the live engine" },
  live: { text: "Engine live", dot: "bg-tick", title: "Runs, uploads and generated batches use the live engine" },
  waking: { text: "Engine starting", dot: "bg-pencil animate-pulse", title: "The free-tier instance sleeps when idle and takes 30 to 60 seconds to start. Recorded runs work meanwhile." },
  offline: { text: "Recorded data", dot: "bg-graphite", title: "The live engine is unreachable, so the page shows recorded runs" },
};

const LINKS = [
  { id: "how", label: "How it works" },
  { id: "workbench", label: "Workbench" },
  { id: "evidence", label: "Evidence" },
  { id: "agent", label: "Agent" },
  { id: "principles", label: "Principles" },
];

/**
 * The section being read: the last one whose top has passed under the
 * header. Looked up by id on each check rather than held, because sections
 * mount late (the evidence chunk loads lazily and replaces its placeholder).
 */
function useActiveSection(ids: string[]) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    let frame = 0;
    const check = () => {
      frame = 0;
      const line = 120; // a little below the 56px header
      let current: string | null = null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= line) current = id;
      }
      setActive(current);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(check); };
    check();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [ids]);
  return active;
}

const IDS = LINKS.map((l) => l.id);

export function NavBar({ engine }: { engine: Engine }) {
  // How far down the ledger you are, drawn as a rule under the header.
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.3 });
  const active = useActiveSection(IDS);
  const s = STATUS[engine.state];
  const seconds = Math.round(engine.waitedMs / 1000);
  return (
    <header className="sticky top-0 z-40 border-b-[3px] border-double border-rule bg-paper/95 backdrop-blur"
      style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <nav className="mx-auto flex h-14 max-w-page items-center gap-6 px-5 sm:px-8" aria-label="Main">
        <a href="#top" className="flex items-center gap-2.5 font-serif text-[1.1rem] font-medium">
          {/* A clerk's seal: the audit tick inside a double-ruled square. */}
          <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" className="fill-ink" />
            <rect x="2.5" y="2.5" width="27" height="27" fill="none" className="stroke-paper/40" strokeWidth="1" />
            <path d="M8 17l5 5 11-12" className="stroke-paper" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="hidden sm:inline">Three-way reconciliation</span>
          <span className="sm:hidden">Recon</span>
        </a>
        <div className="ml-auto hidden items-center gap-1 text-sm lg:flex">
          {LINKS.map((l) => (
            <a key={l.id} href={`#${l.id}`} aria-current={active === l.id ? "location" : undefined}
              className={cn("relative rounded px-2.5 py-1.5 transition-colors",
                active === l.id ? "text-ink" : "text-graphite hover:text-ink")}>
              {l.label}
              {active === l.id && (
                <motion.span layoutId="nav-active" aria-hidden
                  className="absolute inset-x-2.5 -bottom-[0.7rem] h-0.5 bg-redink"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }} />
              )}
            </a>
          ))}
        </div>
        <span title={s.title} aria-live="polite"
          className="ml-auto flex items-center gap-2 border border-rule bg-sheet px-2.5 py-1 text-xs text-graphite lg:ml-2">
          <span className={cn("h-2 w-2 rounded-full", s.dot)} aria-hidden />
          {s.text}
          {engine.state === "waking" && seconds > 2 && <span className="num">{seconds}s</span>}
          {engine.state === "offline" && (
            <button onClick={engine.retry} className="underline underline-offset-2 hover:text-ink">
              Try again
            </button>
          )}
        </span>
        <a href={REPO} className="text-graphite hover:text-ink" aria-label="Source on GitHub">
          <Github size={18} />
        </a>
      </nav>
      <motion.div aria-hidden style={{ scaleX: progress }}
        className="h-px origin-left bg-brass" />
    </header>
  );
}
