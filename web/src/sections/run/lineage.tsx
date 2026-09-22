import type { BankRow, Order, Resolution, Run, Settlement, Txn } from "@/lib/types";
import { cn, rupees } from "@/lib/utils";

interface Chain { orders: Order[]; txns: Txn[]; settlements: Settlement[]; bank: BankRow[]; dangling: string[] }

/**
 * Follow a record through the four sources using the same keys the engine
 * uses: order_ref, settlement_id, and the bank line each settlement was
 * matched to. Nothing is inferred here that the engine did not already record.
 */
function trace(run: Run, r: Resolution): Chain | null {
  const rec = run.records;
  if (!rec) return null;
  const orderBy = new Map(rec.orders.map((o) => [o.order_id, o]));
  const setlBy = new Map(rec.settlements.map((s) => [s.settlement_id, s]));
  const bankBy = new Map(rec.bank.map((b) => [b.bank_txn_id, b]));
  const bankFor = (sid: string) => run.resolutions
    .filter((x) => x.entity_type === "bank_row" && x.matched_to === sid)
    .map((x) => bankBy.get(x.entity_id)!).filter(Boolean);

  const chain: Chain = { orders: [], txns: [], settlements: [], bank: [], dangling: [] };
  const addSettlements = (txns: Txn[]) => {
    for (const t of txns) {
      if (!t.settlement_id) continue;
      const s = setlBy.get(t.settlement_id);
      if (s && !chain.settlements.includes(s)) chain.settlements.push(s);
      if (!s && !chain.dangling.includes(t.settlement_id)) chain.dangling.push(t.settlement_id);
    }
    for (const s of chain.settlements) for (const b of bankFor(s.settlement_id)) if (!chain.bank.includes(b)) chain.bank.push(b);
  };

  switch (r.entity_type) {
    case "order": {
      const o = orderBy.get(r.entity_id);
      if (o) chain.orders.push(o);
      chain.txns = rec.txns.filter((t) => t.order_ref === r.entity_id);
      addSettlements(chain.txns);
      break;
    }
    case "txn": {
      const t = rec.txns.find((x) => x.txn_id === r.entity_id);
      if (t) {
        chain.txns = [t];
        const o = t.order_ref ? orderBy.get(t.order_ref) : undefined;
        if (o) chain.orders.push(o);
        addSettlements(chain.txns);
      }
      break;
    }
    case "settlement": {
      const s = setlBy.get(r.entity_id);
      if (s) chain.settlements.push(s);
      chain.txns = rec.txns.filter((t) => t.settlement_id === r.entity_id);
      chain.orders = chain.txns.map((t) => orderBy.get(t.order_ref ?? "")).filter(Boolean) as Order[];
      chain.bank = bankFor(r.entity_id);
      break;
    }
    case "bank_row": {
      const b = bankBy.get(r.entity_id);
      if (b) chain.bank.push(b);
      const s = r.matched_to ? setlBy.get(r.matched_to) : undefined;
      if (s) {
        chain.settlements.push(s);
        chain.txns = rec.txns.filter((t) => t.settlement_id === s.settlement_id);
        chain.orders = chain.txns.map((t) => orderBy.get(t.order_ref ?? "")).filter(Boolean) as Order[];
      }
      break;
    }
    case "statement_gap": {
      const id = r.entity_id.replace("GAP_BEFORE_", "");
      const i = rec.bank.findIndex((b) => b.bank_txn_id === id);
      chain.bank = rec.bank.slice(Math.max(0, i - 1), i + 1);
      break;
    }
  }
  return chain;
}

