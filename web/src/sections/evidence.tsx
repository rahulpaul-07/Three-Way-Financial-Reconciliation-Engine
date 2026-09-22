import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, ReferenceLine } from "recharts";
import { snapshot } from "@/lib/api";
import type { Benchmarks, Meta } from "@/lib/types";
import { cn, human, int, pct } from "@/lib/utils";
import { useData } from "@/hooks/use-data";
import { Panel, Skeleton } from "@/components/ui/panel";

const axis = { fontSize: 11, fill: "rgb(var(--graphite))" };
const grid = <CartesianGrid stroke="rgb(var(--rule))" strokeOpacity={0.6} vertical={false} />;
const tipStyle = {
  contentStyle: { background: "rgb(var(--sheet))", border: "1px solid rgb(var(--rule))", borderRadius: 5, fontSize: 12 },
  labelStyle: { color: "rgb(var(--ink))" }, itemStyle: { color: "rgb(var(--ink))" },
};

export function Evidence({ meta }: { meta: Meta | null }) {
  const bench = useData(snapshot.benchmarks);
  const b = bench.data;
  return (
    <section id="evidence" className="border-b border-rule">
      <div className="mx-auto max-w-page px-5 py-16 sm:px-8 lg:py-20">
        <div className="max-w-prose">
          <h2 className="text-3xl font-medium">Evidence</h2>
          <p className="mt-3 text-graphite">
            One good run proves little. These are measured across independently generated batches, under rising
            defect density, at scale, and against defects the engine was not designed around.
            {meta && <> The test suite has {meta.tests} tests.</>}
          </p>
        </div>
        {!b ? <Skeleton className="mt-10 h-96 w-full" /> : (
          <div className="mt-10 grid gap-6 lg:grid-cols-2">
            <Variance b={b} />
            <Degradation b={b} />
            <BlindSpots b={b} />
            <Throughput b={b} />
          </div>
        )}
      </div>
    </section>
  );
}

