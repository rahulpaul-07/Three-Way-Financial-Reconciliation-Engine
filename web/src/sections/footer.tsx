import type { Meta } from "@/lib/types";
import { REPO, REPORT, VIDEO, blob } from "./links";

export function Footer({ meta }: { meta: Meta | null }) {
  return (
    <footer className="relative overflow-hidden border-t-8 border-double border-pencil bg-sheet/70">
      <div aria-hidden className="pattern-layer pattern-stripes" />
      <p aria-hidden className="marquee pointer-events-none select-none whitespace-nowrap border-b-4 border-dashed border-magenta bg-paper py-2 font-display text-2xl uppercase text-magenta">
        {Array.from({ length: 12 }, (_, i) => <span key={i} className="px-6">Ledger + Gateway + Bank = Tied</span>)}
      </p>
      <div className="relative mx-auto grid max-w-page gap-8 px-5 py-12 text-sm text-graphite sm:grid-cols-[1.4fr_1fr_1fr] sm:px-8">
        <div className="max-w-sm">
          <p className="ts-1 font-serif text-xl font-black uppercase text-ink">Three-way payment reconciliation engine</p>
          <p className="mt-2">Built by Rahul Paul. Python engine, MIT licensed. Every figure on this page is produced by the engine and its evaluator at build time.</p>
          {meta && (
            <p className="mt-3 text-xs">
              Data built {new Date(meta.generated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} from commit{" "}
              <a className="underline decoration-magenta underline-offset-2 hover:text-ink" href={`${REPO}/commit/${meta.commit}`}>{meta.commit}</a>.
            </p>
          )}
        </div>
        <ul className="space-y-2">
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={REPO}>Source code</a></li>
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={REPORT}>Static HTML report</a></li>
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={VIDEO}>Five-minute walkthrough</a></li>
        </ul>
        <ul className="space-y-2">
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={blob("ARCHITECTURE.md")}>Architecture</a></li>
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={blob("DECISIONS.md")}>Design decisions</a></li>
          <li><a className="font-bold underline decoration-wavy decoration-magenta underline-offset-4 hover:text-pencil" href={blob("NOTES.md")}>Build notes</a></li>
        </ul>
      </div>
    </footer>
  );
}
