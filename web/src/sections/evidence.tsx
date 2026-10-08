import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, ReferenceLine } from "recharts";
import { snapshot } from "@/lib/api";
import type { Benchmarks, Meta } from "@/lib/types";
import { cn, human, int, pct } from "@/lib/utils";
import { useData } from "@/hooks/use-data";
import { Panel, Skeleton } from "@/components/ui/panel";
import { BlurFade } from "@/components/ui/blur-fade";
import { SectionHeader } from "@/components/ui/section-header";
import { Section } from "@/components/ui/section";
import { REPO } from "./links";

const axis = { fontSize: 11, fill: "rgb(var(--graphite))" };
const grid = <CartesianGrid stroke="rgb(var(--rule))" strokeOpacity={0.6} vertical={false} />;
const tipStyle = {
  contentStyle: { background: "rgb(var(--sheet))", border: "1px solid rgb(var(--rule))", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "rgb(var(--ink))" }, itemStyle: { color: "rgb(var(--ink))" },
};

export function Evidence({ meta }: { meta: Meta | null }) {
  const bench = useData(snapshot.benchmarks);
  const b = bench.data;
  return (
    <Section id="evidence" accent={3} word="PROOF">
      <div className="mx-auto max-w-page px-5 py-20 sm:px-8 lg:py-28">
        <SectionHeader folio="03" eyebrow="Evidence" title="One good run proves little.">
          These are measured across independently generated batches, under rising defect density, at scale, and against
          defects the engine was not designed around.
        </SectionHeader>
        {!b ? <Skeleton className="mt-12 h-96 w-full" /> : (
          // A bento grid, after Magic UI's (magicui.design/docs/components/bento-grid):
          // tiles sized by how much each chart needs to say.
          <div className="mt-12 grid auto-rows-auto gap-4 lg:grid-cols-6">
            <BlurFade className="lg:col-span-4"><Variance b={b} /></BlurFade>
            <BlurFade className="lg:col-span-2" delay={0.06}><Facts meta={meta} b={b} /></BlurFade>
            <BlurFade className="lg:col-span-3"><Degradation b={b} /></BlurFade>
            <BlurFade className="lg:col-span-3" delay={0.06}><Throughput b={b} /></BlurFade>
            <BlurFade className="lg:col-span-6"><BlindSpots b={b} /></BlurFade>
          </div>
        )}
      </div>
    </Section>
  );
}

/** What the suite and CI check, with the commit the figures were built from. */
function Facts({ meta, b }: { meta: Meta | null; b: Benchmarks }) {
  const rows: [string, string][] = [
    ["Tests", meta?.tests != null ? int(meta.tests) : "–"],
    ["Batches measured", int(b.variance.length)],
    ["Python versions in CI", "3.10–3.13"],
  ];
  return (
    <Panel spotlight className="flex h-full flex-col" title="Checked on every push">
      <dl className="space-y-4">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-4 border-b border-rule/60 pb-3">
            <dt className="text-sm text-graphite">{k}</dt>
            <dd className="num whitespace-nowrap font-serif text-2xl">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-auto pt-4 text-sm text-graphite">
        CI fails if classification accuracy moves or any unseen defect class passes silently.
        {meta && <> Figures built from commit <a className="font-mono text-xs underline decoration-rule underline-offset-2 hover:text-ink" href={`${REPO}/commit/${meta.commit}`}>{meta.commit}</a>.</>}
      </p>
    </Panel>
  );
}

function Variance({ b }: { b: Benchmarks }) {
  const rates = b.variance.map((v) => v.resolution_rate);
  const mean = rates.reduce((a, x) => a + x, 0) / rates.length;
  const sd = Math.sqrt(rates.reduce((a, x) => a + (x - mean) ** 2, 0) / rates.length);
  const allPerfect = b.variance.every((v) => v.accuracy === 1);
  const data = b.variance.map((v) => ({ seed: v.seed, rate: +(v.resolution_rate * 100).toFixed(2) }));
  return (
    <Panel spotlight className="h-full" title={`${b.variance.length} batches, different data, same answer`}
      note={<>Resolution rate {pct(mean)} ± {pct(sd)} across seeds. Classification accuracy was {allPerfect ? "100% on every one" : "not perfect on every seed"}.
        The spread comes from how many captures happen to fall after the last payout, which are correctly left unsettled.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="seed" type="number" name="Seed" tick={axis} tickLine={false} domain={[0, b.variance.length + 1]} allowDecimals={false}
              label={{ value: "seed", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis dataKey="rate" type="number" name="Resolved" unit="%" tick={axis} tickLine={false} axisLine={false} width={56}
              tickFormatter={(v: number) => v.toFixed(1)}
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
    <Panel spotlight className="h-full" title="Where it breaks"
      note={<>More defects of the same kinds change nothing: each record is classified on its own. Defects that land on the same record do degrade it,
        to {pct(worst.accuracy)} at {pct(worst.defect_rate, 0)} density, because the taxonomy allows one label per record and some records have two.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="scale" tick={axis} tickLine={false}
              label={{ value: "planted defect rate", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis unit="%" tick={axis} tickLine={false} axisLine={false} width={48} domain={[70, 100]} ticks={[70, 80, 90, 100]} />
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
    <Panel spotlight className="h-full" title="Speed at scale"
      note={<>Thousands of entities reconciled per second, by batch size: between {int(lo / 1000)}k and {int(hi / 1000)}k here, so cost grows
        roughly linearly with the batch. The largest, {int(last.entities)} entities, took {(last.reconcile_seconds * 1000).toFixed(0)} ms.
        These are single timings on the build machine and vary from run to run; they are not a controlled benchmark.</>}>
      <div className="h-56">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            {grid}
            <XAxis dataKey="label" tick={axis} tickLine={false}
              label={{ value: "entities in batch", position: "insideBottomRight", offset: -2, fontSize: 11, fill: "rgb(var(--graphite))" }} />
            <YAxis tick={axis} tickLine={false} axisLine={false} width={48} unit="k" />
            <Tooltip {...tipStyle} cursor={{ fill: "rgb(var(--ink) / 0.05)" }} formatter={(v: number) => [`${v}k per second`, "Rate"]} />
            <Bar dataKey="rate" fill="rgb(var(--tick))" fillOpacity={0.85} radius={[2, 2, 0, 0]} />
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
    <Panel spotlight className="h-full" title="Blind spots, found and closed"
      note={<>An adversarial generator planted nine defect classes the engine had no rule for. Before, four passed silently; the duplicate bank credit reconciled the same money twice
        without a flag. Each now has a rule and a test. Because the rules were written after seeing these defects, this batch no longer measures generalisation for them; that needs a fresh round of unseen classes.</>}>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <Stat label={`Before (${before.commit})`} value={`${before.detected} of ${before.total}`} tone="text-redink" />
        <Stat label="Now" value={`${after.detected} of ${after.total}`} tone="text-tick" />
      </div>
      <ul className="mt-4 grid gap-x-8 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-3">
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
