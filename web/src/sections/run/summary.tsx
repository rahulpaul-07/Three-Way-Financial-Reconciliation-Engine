import type { Run } from "@/lib/types";
import { int, pct, rupees } from "@/lib/utils";
import { NumberTicker } from "@/components/ui/number-ticker";

export function Summary({ run, title }: { run: Run; title: string }) {
  const s = run.summary;
  const [lo, hi] = s.resolution_ci;
  const items: { label: string; value: React.ReactNode; note: string }[] = [
    { label: "Examined", value: <NumberTicker value={s.entities} format={int} />,
      note: `${int(run.sources.orders)} orders, ${int(run.sources.txns)} gateway rows, ${int(run.sources.bank)} bank lines` },
    { label: "Resolved", value: <NumberTicker value={s.resolution_rate} format={(x) => pct(x)} />,
      note: `95% interval ${pct(lo)} to ${pct(hi)}` },
    { label: "Sent to a person", value: <NumberTicker value={s.unresolved} format={int} />,
      note: "each with a reason; none dropped" },
    { label: "Money in breaks", value: <NumberTicker value={s.exposure_paise} format={(x) => rupees(Math.round(x), { compact: true })} />,
      note: `${s.by_severity.break ?? 0} records where money is missing or unexplained` },
  ];
  if (run.grading) {
    items.push({ label: "Matches the answer key", value: <NumberTicker value={run.grading.accuracy} format={(x) => pct(x)} />,
      note: `${run.grading.correct} of ${run.grading.graded} graded records` });
  }
  items.push({ label: "Engine time", value: <span className="num">{run.engine_ms < 1 ? "<1" : run.engine_ms.toFixed(1)} ms</span>,
    note: "matching only, excluding file parsing" });

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-serif text-2xl">{title}</h3>
        <span className="text-sm text-graphite">
          reconciled {new Date(run.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
        </span>
      </div>
      <dl className="totals mt-4 grid grid-cols-2 gap-x-6 gap-y-5 py-5 sm:grid-cols-3 lg:grid-cols-6">
        {items.map((i) => (
          <div key={i.label}>
            <dt className="text-sm text-graphite">{i.label}</dt>
            <dd className="mt-1 font-serif text-[1.75rem] leading-none">{i.value}</dd>
            <dd className="mt-2 text-xs leading-snug text-graphite">{i.note}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
