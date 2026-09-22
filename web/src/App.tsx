import { useCallback, useState } from "react";
import { snapshot } from "@/lib/api";
import type { Run } from "@/lib/types";
import { useData } from "@/hooks/use-data";
import { useEngine } from "@/hooks/use-engine";
import { NavBar } from "@/sections/nav";
import { Hero } from "@/sections/hero";
import { Workbench } from "@/sections/workbench";
import { Evidence } from "@/sections/evidence";
import { AgentSection } from "@/sections/agent";
import { HowItWorks } from "@/sections/how";
import { Footer } from "@/sections/footer";

export default function App() {
  const engine = useEngine();
  const meta = useData(snapshot.meta);
  const reference = useData(() => snapshot.dataset("01-reference"));
  const [run, setRun] = useState<Run | null>(null);
  const current = run ?? reference.data;
  const onRun = useCallback((r: Run) => setRun(r), []);

  return (
    <>
      <a href="#workbench" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-paper">
        Skip to the workbench
      </a>
      <NavBar engine={engine.state} />
      <main>
        <Hero reference={reference.data} meta={meta.data} />
        <Workbench engine={engine} meta={meta.data} run={current} onRun={onRun} />
        <Evidence meta={meta.data} />
        <AgentSection engine={engine} />
        <HowItWorks />
      </main>
      <Footer meta={meta.data} />
    </>
  );
}
