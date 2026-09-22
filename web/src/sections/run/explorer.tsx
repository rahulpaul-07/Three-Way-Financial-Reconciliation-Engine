import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { Resolution, Run, Severity } from "@/lib/types";
import { cn, human, rupees } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";
import { Segmented } from "@/components/ui/segmented";
import { ClassBadge } from "@/components/ui/severity";
import { Sheet } from "@/components/ui/sheet";
import { Lineage } from "./lineage";

type Scope = "open" | "all" | Severity;
const RANK: Record<Severity, number> = { break: 0, review: 1, expected: 2, ok: 3 };
const PAGE = 25;
const TIER = ["self-consistency", "exact key", "inference", "recovery"];
const TYPE: Record<Resolution["entity_type"], string> = {
  order: "Order", txn: "Gateway row", bank_row: "Bank line", settlement: "Settlement", statement_gap: "Statement gap",
};

export function Explorer({ run }: { run: Run }) {
  const [scope, setScope] = useState<Scope>("open");
  const [cls, setCls] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<Resolution | null>(null);

  const classes = useMemo(() => Object.keys(run.summary.by_class).sort(), [run]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return run.resolutions
      .filter((r) => scope === "all" || (scope === "open" ? !r.resolved : r.severity === scope))
      .filter((r) => !cls || r.classification === cls)
      .filter((r) => !needle || [r.entity_id, r.matched_to, r.detail, r.classification].some((f) => f.toLowerCase().includes(needle)))
      .sort((a, b) => RANK[a.severity] - RANK[b.severity] || Math.abs(b.amount_paise) - Math.abs(a.amount_paise));
  }, [run, scope, cls, q]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const reset = () => setPage(0);

  return (
    <Panel title="Every record, and why"
      note="Select a record to trace it across all four sources. Unresolved records are never dropped: each carries the reason the engine could not close it.">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Which records" value={scope} onChange={(v) => { setScope(v); reset(); }}
          options={[
            { value: "open", label: `Sent to a person (${run.summary.unresolved})` },
            { value: "break", label: "Breaks" },
            { value: "review", label: "Review" },
            { value: "all", label: "All" },
          ]} />
        <select value={cls} onChange={(e) => { setCls(e.target.value); reset(); }} aria-label="Filter by classification"
          className="h-9 rounded border border-rule bg-paper px-2 text-sm">
          <option value="">Any classification</option>
          {classes.map((c) => <option key={c} value={c}>{human(c)}</option>)}
        </select>
        <label className="relative ml-auto w-full sm:w-64">
          <Search size={15} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-graphite" aria-hidden />
          <input value={q} onChange={(e) => { setQ(e.target.value); reset(); }} placeholder="Search id, reference or reason"
            aria-label="Search records" className="h-9 w-full rounded border border-rule bg-paper pl-8 pr-3 text-sm" />
        </label>
      </div>

      <div className="scroll-x mt-4">
        <table className="w-full min-w-[46rem] text-sm">
          <thead>
            <tr className="border-b border-ink/50 text-left text-graphite">
              <th className="py-2 pr-3 font-medium">Record</th>
              <th className="py-2 pr-3 font-medium">Classification</th>
              <th className="py-2 pr-3 text-right font-medium">Amount</th>
              <th className="py-2 pr-3 font-medium">Reason</th>
              <th className="py-2 font-medium">Method</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.entity_id} onClick={() => setOpen(r)}
                className="cursor-pointer border-b border-rule/60 align-top hover:bg-ink/[0.03]">
                <td className="py-2 pr-3">
                  <button className="text-left font-mono text-[0.8rem] text-ink underline decoration-rule underline-offset-4 hover:decoration-ink"
                    onClick={(e) => { e.stopPropagation(); setOpen(r); }}>{r.entity_id}</button>
                  <div className="text-xs text-graphite">{TYPE[r.entity_type]}</div>
                </td>
                <td className="py-2 pr-3"><ClassBadge label={r.classification} severity={r.severity} /></td>
                <td className={cn("num py-2 pr-3 text-right", r.amount_paise < 0 && "text-redink")}>{rupees(r.amount_paise)}</td>
                <td className="max-w-[26rem] py-2 pr-3 text-graphite">{r.detail}</td>
                <td className="whitespace-nowrap py-2 text-xs text-graphite">
                  {r.resolved ? `tier ${r.tier}, ${TIER[r.tier]}` : "unresolved"}
                </td>
              </tr>
            ))}
            {!shown.length && (
              <tr><td colSpan={5} className="py-8 text-center text-graphite">No records match. Clear the search or choose All.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="mt-3 flex items-center justify-between text-sm text-graphite">
          <span className="num">{rows.length} records, page {page + 1} of {pages}</span>
          <span className="flex gap-2">
            <button className="rounded border border-rule px-3 py-1 hover:border-ink disabled:opacity-40" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="rounded border border-rule px-3 py-1 hover:border-ink disabled:opacity-40" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
          </span>
        </div>
      )}

      <Sheet open={!!open} onClose={() => setOpen(null)}
        title={open && (
          <div>
            <div className="font-mono text-sm">{open.entity_id}</div>
            <ClassBadge className="mt-1" label={open.classification} severity={open.severity} />
          </div>
        )}>
        {open && <Lineage run={run} r={open} />}
      </Sheet>
    </Panel>
  );
}
