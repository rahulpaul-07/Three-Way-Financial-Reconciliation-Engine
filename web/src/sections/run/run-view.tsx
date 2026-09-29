import { useState } from "react";
import type { Meta, Run } from "@/lib/types";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import { Summary } from "./summary";
import { MoneyFlow } from "./money-flow";
import { Breakdown } from "./breakdown";
import { Timeline } from "./timeline";
import { Explorer } from "./explorer";
import { Grading } from "./grading";
import { Detection } from "./detection";

type View = "overview" | "daily" | "exceptions" | "grading";
const ID = "run-view";

/**
 * One reconciled batch. The summary stays in view; the detail is split into
 * tabs, because each view answers a different question and stacking all of
 * them made the page several screens long.
 */
export function RunView({ run, meta }: { run: Run; meta: Meta | null }) {
  const title = meta?.datasets.find((d) => d.name === run.source)?.title;
  const hasGrading = !!(run.grading || run.detection);
  const [picked, setPicked] = useState<View>("overview");
  // A batch without an answer key has no grading tab; fall back rather than
  // show an empty panel after switching batches.
  const view: View = picked === "grading" && !hasGrading ? "overview" : picked;

  const items: { value: View; label: string; count?: number }[] = [
    { value: "overview", label: "Overview" },
    { value: "daily", label: "Day by day" },
    { value: "exceptions", label: "Exceptions", count: run.summary.unresolved },
  ];
  if (hasGrading) items.push({ value: "grading", label: run.grading ? "Graded" : "Detection" });

  return (
    <div className="space-y-8">
      <Summary run={run} title={title ? `${title} batch` : run.source} />
      <div>
        <Tabs label="Views of this batch" idBase={ID} items={items} value={view} onChange={setPicked} />
        <TabPanel idBase={ID} value={view} className="pt-6">
          {view === "overview" && (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
              <MoneyFlow run={run} />
              <Breakdown run={run} />
            </div>
          )}
          {view === "daily" && <Timeline run={run} />}
          {view === "exceptions" && <Explorer run={run} />}
          {view === "grading" && (
            <div className="space-y-6">
              {run.detection && <Detection run={run} />}
              {run.grading && <Grading run={run} />}
            </div>
          )}
        </TabPanel>
      </div>
    </div>
  );
}
