import type { Run } from "@/lib/types";
import { cn, human } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";

export function Detection({ run }: { run: Run }) {
  const d = run.detection!;
  const classes = Object.keys(d.by_class).sort();
  return (
    <Panel title="Defects planted from outside the original taxonomy"
      note="The question asked first is narrow: did the engine refuse to call a broken record clean? A silent pass is the failure that costs money, because nobody looks at it. Two classes are positive controls that prove the grader can see both order-level and transaction-level emissions.">
      <p className="text-sm">
        <span className="num font-serif text-2xl">{d.detected}</span> of <span className="num">{d.total}</span> planted records flagged,{" "}
        <span className="num">{d.named}</span> under their exact name, <span className={cn("num", d.silent ? "text-redink" : "text-tick")}>{d.silent}</span> silent.
      </p>
      <div className="scroll-x mt-4">
        <table className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="border-b border-ink/50 text-left text-graphite">
              <th className="py-2 pr-3 font-medium">Planted defect</th>
              <th className="py-2 pr-3 text-right font-medium">Planted</th>
              <th className="py-2 pr-3 text-right font-medium">Flagged</th>
              <th className="py-2 font-medium">Reported as</th>
            </tr>
          </thead>
          <tbody>
            {classes.map((c) => {
              const s = d.by_class[c];
              const n = Object.values(s).reduce((a, b) => a + b, 0);
              const labels = Object.entries(d.labels[c] ?? {});
              return (
                <tr key={c} className="border-b border-rule/60">
                  <td className="py-1.5 pr-3">{human(c)}</td>
                  <td className="num py-1.5 pr-3 text-right">{n}</td>
                  <td className={cn("num py-1.5 pr-3 text-right", (s.detected ?? 0) < n ? "text-redink" : "text-tick")}>{s.detected ?? 0}</td>
                  <td className="py-1.5 text-graphite">
                    {labels.map(([l, k]) => (
                      <span key={l} className={cn("mr-3", l === c && "text-ink")}>{human(l)}{k > 1 ? ` ×${k}` : ""}</span>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
