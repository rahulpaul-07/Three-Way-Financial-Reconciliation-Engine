import { motion, useReducedMotion } from "framer-motion";
import { useMemo } from "react";
import type { Meta, Run, Txn } from "@/lib/types";
import { cn, pct, rupees } from "@/lib/utils";
import { ButtonLink } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/panel";
import { TickMark } from "@/components/ui/tick-mark";
import { REPO } from "./links";

// The settlement the hero reconciles. Real rows from datasets/01-reference,
// read from the snapshot at runtime so the picture cannot drift from the data.
const HERO_SETTLEMENT = "setl_0005";

interface Line { order: string; method: string; ledger: number; gross: number; fee: number; net: number; label: string }

function pickExample(run: Run | null) {
  const rec = run?.records;
  if (!rec) return null;
  const byId = new Map(run!.resolutions.map((r) => [r.entity_id, r]));
  const members = (sid: string) => rec.txns.filter((t) => t.settlement_id === sid);
  const settlement = rec.settlements.find((s) => s.settlement_id === HERO_SETTLEMENT)
    ?? rec.settlements.find((s) => members(s.settlement_id).length >= 4 && s.total_paise > 0);
  if (!settlement) return null;
  const orders = new Map(rec.orders.map((o) => [o.order_id, o]));
  const lines: Line[] = members(settlement.settlement_id).map((t: Txn) => ({
    order: t.order_ref ?? t.txn_id,
    method: t.payment_method,
    ledger: orders.get(t.order_ref ?? "")?.order_amount_paise ?? 0,
    gross: t.gross_amount_paise, fee: t.fee_paise + t.gst_on_fee_paise, net: t.net_amount_paise,
    label: byId.get(t.order_ref ?? "")?.classification ?? "clean",
  }));
  const bankRes = run!.resolutions.find((r) => r.entity_type === "bank_row" && r.matched_to === settlement.settlement_id);
  const bank = rec.bank.find((b) => b.bank_txn_id === bankRes?.entity_id);
  return { settlement, lines, bank };
}

export function Hero({ reference, meta }: { reference: Run | null; meta: Meta | null }) {
  const example = useMemo(() => pickExample(reference), [reference]);
  return (
    <section id="top" className="relative overflow-hidden border-b border-rule">
      <LedgerBackdrop />
      <div className="relative mx-auto grid max-w-page gap-12 px-5 pb-16 pt-12 sm:px-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:items-center lg:gap-14 lg:pb-24 lg:pt-20">
        <div className="max-w-xl">
          <h1 className="text-display font-medium">Three systems record every sale. They never agree.</h1>
          <p className="mt-6 max-w-prose text-lg leading-relaxed text-graphite">
            The merchant's ledger has the order amount. The payment gateway has it less its fee.
            The bank has one netted credit a day or two later, covering dozens of orders, with no line items.
            This engine reconciles all three, explains every difference it can, and hands the rest to a person with a reason attached.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href="#workbench" variant="ink">Open the workbench</ButtonLink>
            <ButtonLink href={REPO}>Read the source</ButtonLink>
          </div>
          <dl className="mt-10 grid max-w-md grid-cols-3 gap-x-6 border-t border-rule pt-5 text-sm">
            <Fact term="resolved on the reference batch" value={meta ? pct(meta.headline.resolution_rate) : undefined} />
            <Fact term="agreement with the answer key" value={meta ? pct(meta.headline.accuracy, 0) : undefined} />
            <Fact term="unseen defects caught" value={meta?.headline.detection} />
          </dl>
        </div>
        <div className="min-w-0">
          {example ? <ReconcileSheet {...example} /> : <Skeleton className="h-[26rem] w-full" />}
        </div>
      </div>
    </section>
  );
}

/** Faint ruled paper behind the opening, fading out before the text starts. */
function LedgerBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="ruled absolute inset-0 opacity-[0.55]"
        style={{ maskImage: "linear-gradient(to bottom, rgb(0 0 0 / 0.5), transparent 72%)",
                 WebkitMaskImage: "linear-gradient(to bottom, rgb(0 0 0 / 0.5), transparent 72%)" }} />
      <div className="absolute inset-y-0 left-1/2 hidden w-px bg-rule/60 lg:block"
        style={{ maskImage: "linear-gradient(to bottom, rgb(0 0 0 / 0.6), transparent 80%)",
                 WebkitMaskImage: "linear-gradient(to bottom, rgb(0 0 0 / 0.6), transparent 80%)" }} />
    </div>
  );
}

function Fact({ term, value }: { term: string; value?: string }) {
  return (
    <div>
      <dd className="num font-serif text-2xl text-ink">{value ?? <Skeleton className="h-7 w-14" />}</dd>
      <dt className="mt-1 leading-snug text-graphite">{term}</dt>
    </div>
  );
}

