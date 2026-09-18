"""
Adversarial generator -- defect classes the engine was never designed around.

Why this exists
---------------
`generate_data.py` plants thirteen defect types and records each one in the
answer key. The reconciliation engine names those same thirteen. Accuracy
measured across that set is a measure of internal consistency: the set of
things the generator can produce and the set of things the engine can name are
the same set, so the number cannot fall for the reason that matters.

This module plants defects drawn from outside that set. They are real failures
in payment operations, and the engine has no label for any of them.

The metric that follows is different, and the difference is the point
------------------------------------------------------------------
Classification accuracy on these records is structurally guaranteed to be zero.
The engine cannot emit `currency_mismatch` because no such class exists. A zero
that was unavoidable measures nothing.

The question worth asking is narrower:

    Did the engine refuse to call a broken record clean?

That is *detection*, not classification. An engine that has never heard of a
reversed payout, but whose amount-tie invariant refuses to reconcile the row
anyway, has generalised -- its invariants caught a defect it had no name for.
An engine that marks the row clean has failed in the way that actually costs
money in reconciliation: invisibly.

So each planted record lands in one of three states:

    detected       engine emitted a non-clean classification
    misattributed  detected, but under a label that misdirects the analyst
    silent pass    engine emitted `clean`, or emitted nothing at all

Silent-pass rate is the honest headline. See `grade_detection` in evaluate.py.

Substrate
---------
The base generator's own defects are switched off by default, so the substrate
is clean and the only defects present are the unseen ones. That keeps the
measurement unconfounded: any non-clean classification is either a correct
detection or a false positive, with no third possibility to argue about.
`--mixed` restores the base defects for a harder, noisier batch.

What this does NOT establish
----------------------------
The substrate is shared with `generate_data.py` on purpose -- same order book,
same fee table, same working-day calendar, same narration templates -- so that
any change in the measured numbers is attributable to the defects alone.

The consequence is that the shared assumptions stay shared. Currency is INR,
fees follow `core.expected_fee`, settlement is T+1 working days. If the engine
is wrong *about those*, neither generator can reveal it. This measures
generalisation to unseen defect classes, not correctness of the model of
payments that both generators encode.

Run:  python src/adversarial_data.py --seed 7 --orders 120 --out datasets/08-unseen
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, fields
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import GST_RATE, expected_fee, rupees_to_paise  # noqa: E402
from generate_data import (  # noqa: E402
    BankRow, DefectPlan, Generator, GatewayRow, NARRATION_TEMPLATES_CLEAN,
)

# Labels this module plants. None of these appear in the engine's taxonomy;
# the grader uses this set to decide which records are graded for detection
# rather than for classification.
UNSEEN_LABELS = frozenset({
    "split_settlement",
    "payout_reversal",
    "duplicate_bank_row",
    "dangling_settlement_ref",
    "unreversed_refund_fee",
    "currency_mismatch",
    "amount_transposition",
    "balance_inconsistency",
})


@dataclass
class UnseenPlan:
    """
    How many of each unseen defect to plant.

    `amount_transposition` is a deliberate positive control. The engine DOES
    compare ledger amount against gateway gross (matcher.py, tier 1), so this
    one should be detected. If a run reports every class as a silent pass
    including this one, the harness is broken rather than the engine.
    """
    split_settlement: int = 3
    payout_reversal: int = 2
    duplicate_bank_row: int = 3
    dangling_settlement_ref: int = 2
    unreversed_refund_fee: int = 3
    currency_mismatch: int = 3
    amount_transposition: int = 3
    balance_inconsistency: int = 2


def zero_plan() -> DefectPlan:
    """Base generator with every planted defect switched off."""
    return DefectPlan(**{f.name: 0 for f in fields(DefectPlan)})


class AdversarialGenerator(Generator):
    """
    Runs the ordinary pipeline, then layers unseen defects on top.

    Post-hoc mutation rather than hooking into the base pipeline: the base
    stages are left exactly as they are, so a change in results cannot be
    blamed on a subtly different substrate.
    """

    def __init__(self, *args, unseen: UnseenPlan | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.unseen = unseen or UnseenPlan()
        self._unseen_ids: set[str] = set()
        self._frozen_balances = False
        # Settlements already carrying an unseen defect. Without this, a later
        # pass can mutate a settlement an earlier pass already touched, and the
        # record ends up with two defects on it. The detection is then credited
        # to whichever class the answer key names, which may not be the one
        # that actually caused it. That is a measurement error, not a finding.
        self._touched: set[str] = set()

    # ---- helpers ---------------------------------------------------------

    def _mark(self, eid: str, etype: str, cls: str, target: str,
              notes: str) -> None:
        self._truth(eid, etype, cls, target, notes)
        self._unseen_ids.add(eid)

    def _bank_row_for(self, sid: str) -> BankRow | None:
        """The statement line paying out a given settlement, by UTR."""
        utr = self.settlements[sid]["utr"]
        for b in self.bank:
            if b.utr == utr:
                return b
        return None

    def _clean_settlements(self) -> list[str]:
        """
        Settlements not yet carrying an unseen defect.

        Checking `_touched` rather than only the statement line matters: a
        duplicate credit marks the NEW row, leaving the original unmarked, so a
        settlement could look untouched while already being part of a defect.
        """
        return [sid for sid, s in self.settlements.items()
                if s["total_paise"] > 0
                and sid not in self._touched
                and self._bank_row_for(sid) is not None]

    def _take(self, n: int) -> list[str]:
        """Claim up to n untouched settlements, marking them as taken."""
        pool = self._clean_settlements()
        chosen = self.rng.sample(pool, min(n, len(pool)))
        self._touched.update(chosen)
        return chosen

    def _rebuild_balances(self) -> None:
        """
        Recompute the running balance from the opening balance and the
        movements actually present.

        Every mutation below adds, removes or resizes a statement line. Without
        this the balance column would no longer tie, and the engine's
        balance-continuity check would fire -- reporting a missing row that was
        never missing. That would confound the measurement: a detection
        credited to the intended defect when it was really caused by the
        instrument. Called once, after all structural mutations.
        """
        if self._frozen_balances:
            raise RuntimeError("balances already frozen; rebuild would erase "
                               "a deliberately planted inconsistency")
        balance = self.opening_balance_paise
        for b in self.bank:
            movement = (b.credit_paise or 0) - (b.debit_paise or 0)
            balance += movement
            b.balance_paise = balance

    def _narration(self, utr: str) -> str:
        return self.rng.choice(NARRATION_TEMPLATES_CLEAN).format(
            bank_code=self.rng.choice(["HDFC", "ICIC", "SBIN", "UTIB"]),
            utr=utr)

    # ---- entry point -----------------------------------------------------

    def run(self) -> None:
        super().run()
        self._apply_unseen()

    def _apply_unseen(self) -> None:
        self._split_settlements()
        self._reverse_payouts()
        self._duplicate_bank_rows()
        self._dangle_settlement_refs()
        self._unreverse_refund_fees()
        self._mismatch_currency()
        self._transpose_amounts()

        # Structural mutations are done; the statement is internally
        # consistent again before the one defect that deliberately is not.
        self.bank.sort(key=lambda b: (b.value_date, b.bank_txn_id))
        self._rebuild_balances()

        self._break_balance_continuity()
        self._frozen_balances = True

    # ---- 1. settlement paid out in two instalments -----------------------

    def _split_settlements(self) -> None:
        """
        One settlement, two bank credits summing to its total.

        The engine assumes one settlement pays out as one statement line that
        ties exactly. Neither half ties, and the original UTR is gone, so
        nothing can join on the key either. Real: banks split large NEFT
        payouts, and aggregators sometimes pay a settlement in tranches.
        """
        for sid in self._take(self.unseen.split_settlement):
            row = self._bank_row_for(sid)
            if row is None:
                continue
            total = self.settlements[sid]["total_paise"]
            first = int(total * 0.6)
            second = total - first
            if first <= 0 or second <= 0:
                continue

            self.bank.remove(row)
            for part, offset in ((first, 0), (second, 1)):
                utr = self._utr()          # a new reference, unknown to settlements.csv
                bid = self._next_bank_id()
                self.bank.append(BankRow(
                    bank_txn_id=bid,
                    value_date=row.value_date + timedelta(days=offset),
                    description=self._narration(utr),
                    credit_paise=part,
                    debit_paise=None,
                    balance_paise=0,       # set by _rebuild_balances
                    utr=utr,
                ))
                self._mark(bid, "bank_row", "split_settlement", sid,
                           f"settlement {sid} paid in two instalments; this "
                           f"line carries part of the total, so no single "
                           f"statement line ties to the settlement")

    # ---- 2. payout returned by the beneficiary bank ----------------------

    def _reverse_payouts(self) -> None:
        """
        A settlement credited normally, then debited back a day or two later.

        NEFT returns happen: wrong account, closed account, name mismatch. The
        credit still reconciles; the debit is money leaving that corresponds to
        no settlement. The engine has no concept of a reversed payout.
        """
        for sid in self._take(self.unseen.payout_reversal):
            row = self._bank_row_for(sid)
            if row is None:
                continue
            amount = self.settlements[sid]["total_paise"]
            bid = self._next_bank_id()
            self.bank.append(BankRow(
                bank_txn_id=bid,
                value_date=row.value_date + timedelta(days=self.rng.choice([1, 2])),
                description=f"NEFT RETURN-{row.utr or self._utr()}-BENEFICIARY "
                            f"ACCOUNT CLOSED",
                credit_paise=None,
                debit_paise=amount,
                balance_paise=0,
                utr=None,
            ))
            self._mark(bid, "bank_row", "payout_reversal", sid,
                       f"payout for {sid} was returned; the original credit "
                       f"still reconciles, so the books look settled while the "
                       f"money is no longer there")

    # ---- 3. the same credit appearing twice ------------------------------

    def _duplicate_bank_rows(self) -> None:
        """
        The identical settlement credit present twice, same UTR and amount.

        Statement exports get concatenated, re-pulled after a timeout, or
        double-delivered. `duplicate_payment` in the base taxonomy is a
        gateway-side duplicate; nothing covers the bank side.
        """
        for sid in self._take(self.unseen.duplicate_bank_row):
            row = self._bank_row_for(sid)
            if row is None:
                continue
            bid = self._next_bank_id()
            self.bank.append(BankRow(
                bank_txn_id=bid,
                value_date=row.value_date,
                description=row.description,
                credit_paise=row.credit_paise,
                debit_paise=row.debit_paise,
                balance_paise=0,
                utr=row.utr,
            ))
            self._mark(bid, "bank_row", "duplicate_bank_row", sid,
                       f"exact duplicate of the credit for {sid}; if both are "
                       f"accepted the settlement is reconciled twice and the "
                       f"statement total is overstated")

    # ---- 4. a settlement reference pointing at nothing --------------------

    def _dangle_settlement_refs(self) -> None:
        """
        A gateway row whose `settlement_id` names a settlement that does not
        exist in the settlement report.

        The remaining books are kept tying: the settlement it left has its
        stated total and its bank credit reduced by the row's net, so no
        arithmetic check fires anywhere. What remains is purely a broken
        reference -- a row claiming to have been paid out under an identifier
        nobody can resolve.
        """
        placed = 0
        # Not routed through `_take`: this pass skips settlements with fewer
        # than two members, and consuming those would starve nothing useful.
        # Settlements are marked only once a defect is actually placed.
        pool = self._clean_settlements()
        self.rng.shuffle(pool)
        for sid in pool:
            if placed >= self.unseen.dangling_settlement_ref:
                break
            members = [t for t in self.gateway
                       if t.settlement_id == sid and t.txn_type == "payment"]
            if len(members) < 2:          # never orphan a whole settlement
                continue
            victim = self.rng.choice(members)
            row = self._bank_row_for(sid)
            if row is None or row.credit_paise is None:
                continue

            new_total = self.settlements[sid]["total_paise"] - victim.net_amount_paise
            if new_total <= 0:
                continue
            self.settlements[sid]["total_paise"] = new_total
            row.credit_paise = new_total

            victim.settlement_id = f"setl_{self.rng.randrange(9000, 9999)}"
            self._touched.add(sid)
            self._mark(victim.txn_id, "txn", "dangling_settlement_ref",
                       victim.settlement_id,
                       "settlement_id resolves to no settlement in the report; "
                       "the transaction claims to be paid out and nothing "
                       "contradicts it")
            placed += 1

    # ---- 5. a refund that was charged a fee ------------------------------

    def _unreverse_refund_fees(self) -> None:
        """
        A refund carrying a processing fee that was never reversed.

        `expected_fee` is applied only to the payment row. Once an order has a
        refund the engine classifies it `refund` and stops looking, so the
        refund's own fee and GST columns are never checked against any rule.
        The merchant is out of pocket and the books agree with themselves.
        """
        used = {t.entity_id for t in self.truth
                if t.expected_classification != "clean"}
        # UPI carries no MDR in `core.expected_fee`, so a refund fee on a UPI
        # order would be zero -- an inert record that looks like a planted
        # defect and scores as a silent pass the engine never had a chance to
        # catch. Restricted to methods that actually charge.
        pool = [l for l in self.ledger
                if l.order_id not in used
                and expected_fee(l.order_amount_paise, l.payment_method)[0] > 0]
        for l in self.rng.sample(pool, min(self.unseen.unreversed_refund_fee,
                                           len(pool))):
            pay = self._gw_for(l.order_id)
            if pay is None:
                continue
            gross = -l.order_amount_paise
            # A fee on a refund of the same size the capture was charged,
            # retained rather than returned.
            fee, gst = expected_fee(l.order_amount_paise, l.payment_method)
            txn_id = self._next_txn_id("rfnd")
            self.gateway.append(GatewayRow(
                txn_id=txn_id,
                txn_type="refund",
                order_ref=l.order_id,
                gross_amount_paise=gross,
                fee_paise=fee,
                gst_on_fee_paise=gst,
                # The row's own identity still holds, so no arithmetic check
                # fires. The defect is the presence of the fee, not a sum.
                net_amount_paise=gross - fee - gst,
                txn_datetime=pay.txn_datetime + timedelta(days=1),
                settlement_id=None,
                payment_method=l.payment_method,
                status="processed",
            ))
            # The ORDER is legitimately a refund, which is a known class. The
            # unseen defect belongs to the refund row itself.
            self._truth(l.order_id, "order", "refund", txn_id,
                        "fully refunded; the order-level classification is "
                        "correct and is not the defect under test")
            self._mark(txn_id, "txn", "unreversed_refund_fee", l.order_id,
                       "refund was charged a fee that was never reversed; the "
                       "row is internally consistent so no identity check "
                       "fires")

    # ---- 6. an order denominated in another currency ---------------------

    def _mismatch_currency(self) -> None:
        """
        A ledger row in USD settled in INR at face value.

        `currency` is parsed into the Order record (matcher.py) and never read
        again anywhere in the engine. The amounts tie numerically, so every
        check passes and 499 dollars reconcile against 499 rupees.
        """
        used = {t.entity_id for t in self.truth
                if t.expected_classification != "clean"}
        pool = [l for l in self.ledger if l.order_id not in used]
        for l in self.rng.sample(pool, min(self.unseen.currency_mismatch,
                                           len(pool))):
            l.currency = self.rng.choice(["USD", "AED", "SGD"])
            self._mark(l.order_id, "order", "currency_mismatch", "",
                       f"ledger records this order in {l.currency} while the "
                       f"gateway and bank are in INR; the amounts tie only "
                       f"because the unit is never checked")

    # ---- 7. transposed digits (positive control) -------------------------

    def _transpose_amounts(self) -> None:
        """
        Two adjacent digits swapped in the ledger amount.

        The classic manual-entry error: 45,710 keyed as 45,170. Included as a
        control, not as a hard case -- the engine compares ledger amount to
        gateway gross directly, so this should be detected. A run that reports
        it as a silent pass means the harness is wrong, not the engine.
        """
        used = {t.entity_id for t in self.truth
                if t.expected_classification != "clean"}
        pool = [l for l in self.ledger if l.order_id not in used]
        for l in self.rng.sample(pool, min(self.unseen.amount_transposition,
                                           len(pool))):
            digits = list(str(l.order_amount_paise))
            swapped = None
            for i in range(len(digits) - 1):
                if digits[i] != digits[i + 1]:
                    digits[i], digits[i + 1] = digits[i + 1], digits[i]
                    swapped = int("".join(digits))
                    break
            if swapped is None or swapped == l.order_amount_paise:
                continue
            original = l.order_amount_paise
            l.order_amount_paise = swapped
            self._mark(l.order_id, "order", "amount_transposition", "",
                       f"ledger amount {swapped} is {original} with two digits "
                       f"transposed; gateway and bank carry the original")

    # ---- 8. a running balance that does not tie --------------------------

    def _break_balance_continuity(self) -> None:
        """
        A balance column that disagrees with its own credit and debit columns,
        with no statement line missing.

        The engine infers a missing row from a balance discontinuity. Here the
        discontinuity is real and the row is not missing -- the statement
        itself is corrupt. Applied last, after the rebuild, because it is the
        one inconsistency that must survive.
        """
        eligible = [b for b in self.bank
                    if b.bank_txn_id not in self._unseen_ids]
        for b in self.rng.sample(eligible, min(self.unseen.balance_inconsistency,
                                               len(eligible))):
            drift = rupees_to_paise(Decimal(str(self.rng.choice([120, 75, 310]))))
            b.balance_paise += drift
            self._mark(b.bank_txn_id, "bank_row", "balance_inconsistency", "",
                       f"balance column overstates by {drift} paise against "
                       f"this row's own credit and debit; no line is missing, "
                       f"the statement is internally wrong")

    # ---- output ----------------------------------------------------------

    def write(self, outdir: Path) -> None:
        """
        Same five files as the base generator, with one extra column on the
        answer key: `outside_taxonomy`.

        The grader needs to know which records are unseen, because they are
        scored for detection rather than for classification. Readers that do
        not know about the column (matcher.load, evaluate.load_truth) use
        DictReader and ignore it.
        """
        super().write(outdir)

        with (outdir / "ground_truth.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["entity_id", "entity_type", "expected_classification",
                        "expected_match_target", "notes", "outside_taxonomy"])
            for r in sorted(self.truth, key=lambda x: x.entity_id):
                w.writerow([r.entity_id, r.entity_type,
                            r.expected_classification, r.expected_match_target,
                            r.notes,
                            "yes" if r.entity_id in self._unseen_ids else "no"])

    def unseen_summary(self) -> str:
        from collections import Counter
        counts = Counter(t.expected_classification for t in self.truth
                         if t.entity_id in self._unseen_ids)
        lines = ["unseen defects planted:"]
        for k, v in sorted(counts.items()):
            lines.append(f"  {k:<26} {v}")
        lines.append(f"  {'TOTAL':<26} {sum(counts.values())}")
        return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate a batch containing defect classes the engine "
                    "has no label for.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--orders", type=int, default=300)
    ap.add_argument("--days", type=int, default=30,
                    help="settlement batches are per capture day, so this "
                         "sets how many settlements exist to plant on")
    ap.add_argument("--out", type=str, default="datasets/08-unseen")
    ap.add_argument("--mixed", action="store_true",
                    help="also plant the base generator's known defects; "
                         "harder, but detections become harder to attribute")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    gen = AdversarialGenerator(
        seed=args.seed,
        n_orders=args.orders,
        n_days=args.days,
        plan=DefectPlan() if args.mixed else zero_plan(),
    )
    gen.run()
    gen.write(outdir)
    print(gen.summary())
    print()
    print(gen.unseen_summary())


if __name__ == "__main__":
    main()
