import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from "recharts";
import type { Run } from "@/lib/types";
import { rupees } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";

const short = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

export function Timeline({ run }: { run: Run }) {
  const data = run.daily.map((d) => ({
    ...d, label: short(d.date),
    capturedR: d.captured / 100, settledR: d.settled / 100, bankedR: d.banked / 100,
    exc: d.exceptions || null,
  }));
  return (
    <Panel title="Day by day"
      note="Captures happen one day; the bank pays them out a working day or more later, netted. Weekends leave gaps and Mondays catch up, which is why a same-day comparison would fail. Red dots are the exceptions dated to that day.">
      <div className="h-72 w-full">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="rgb(var(--rule))" strokeOpacity={0.6} vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "rgb(var(--graphite))" }} tickLine={false} axisLine={{ stroke: "rgb(var(--rule))" }} interval="preserveStartEnd" minTickGap={16} />
            <YAxis yAxisId="m" tick={{ fontSize: 11, fill: "rgb(var(--graphite))" }} tickLine={false} axisLine={false} width={56}
              tickFormatter={(v: number) => (Math.abs(v) >= 1000 ? `₹${Math.round(v / 1000)}k` : `₹${v}`)} />
            <YAxis yAxisId="e" orientation="right" hide domain={[0, "dataMax + 2"]} />
            <Tooltip content={<Tip />} cursor={{ fill: "rgb(var(--ink) / 0.05)" }} />
            <Bar yAxisId="m" dataKey="capturedR" name="Captured" fill="rgb(var(--ink))" fillOpacity={0.2} radius={[2, 2, 0, 0]} />
            <Line yAxisId="m" dataKey="settledR" name="Settlement payouts" stroke="rgb(var(--settled))" strokeWidth={2} dot={false} type="stepAfter" />
            <Line yAxisId="m" dataKey="bankedR" name="Bank movement" stroke="rgb(var(--tick))" strokeWidth={2} strokeDasharray="4 3" dot={false} type="stepAfter" />
            <Scatter yAxisId="e" dataKey="exc" name="Exceptions" fill="rgb(var(--redink))" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-graphite">
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-3 bg-ink/20" />Captured at the gateway</li>
        <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-settled" />Settlement payouts due</li>
        <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t-2 border-dashed border-tick" />Bank movement</li>
        <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-redink" />Exceptions</li>
      </ul>
    </Panel>
  );
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Run["daily"][number] & { label: string } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded border border-rule bg-sheet px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium">{d.label}</div>
      <div className="num grid grid-cols-[auto_auto] gap-x-4">
        <span className="text-graphite">Captured</span><span className="text-right">{rupees(d.captured)}</span>
        <span className="text-graphite">Payouts due</span><span className="text-right">{rupees(d.settled)}</span>
        <span className="text-graphite">Bank movement</span><span className="text-right">{rupees(d.banked)}</span>
        {d.exceptions > 0 && <><span className="text-redink">Exceptions</span><span className="text-right text-redink">{d.exceptions}</span></>}
      </div>
    </div>
  );
}
