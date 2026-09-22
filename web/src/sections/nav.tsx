import { Github } from "lucide-react";
import type { EngineState } from "@/hooks/use-engine";
import { cn } from "@/lib/utils";
import { REPO } from "./links";

const STATUS: Record<EngineState, { text: string; dot: string; title: string }> = {
  checking: { text: "Checking engine", dot: "bg-graphite animate-pulse", title: "Looking for the live engine" },
  live: { text: "Engine live", dot: "bg-tick", title: "Runs, uploads and generated batches use the live engine" },
  waking: { text: "Engine waking", dot: "bg-pencil animate-pulse", title: "The free-tier instance is starting; this takes about 30 seconds" },
  offline: { text: "Recorded data", dot: "bg-graphite", title: "The live engine is unreachable, so the page shows recorded runs" },
};

export function NavBar({ engine }: { engine: EngineState }) {
  const s = STATUS[engine];
  return (
    <header className="sticky top-0 z-40 border-b border-rule/80 bg-paper/90 backdrop-blur"
      style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <nav className="mx-auto flex h-14 max-w-page items-center gap-6 px-5 sm:px-8" aria-label="Main">
        <a href="#top" className="flex items-center gap-2 font-serif text-[1.05rem] font-semibold">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="6" className="fill-ink" />
            <path d="M8 17l5 5 11-12" className="stroke-paper" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="hidden sm:inline">Three-way reconciliation</span>
          <span className="sm:hidden">Recon</span>
        </a>
        <div className="ml-auto hidden items-center gap-5 text-sm text-graphite md:flex">
          <a className="hover:text-ink" href="#workbench">Workbench</a>
          <a className="hover:text-ink" href="#evidence">Evidence</a>
          <a className="hover:text-ink" href="#agent">Agent</a>
          <a className="hover:text-ink" href="#how">How it works</a>
        </div>
        <span title={s.title} className="ml-auto flex items-center gap-2 text-xs text-graphite md:ml-0">
          <span className={cn("h-2 w-2 rounded-full", s.dot)} aria-hidden />
          {s.text}
        </span>
        <a href={REPO} className="text-graphite hover:text-ink" aria-label="Source on GitHub">
          <Github size={18} />
        </a>
      </nav>
    </header>
  );
}