function Variance({ b }: { b: Benchmarks }) {
  const rates = b.variance.map((v) => v.resolution_rate);
  const mean = rates.reduce((a, x) => a + x, 0) / rates.length;
  const sd = Math.sqrt(rates.reduce((a, x) => a + (x - mean) ** 2, 0) / rates.length);
  const allPerfect = b.variance.every((v) => v.accuracy === 1);
  const data = b.variance.map((v) => ({ seed: v.seed, rate: +(v.resolution_rate * 100).toFixed(2) }));
  return (
    <Panel title={`${b.variance.length} batches, different data, same answer`}
      note={<>Resolution rate {pct(mean)} ± {pct(sd)} across seeds. Classification accuracy was {allPerfect ? "100% on every one" : "not perfect on every seed"}.
        The spread comes from how many captures happen to fall after the last payout, which are correctly left unsettled.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="seed" type="number" name="Seed" tick={axis} tickLine={false} domain={[0, b.variance.length + 1]} allowDecimals={false}
              label={{ value: "seed", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis dataKey="rate" type="number" name="Resolved" unit="%" tick={axis} tickLine={false} axisLine={false} width={48}
              domain={[(dataMin: number) => Math.floor(dataMin - 1), (dataMax: number) => Math.ceil(dataMax + 1)]} />
            <ZAxis range={[60, 60]} />
            <ReferenceLine y={+(mean * 100).toFixed(2)} stroke="rgb(var(--graphite))" strokeDasharray="4 3" />
            <Tooltip {...tipStyle} cursor={false} />
            <Scatter data={data} fill="rgb(var(--tick))" name="Resolved" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

function Degradation({ b }: { b: Benchmarks }) {
  // Plotted against the planted-defect multiplier, which both runs share.
  // The share of records carrying a defect differs between them at the same
  // multiplier (compound stacking puts several on one record), so it is
  // shown in the tooltip rather than used as the axis.
  const rows = b.stress_compound.map((c, i) => ({
    scale: `×${c.scale}`,
    compound: +(c.accuracy * 100).toFixed(1),
    separate: +((b.stress_density[i]?.accuracy ?? 1) * 100).toFixed(1),
    compoundDensity: Math.round(c.defect_rate * 100),
    separateDensity: Math.round((b.stress_density[i]?.defect_rate ?? 0) * 100),
  }));
  const worst = b.stress_compound[b.stress_compound.length - 1];
  return (
    <Panel title="Where it breaks"
      note={<>More defects of the same kinds change nothing: each record is classified on its own. Defects that land on the same record do degrade it,
        to {pct(worst.accuracy)} at {pct(worst.defect_rate, 0)} density, because the taxonomy allows one label per record and some records have two.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="scale" tick={axis} tickLine={false}
              label={{ value: "planted defect rate", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis unit="%" tick={axis} tickLine={false} axisLine={false} width={48} domain={[70, 100]} />
            <Tooltip {...tipStyle} formatter={(v: number, name: string, item: { payload?: Record<string, number> }) => {
              const d = name.includes("same") ? item.payload?.compoundDensity : item.payload?.separateDensity;
              return [`${v}% correct, ${d}% of records defective`, name];
            }} />
            <Line dataKey="separate" name="Defects on separate records" stroke="rgb(var(--tick))" strokeWidth={2} dot={{ r: 3 }} />
            <Line dataKey="compound" name="Defects on the same record" stroke="rgb(var(--redink))" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-5 text-xs text-graphite">
        <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-tick" />Defects on separate records</li>
        <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-redink" />Defects on the same record</li>
      </ul>
    </Panel>
  );
}

function Throughput({ b }: { b: Benchmarks }) {
  const data = b.throughput.map((t) => ({ label: int(t.entities), rate: Math.round(t.entities_per_second / 1000), ms: t.reconcile_seconds * 1000 }));
  const last = b.throughput[b.throughput.length - 1];
  const rates = b.throughput.map((t) => t.entities_per_second);
  const lo = Math.min(...rates), hi = Math.max(...rates);
  return (
    <Panel title="Speed at scale"
      note={<>Thousands of entities reconciled per second, by batch size. Across a {Math.round(last.entities / b.throughput[0].entities)}× range of sizes the rate stays between{" "}
        {Math.round(lo / 1000)}k and {Math.round(hi / 1000)}k per second, so cost grows linearly; the largest batch takes {(last.reconcile_seconds * 1000).toFixed(0)} ms.
        These are single timings on the build machine, not a controlled benchmark, and vary by a few tens of percent between runs.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="label" tick={axis} tickLine={false}
              label={{ value: "entities in batch", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis tick={axis} tickLine={false} axisLine={false} width={48} unit="k" />
            <Tooltip {...tipStyle} cursor={{ fill: "rgb(var(--ink) / 0.05)" }} formatter={(v: number) => [`${v}k per second`, "Rate"]} />
            <Bar dataKey="rate" fill="rgb(var(--ink))" fillOpacity={0.75} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

function BlindSpots({ b }: { b: Benchmarks }) {
  const { before, after } = b.detection;
  const classes = Object.keys(after.by_class).sort();
  return (
    <Panel title="Blind spots, found and closed"
      note={<>An adversarial generator planted nine defect classes the engine had no rule for. Before, four passed silently; the duplicate bank credit reconciled the same money twice
        without a flag. Each now has a rule and a test. Because the rules were written after seeing these defects, this batch no longer measures generalisation for them; that needs a fresh round of unseen classes.</>}>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <Stat label={`Before (${before.commit})`} value={`${before.detected} of ${before.total}`} tone="text-redink" />
        <Stat label="Now" value={`${after.detected} of ${after.total}`} tone="text-tick" />
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {classes.map((c) => {
          const was = before.silent_classes.includes(c);
          return (
            <li key={c} className="flex items-center justify-between gap-3 border-b border-rule/60 py-1">
              <span>{human(c)}</span>
              <span className={cn("text-xs", was ? "text-settled" : "text-graphite")}>{was ? "was silent, now caught" : "caught before and now"}</span>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded border border-rule p-3">
      <div className="text-graphite">{label}</div>
      <div className={cn("num mt-1 font-serif text-2xl", tone)}>{value}</div>
      <div className="text-xs text-graphite">planted records flagged</div>
    </div>
  );
}