function ReconcileSheet({ settlement, lines, bank }: NonNullable<ReturnType<typeof pickExample>>) {
  const reduce = useReducedMotion();
  const netSum = lines.reduce((a, l) => a + l.net, 0);
  const ties = bank ? bank.movement_paise === settlement.total_paise && netSum === settlement.total_paise : false;
  const step = 0.16;
  const tieAt = 0.5 + lines.length * step + 0.25;

  return (
    <figure>
      <div className="overflow-hidden rounded-lg border border-rule bg-sheet">
        <div className="scroll-x">
          <table className="w-full border-collapse whitespace-nowrap text-[0.8rem] sm:min-w-[33rem] sm:text-sm">
            <caption className="sr-only">
              One settlement reconciled across the merchant ledger, the gateway report and the bank statement
            </caption>
            <thead>
              <tr className="border-b border-ink/60 text-left align-bottom font-serif text-[0.95rem]">
                <th className="py-3 pl-3 font-medium sm:pl-4"><span className="sm:hidden">Ledger</span><span className="hidden sm:inline">Merchant ledger</span></th>
                <th className="hidden sm:table-cell"><span className="sr-only">Ledger amount</span></th>
                <th className="w-8"><span className="sr-only">Amount agrees with gateway</span></th>
                <th className="hidden py-3 font-medium sm:table-cell">Gateway: fee</th>
                <th className="py-3 pr-2 text-right font-medium sm:pr-4"><span className="sm:hidden">Gateway net</span><span className="hidden sm:inline">then net</span></th>
                <th className="py-3 pr-4 text-right font-medium">Bank statement</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => {
                const later = l.label !== "clean" && l.label !== "rounding_noise";
                return (
                  <tr key={l.order} className="h-9 border-b border-rule/70">
                    <td className="pl-3 font-mono text-[0.75rem] text-graphite sm:pl-4 sm:text-[0.8rem]">{l.order}</td>
                    <td className="num hidden pr-2 text-right sm:table-cell">{rupees(l.ledger)}</td>
                    <td className="text-tick"><TickMark delay={reduce ? 0 : 0.5 + i * step} /></td>
                    <td className="num hidden pr-4 text-right text-graphite sm:table-cell">
                      {l.fee ? `− ${rupees(l.fee)}` : <span className="text-xs">{l.method.toUpperCase()}, none</span>}
                    </td>
                    <td className="num pr-2 text-right sm:pr-4">
                      {rupees(l.net)}
                      {later && <sup className="ml-0.5 text-settled" title={l.label.replace(/_/g, " ")}>†</sup>}
                    </td>
                    {i === 0 && (
                      <td rowSpan={lines.length} className="relative w-[7.5rem] border-l border-rule/70 pr-3 align-middle sm:w-[12rem] sm:pr-4">
                        <Brace rows={lines.length} delay={reduce ? 0 : tieAt - 0.3} />
                        <div className="ml-5 whitespace-normal text-right sm:ml-6">
                          <div className="whitespace-nowrap text-xs text-graphite">{bank?.value_date ?? settlement.payout_date}</div>
                          <div className="num font-serif text-base sm:text-xl">{rupees(bank?.movement_paise ?? 0)}</div>
                          <div className="mt-1 text-xs leading-snug text-graphite">{bank?.description}</div>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2} className="py-3 pl-3 text-xs text-graphite sm:pl-4">Captured {settlement.capture_date}</td>
                <td className="hidden sm:table-cell" />
                <td className="hidden py-3 pr-4 text-right text-xs text-graphite sm:table-cell">sum of nets</td>
                <td className="py-3 pr-4 text-right">
                  <span className="totals num inline-block px-1 font-medium">{rupees(netSum)}</span>
                </td>
                <td className="py-3 pr-4 text-right">
                  <motion.span initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: tieAt, duration: 0.3 }}
                    className={cn("inline-flex items-center gap-1.5 text-sm font-medium", ties ? "text-tick" : "text-redink")}>
                    {ties ? <><TickMark delay={reduce ? 0 : tieAt} size={16} /> ties<span className="hidden sm:inline"> to the paisa</span></> : "does not tie"}
                  </motion.span>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
      <figcaption className="mt-3 max-w-prose text-sm text-graphite">
        Settlement <span className="font-mono text-[0.8rem]">{settlement.settlement_id}</span> from the reference batch.
        The bank line names no orders; the engine proves which {lines.length} it pays for by the settlement reference and an exact tie.
        {lines.some((l) => l.label !== "clean" && l.label !== "rounding_noise") &&
          <> <span className="text-settled">†</span> Partly refunded later; the refund lands in a later payout and is explained, not a break.</>}
      </figcaption>
    </figure>
  );
}

function Brace({ rows, delay }: { rows: number; delay: number }) {
  const reduce = useReducedMotion();
  const h = rows * 32;
  return (
    <svg className="absolute left-0 top-1/2 -translate-y-1/2 text-tick" width="18" height={h} viewBox={`0 0 18 ${h}`} aria-hidden>
      <motion.path
        d={`M2 4 Q 9 4 9 ${h / 4} L 9 ${h / 2 - 6} Q 9 ${h / 2} 16 ${h / 2} Q 9 ${h / 2} 9 ${h / 2 + 6} L 9 ${(3 * h) / 4} Q 9 ${h - 4} 2 ${h - 4}`}
        fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round"
        initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
        transition={{ delay, duration: 0.5, ease: "easeInOut" }} />
    </svg>
  );
}
