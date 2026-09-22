import type { Meta, Run } from "@/lib/types";
import { Summary } from "./summary";
import { MoneyFlow } from "./money-flow";
import { Breakdown } from "./breakdown";
import { Timeline } from "./timeline";
import { Explorer } from "./explorer";
import { Grading } from "./grading";
import { Detection } from "./detection";

export function RunView({ run, meta }: { run: Run; meta: Meta | null }) {
  const title = meta?.datasets.find((d) => d.name === run.source)?.title;
  return (
    <div className="space-y-6">
      <Summary run={run} title={title ? `${title} batch` : run.source} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <MoneyFlow run={run} />
        <Breakdown run={run} />
      </div>
      <Timeline run={run} />
      <Explorer run={run} />
      {run.detection && <Detection run={run} />}
      {run.grading && <Grading run={run} />}
    </div>
  );
}
