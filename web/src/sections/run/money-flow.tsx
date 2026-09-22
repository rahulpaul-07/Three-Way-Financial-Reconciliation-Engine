import { sankey, sankeyLeft, sankeyLinkHorizontal, type SankeyLink, type SankeyNode } from "d3-sankey";
import { useMemo, useState } from "react";
import type { Run } from "@/lib/types";
import { rupees } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";
import { useElementWidth } from "@/hooks/use-data";

type N = { name: string };
type L = { source: number; target: number; value: number };

// Where each node sits on the ledger palette: money that reached the bank and
// tied is blue pencil, deductions are graphite, anything unaccounted is red.
const SPINE = new Set(["Captured gross", "Net of fees", "In a settlement", "Net payout", "Credited & matched"]);
const TONE: Record<string, string> = {
  "Captured gross": "var(--ink)", "Net of fees": "var(--ink)", "In a settlement": "var(--ink)",
  "Net payout": "var(--ink)", "Credited & matched": "var(--tick)",
  "MDR fees": "var(--graphite)", "GST on fees": "var(--graphite)",
  "Refunds & chargebacks": "var(--settled)", "Awaiting payout": "var(--settled)",
  "Unknown settlement": "var(--redink)", "Not matched in bank": "var(--redink)",
};

export function MoneyFlow({ run }: { run: Run }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const narrow = width < 560;
  const height = narrow ? 400 : 430;

  const graph = useMemo(() => {
    if (!width || !run.money_flow.links.length) return null;
    const used = new Set(run.money_flow.links.flatMap((l) => [l.source, l.target]));
    const nodes = run.money_flow.nodes.map((n, i) => ({ ...n, i })).filter((n) => used.has(n.i));
    const index = new Map(nodes.map((n, k) => [n.i, k]));
    const links = run.money_flow.links.map((l) => ({ ...l, source: index.get(l.source)!, target: index.get(l.target)! }));
    // Left alignment keeps each deduction beside the stage it leaves, rather
    // than stacking every sink in the last column where the labels collide.
    // Space is reserved on the right for the branch labels.
    return sankey<N, L>()
      .nodeAlign(sankeyLeft).nodeWidth(8).nodePadding(narrow ? 26 : 30)
      // The spine sits on top with its labels above it; every branch hangs
      // beneath, labelled to its right, so no two labels share a space.
      .nodeSort((a, b) => Number(!SPINE.has(a.name)) - Number(!SPINE.has(b.name)) || (b.value ?? 0) - (a.value ?? 0))
      .extent([[1, 26], [width - (narrow ? 70 : 110), height - 30]])({ nodes: nodes.map((n) => ({ name: n.name })), links });
  }, [run, width, height]);

  const t = run.money_flow.totals;

  return (
    <Panel title="Where the captured money went"
      note={<>Every stream here conserves: each node's outflows sum exactly to its inflow, in paise. Of {rupees(t.gross, { compact: true })} captured,{" "}
        {rupees(t.credited, { compact: true })} reached the bank and tied; {t.not_credited > 0
          ? <span className="text-redink">{rupees(t.not_credited, { compact: true })} of payouts did not appear on the statement</span>
          : "every payout appeared on the statement"}.</>}>
      <div ref={ref} className="w-full">
        {narrow && <FlowStatement totals={t} />}
        {graph && !narrow && (
          <svg width={width} height={height} role="img" aria-label="Sankey diagram of captured money flowing to fees, settlements and the bank">
            <g fill="none">
              {graph.links.map((l, k) => {
                const target = (l.target as SankeyNode<N, L>).name;
                const active = hover === null || hover === k;
                return (
                  <path key={k} d={sankeyLinkHorizontal()(l as SankeyLink<N, L>) ?? ""}
                    stroke={`rgb(${SPINE.has(target) ? "var(--tick)" : TONE[target] ?? "var(--ink)"})`}
                    strokeOpacity={active ? (SPINE.has(target) ? 0.2 : 0.4) : 0.06}
                    strokeWidth={Math.max(1, l.width ?? 1)}
                    onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}>
                    <title>{`${(l.source as SankeyNode<N, L>).name} to ${target}: ${rupees(l.value)}`}</title>
                  </path>
                );
              })}
            </g>
            {graph.nodes.map((n) => {
              const spine = SPINE.has(n.name);
              const x0 = n.x0 ?? 0, x1 = n.x1 ?? 0, y0 = n.y0 ?? 0, y1 = n.y1 ?? 0;
              // Spine stages are labelled above the node, where the stream is
              // widest and nothing else is drawn; branches directly beneath.
              const label = spine
                ? { x: x0, y: y0 - 16, anchor: "start" as const, y2: y0 - 5 }
                : { x: x0, y: y1 + 12, anchor: "start" as const, y2: y1 + 24 };
              return (
                <g key={n.name}>
                  <rect x={x0} y={y0} width={x1 - x0} height={Math.max(1.5, y1 - y0)}
                    fill={`rgb(${TONE[n.name] ?? "var(--ink)"})`} />
                  <text x={label.x} y={label.y} textAnchor={label.anchor} className="fill-ink text-[11px]">{n.name}</text>
                  <text x={label.x} y={label.y2} textAnchor={label.anchor} className="num fill-graphite text-[11px]">
                    {rupees(n.value ?? 0, { compact: true })}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
      </div>
    </Panel>
  );
}

/**
 * On a phone the diagram's labels have no room, so the same flows are set out
 * the way a statement would: each deduction beneath the line it comes from.
 */
function FlowStatement({ totals: t }: { totals: Record<string, number> }) {
  const net = t.gross - t.fees - t.gst;
  const rows: { label: string; value: number; kind: "line" | "less" | "total" | "bad" }[] = [
    { label: "Captured gross", value: t.gross, kind: "line" },
    { label: "less MDR fees", value: -t.fees, kind: "less" },
    { label: "less GST on fees", value: -t.gst, kind: "less" },
    { label: "Net of fees", value: net, kind: "total" },
    { label: "awaiting payout", value: -t.awaiting, kind: "less" },
    ...(t.dangling ? [{ label: "unknown settlement", value: -t.dangling, kind: "bad" as const }] : []),
    { label: "refunds and chargebacks", value: -t.reversals, kind: "less" },
    { label: "Net payout", value: t.payout, kind: "total" },
    ...(t.not_credited ? [{ label: "not matched in bank", value: -t.not_credited, kind: "bad" as const }] : []),
    { label: "Credited and matched", value: t.credited, kind: "total" },
  ];
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className={r.kind === "total" ? "border-t border-ink/60" : ""}>
            <td className={`py-1.5 ${r.kind === "less" || r.kind === "bad" ? "pl-4 text-graphite" : "font-medium"} ${r.kind === "bad" ? "text-redink" : ""}`}>{r.label}</td>
            <td className={`num py-1.5 text-right ${r.kind === "bad" ? "text-redink" : r.kind === "less" ? "text-graphite" : ""}`}>{rupees(r.value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