export function Lineage({ run, r }: { run: Run; r: Resolution }) {
  const chain = trace(run, r);
  return (
    <div className="space-y-6 text-sm">
      <div>
        <p className="text-ink">{r.detail}</p>
        <p className="mt-1 text-graphite">
          {r.resolved ? `Resolved at tier ${r.tier}.` : "Not resolved; this record goes to a person."}
          {r.matched_to && <> Linked to <span className="font-mono text-[0.8rem]">{r.matched_to}</span>.</>}
        </p>
      </div>

      {!chain ? (
        <p className="text-graphite">This run is too large to include raw records, so the trace is unavailable. The classification and reason above still apply.</p>
      ) : (
        <ol className="relative space-y-4 border-l border-rule pl-5">
          {(() => {
            // A stage is where the chain breaks if it is empty and a stage
            // next to it is not: that is the gap the analyst needs to see.
            const present = [chain.orders.length, chain.txns.length, chain.settlements.length, chain.bank.length].map((n) => n > 0);
            const gap = r.entity_type !== "statement_gap";
            const breaks = (i: number) => gap && !present[i] && (present[i - 1] || present[i + 1]) === true;
            return (<>
              <Stage title="Merchant ledger" danger={breaks(0)} empty={!gap ? null : breaks(0) ? "No ledger order carries this. Money arrived for a sale the merchant never recorded, or its reference is lost." : "Nothing further to follow."}
                items={chain.orders.map((o) => ({ id: o.order_id, focus: o.order_id === r.entity_id,
                  main: rupees(o.order_amount_paise), sub: `${o.payment_method}, ${o.currency}, ${o.order_status}, ${o.order_datetime.slice(0, 10)}` }))} />
              <Stage title="Gateway report" danger={breaks(1)} empty={!gap ? null : breaks(1) ? "No gateway row. The payment never reached the gateway, or its reference is missing." : "Nothing further to follow."}
                items={chain.txns.map((t) => ({ id: t.txn_id, focus: t.txn_id === r.entity_id,
                  main: `${rupees(t.gross_amount_paise)} gross, ${rupees(t.net_amount_paise)} net`,
                  sub: `${t.txn_type}, ${t.status}, fee ${rupees(t.fee_paise)} + GST ${rupees(t.gst_on_fee_paise)}, ${t.settlement_id ?? "not yet settled"}` }))} />
              <Stage title="Settlement report" danger={breaks(2) || chain.dangling.length > 0}
                empty={!gap ? null : chain.dangling.length ? `Refers to ${chain.dangling.join(", ")}, which the settlement report does not contain.`
                  : breaks(2) ? (present[3] ? "No settlement accounts for this bank line." : "Not in any settlement yet. If the capture is recent, that is expected.") : "Nothing further to follow."}
                items={chain.settlements.map((s) => ({ id: s.settlement_id, focus: s.settlement_id === r.entity_id,
                  main: rupees(s.total_paise), sub: `captured ${s.capture_date}, payout ${s.payout_date}, UTR ${s.utr ?? "none"}` }))} />
              <Stage title="Bank statement" danger={breaks(3)} empty={breaks(3) ? "No statement line pays this." : "Nothing further to follow."}
                items={chain.bank.map((b) => ({ id: b.bank_txn_id, focus: b.bank_txn_id === r.entity_id || r.entity_id === `GAP_BEFORE_${b.bank_txn_id}`,
                  main: rupees(b.movement_paise, { sign: true }), sub: `${b.value_date}, balance ${rupees(b.balance_paise)}, ${b.description}` }))} />
            </>);
          })()}
        </ol>
      )}
    </div>
  );
}

function Stage({ title, items, empty, danger }: {
  title: string; empty: string | null; danger?: boolean;
  items: { id: string; main: string; sub: string; focus: boolean }[];
}) {
  return (
    <li>
      <span className={cn("absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-sheet",
        items.length ? "bg-tick" : danger ? "bg-redink" : "bg-rule")} aria-hidden />
      <h4 className="font-serif text-base font-medium">{title}</h4>
      {items.length ? (
        <ul className="mt-1.5 space-y-1.5">
          {items.slice(0, 12).map((i) => (
            <li key={i.id} className={cn("rounded border px-3 py-2", i.focus ? "border-ink/60 bg-ink/[0.04]" : "border-rule")}>
              <div className="flex justify-between gap-3">
                <span className="font-mono text-[0.8rem]">{i.id}</span>
                <span className="num">{i.main}</span>
              </div>
              <div className="mt-0.5 text-xs text-graphite">{i.sub}</div>
            </li>
          ))}
          {items.length > 12 && <li className="text-xs text-graphite">and {items.length - 12} more</li>}
        </ul>
      ) : empty ? (
        <p className={cn("mt-1.5 rounded border border-dashed px-3 py-2", danger ? "border-redink/50 text-redink" : "border-rule text-graphite")}>{empty}</p>
      ) : null}
    </li>
  );
}
