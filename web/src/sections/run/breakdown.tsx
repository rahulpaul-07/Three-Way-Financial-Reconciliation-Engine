import { useMemo } from "react";
import type { Run, Severity } from "@/lib/types";
import { cn, human, pct } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";
import { SEVERITY_BG, SEVERITY_NAME, SEVERITY_TEXT } from "@/components/ui/severity";

const TIER: Record<string, string> = { "0": "Self-consistency", "1": "Exact key join", "2": "Deterministic inference" };

export function Breakdown({ run }: { run: Run }) {
  const s = run.summary;
  const sevOf = useMemo(() => {
    const m = new Map<string, Severity>();
    run.resolutions.forEach((r) => m.set(r.classification, r.severity));
    return m;
  }, [run]);

  const segments = [
    ...Object.entries(s.tiers).map(([t, n]) => ({ key: `t${t}`, label: TIER[t] ?? `Tier ${t}`, n, cls: t === "1" ? "bg-tick" : "bg-tick/55" })),
    { key: "u", label: "Sent to a person", n: s.unresolved, cls: "bg-redink/80" },
  ];
  const classes = Object.entries(s.by_class);
  const max = Math.max(...classes.map(([, n]) => n));

  return (
    <Panel title="How each record was settled">
      <p className="text-sm text-graphite">Resolved by the strongest method that could, then everything left.</p>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded-sm" role="img"
        aria-label={segments.map((g) => `${g.label} ${g.n}`).join(", ")}>
        {segments.map((g) => (
          <div key={g.key} className={g.cls} style={{ width: `${(g.n / s.entities) * 100}%` }} title={`${g.label}: ${g.n}`} />
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-graphite">
        {segments.map((g) => (
          <li key={g.key} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", g.cls)} aria-hidden />
            {g.label} <span className="num text-ink">{g.n}</span> ({pct(g.n / s.entities, 0)})
          </li>
        ))}
      </ul>

      <h4 className="mt-7 font-serif text-base font-medium">By classification</h4>
      <ul className="mt-3 space-y-1.5">
        {classes.map(([label, n]) => {
          const sev = sevOf.get(label) ?? "review";
          return (
            <li key={label} className="grid grid-cols-[minmax(0,10.5rem)_1fr_2.5rem] items-center gap-3 text-sm">
              <span className={cn("truncate", SEVERITY_TEXT[sev])} title={human(label)}>{human(label)}</span>
              <span className="h-2 rounded-sm bg-rule/40">
                <span className={cn("block h-full rounded-sm", SEVERITY_BG[sev])} style={{ width: `${(n / max) * 100}%` }} />
              </span>
              <span className="num text-right">{n}</span>
            </li>
          );
        })}
      </ul>
      <ul className="mt-5 flex flex-wrap gap-x-4 gap-y-1 border-t border-rule pt-3 text-xs text-graphite">
        {(Object.keys(SEVERITY_NAME) as Severity[]).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", SEVERITY_BG[k])} aria-hidden />{SEVERITY_NAME[k]}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
