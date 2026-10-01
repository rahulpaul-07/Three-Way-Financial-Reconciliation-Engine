import type { Meta } from "@/lib/types";
import { REPO, REPORT, VIDEO, blob } from "./links";

export function Footer({ meta }: { meta: Meta | null }) {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto grid max-w-page gap-8 px-5 py-12 text-sm text-graphite sm:grid-cols-[1.4fr_1fr_1fr] sm:px-8">
        <div className="max-w-sm">
          <p className="font-serif text-base text-ink">Three-way payment reconciliation engine</p>
          <p className="mt-2">Built by Rahul Paul. Python engine, MIT licensed. Every figure on this page is produced by the engine and its evaluator at build time.</p>
          {meta && (
            <p className="mt-3 text-xs">
              Data built {new Date(meta.generated_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })} from commit{" "}
              <a className="underline decoration-rule underline-offset-2 hover:text-ink" href={`${REPO}/commit/${meta.commit}`}>{meta.commit}</a>.
            </p>
          )}
        </div>
        <ul className="space-y-2">
          <li><a className="hover:text-ink" href={REPO}>Source code</a></li>
          <li><a className="hover:text-ink" href={REPORT}>Static HTML report</a></li>
          <li><a className="hover:text-ink" href={VIDEO}>Five-minute walkthrough</a></li>
        </ul>
        <ul className="space-y-2">
          <li><a className="hover:text-ink" href={blob("ARCHITECTURE.md")}>Architecture</a></li>
          <li><a className="hover:text-ink" href={blob("DECISIONS.md")}>Design decisions</a></li>
          <li><a className="hover:text-ink" href={blob("NOTES.md")}>Build notes</a></li>
        </ul>
      </div>
    </footer>
  );
}
