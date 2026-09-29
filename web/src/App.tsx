import { lazy, Suspense, useCallback, useState } from "react";
import { snapshot } from "@/lib/api";
import type { Run } from "@/lib/types";
import { useData } from "@/hooks/use-data";
import { useEngine } from "@/hooks/use-engine";
import { useHydrated } from "@/hooks/use-hydrated";
import { NavBar } from "@/sections/nav";
import { Hero } from "@/sections/hero";
import { Workbench } from "@/sections/workbench";
import { AgentSection } from "@/sections/agent";
import { HowItWorks } from "@/sections/how";
import { Principles } from "@/sections/principles";
import { Footer } from "@/sections/footer";
import { Skeleton } from "@/components/ui/panel";

// The evidence charts are the only thing on the page that needs recharts at
// the top level, and they sit below the fold. Loading them as a separate
// chunk keeps the chart library off the path to the first paint.
const Evidence = lazy(() => import("@/sections/evidence").then((m) => ({ default: m.Evidence })));

export default function App() {
  const engine = useEngine();
  const meta = useData(snapshot.meta);
  const reference = useData(() => snapshot.dataset("01-reference"));
  const [run, setRun] = useState<Run | null>(null);
  const current = run ?? reference.data;
  const onRun = useCallback((r: Run) => setRun(r), []);
  const hydrated = useHydrated();

  return (
    <>
      <a href="#workbench" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-paper">
        Skip to the workbench
      </a>
      <NavBar engine={engine} />
      <main>
        <Hero reference={reference.data} meta={meta.data} />
        {/* Read in the order a reviewer asks: what it does, try it, is it
            right, where the model fits, and why it is built this way. */}
        <HowItWorks run={reference.data} />
        <Workbench engine={engine} meta={meta.data} run={current} onRun={onRun} />
        {hydrated ? (
          <Suspense fallback={<SectionPlaceholder id="evidence" />}>
            <Evidence meta={meta.data} />
          </Suspense>
        ) : <SectionPlaceholder id="evidence" />}
        <AgentSection engine={engine} />
        <Principles />
      </main>
      <Footer meta={meta.data} />
    </>
  );
}

/** Holds the anchor and roughly the height while a lazy section loads. */
function SectionPlaceholder({ id }: { id: string }) {
  return (
    <section id={id} className="border-b border-rule">
      <div className="mx-auto max-w-page px-5 py-20 sm:px-8 lg:py-28">
        <Skeleton className="h-[40rem] w-full" />
      </div>
    </section>
  );
}
