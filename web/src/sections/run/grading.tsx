import type { Run } from "@/lib/types";
import { cn, human, pct } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";

/** Shade a cell by how far below perfect it is; perfect cells stay plain. */
const shade = (x: number) => (x >= 0.9995 ? "" : x >= 0.9 ? "bg-pencil/15" : "bg-redink/15");

export function Grading({ run }: { run: Run }) {
  const g = run.grading!;
  const [lo, hi] = g.accuracy_ci;
  return (
    <Panel title="Graded against the answer key"
      note={<>The answer key is written by the generator and never read by the engine. Accuracy {pct(g.accuracy)} ({g.correct} of {g.graded}),
        95% interval {pct(lo)} to {pct(hi)}. Precision asks how often a label was right when given; recall asks how often a planted defect was found.</>}>
      <div className="scroll-x">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-ink/50 text-left text-graphite">
              <th className="py-2 pr-3 font-medium">Class</th>
              <th className="py-2 pr-3 text-right font-medium">Planted</th>
              <th className="py-2 pr-3 text-right font-medium">Precision</th>
              <th className="py-2 pr-3 text-right font-medium">Recall</th>
              <th className="py-2 text-right font-medium">F1</th>
            </tr>
          </thead>
          <tbody>
            {g.per_class.filter((m) => m.support || m.fp).map((m) => (
              <tr key={m.label} className="border-b border-rule/60">
                <td className="py-1.5 pr-3">{human(m.label)}</td>
                <td className="num py-1.5 pr-3 text-right">{m.support}</td>
                {[m.precision, m.recall, m.f1].map((x, i) => (
                  <td key={i} className={cn("num py-1.5 pr-3 text-right", shade(x))}>{pct(x, 0)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {g.misclassified.length > 0 && (
        <div className="mt-5">
          <h4 className="font-serif text-base font-medium">Where it disagreed with the key</h4>
          <ul className="mt-2 space-y-1 text-sm">
            {g.misclassified.slice(0, 12).map((m) => (
              <li key={m.entity_id} className="text-graphite">
                <span className="font-mono text-[0.8rem] text-ink">{m.entity_id}</span>: expected {human(m.expected)}, said {human(m.got)}
              </li>
            ))}
          </ul>
          <p className="mt-2 max-w-prose text-sm text-graphite">
            On compound batches these are records carrying two defects at once. The taxonomy allows one label per record,
            so the engine names one of them; neither answer is wrong, and the limit is recorded in the README.
          </p>
        </div>
      )}
    </Panel>
  );
}
