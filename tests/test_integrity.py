"""
Unit tests for the rules added after the adversarial harness found four blind
spots, and for the two unseen classes the engine now names instead of lumping
into `orphan_bank_credit`.

Each rule is tested in both directions with records built by hand: the defect
must be flagged, and the nearest legitimate record must not be. A rule that
catches its defect by also flagging ordinary rows is a false-positive
generator, which in reconciliation is nearly as costly as a miss -- it buries
the real breaks in noise.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import expected_fee, working_day_window  # noqa: E402
from matcher import BankRow, Engine, Order, Settlement, Txn  # noqa: E402

CAPTURE = date(2026, 8, 10)          # a Monday
PAYOUT = working_day_window(CAPTURE)[0]


def order(oid="ORD1", amount=45000, currency="INR", method="card"):
    return Order(oid, amount, currency, datetime(2026, 8, 10, 10), "C1",
                 "paid", method)


def payment(tid="pay_1", oid="ORD1", amount=45000, method="card",
            sid="setl_1"):
    fee, gst = expected_fee(amount, method)
    return Txn(tid, "payment", oid, amount, fee, gst, amount - fee - gst,
               datetime(2026, 8, 10, 10), sid, method, "captured")


def settlement(sid="setl_1", total=0, utr="UTR1"):
    return Settlement(sid, CAPTURE, PAYOUT, total, utr)


def credit(bid, amount, utr=None, day=None, balance=0):
    return BankRow(bid, day or PAYOUT, "NEFT CR", amount, None, balance, utr)


def debit(bid, amount, day, balance=0):
    return BankRow(bid, day, "NEFT RETURN", None, amount, balance, None)


def with_balances(rows, opening=1_000_000):
    bal = opening
    for r in rows:
        bal += r.movement_paise
        r.balance_paise = bal
    return rows


def run(orders=(), txns=(), settlements=(), bank=()):
    res = Engine(list(orders), list(txns), list(settlements),
                 with_balances(list(bank))).run()
    ids = [r.entity_id for r in res]
    assert len(ids) == len(set(ids)), "an entity was reported twice"
    return {r.entity_id: r for r in res}


class TestCurrency:

    def test_foreign_currency_order_is_flagged(self):
        p = payment()
        out = run([order(currency="USD")], [p],
                  [settlement(total=p.net_amount_paise)],
                  [credit("B1", p.net_amount_paise, "UTR1")])
        assert out["ORD1"].classification == "currency_mismatch"
        assert not out["ORD1"].resolved

    def test_inr_in_any_case_or_padding_is_not_flagged(self):
        p = payment()
        out = run([order(currency=" inr ")], [p],
                  [settlement(total=p.net_amount_paise)],
                  [credit("B1", p.net_amount_paise, "UTR1")])
        assert out["ORD1"].classification == "clean"


class TestDuplicateBankCredit:

    def test_second_credit_for_a_claimed_settlement_is_flagged(self):
        p = payment()
        net = p.net_amount_paise
        out = run([order()], [p], [settlement(total=net)],
                  [credit("B1", net, "UTR1"), credit("B2", net, "UTR1")])
        assert out["B1"].classification == "clean"
        assert out["B2"].classification == "duplicate_bank_row"
        assert out["B2"].matched_to == "setl_1"
        assert not out["B2"].resolved

    def test_distinct_utrs_with_equal_amounts_are_not_duplicates(self):
        a = payment("pay_1", "ORD1", sid="setl_1")
        b = payment("pay_2", "ORD2", sid="setl_2")
        net = a.net_amount_paise
        out = run([order("ORD1"), order("ORD2")], [a, b],
                  [settlement("setl_1", net, "UTR1"),
                   settlement("setl_2", net, "UTR2")],
                  [credit("B1", net, "UTR1"), credit("B2", net, "UTR2")])
        assert out["B1"].classification == out["B2"].classification == "clean"


class TestDanglingSettlementRef:

    def test_reference_to_an_unknown_settlement_is_flagged(self):
        p = payment(sid="setl_9999")
        out = run([order()], [p])
        assert out["pay_1"].classification == "dangling_settlement_ref"
        assert out["pay_1"].matched_to == "setl_9999"

    def test_known_or_absent_reference_is_not_flagged(self):
        known = payment("pay_1", "ORD1", sid="setl_1")
        pending = payment("pay_2", "ORD2", sid=None)
        out = run([order("ORD1"), order("ORD2")], [known, pending],
                  [settlement(total=known.net_amount_paise)],
                  [credit("B1", known.net_amount_paise, "UTR1")])
        assert "pay_1" not in out and "pay_2" not in out
        assert out["ORD2"].classification == "unsettled"


class TestRefundFee:

    def _refund(self, fee, gst):
        return Txn("rfnd_1", "refund", "ORD1", -45000, fee, gst,
                   -45000 - fee - gst, datetime(2026, 8, 11, 10), None,
                   "card", "processed")

    def test_fee_on_a_refund_is_flagged(self):
        out = run([order()], [payment(sid=None), self._refund(900, 162)])
        assert out["rfnd_1"].classification == "unreversed_refund_fee"
        # The order-level classification is unaffected: it is a refund.
        assert out["ORD1"].classification == "refund"

    def test_fee_free_refund_is_not_flagged(self):
        out = run([order()], [payment(sid=None), self._refund(0, 0)])
        assert "rfnd_1" not in out

    def test_arithmetic_break_is_reported_once_not_twice(self):
        bad = self._refund(900, 162)
        bad.net_amount_paise += 1
        out = run([order()], [payment(sid=None), bad])
        assert out["rfnd_1"].classification == "net_arithmetic_error"


class TestSplitSettlement:
    """A UPI order carries no fee, so its net is exactly the settlement total."""

    def _run(self, bank):
        p = payment(amount=100_000, method="upi")
        return run([order(amount=100_000, method="upi")], [p],
                   [settlement(total=100_000, utr=None)], bank)

    def test_two_instalments_summing_exactly_are_matched(self):
        out = self._run([credit("B1", 60_000), credit("B2", 40_000)])
        assert out["B1"].classification == "split_settlement"
        assert out["B2"].classification == "split_settlement"
        assert out["B1"].resolved and out["B1"].matched_to == "setl_1"
        assert "setl_1" not in out, "a paid settlement was reported missing"

    def test_parts_outside_the_payout_window_are_not_matched(self):
        late = date(2026, 9, 30)
        out = self._run([credit("B1", 60_000, day=late),
                         credit("B2", 40_000, day=late)])
        assert out["B1"].classification == "orphan_bank_credit"
        assert out["setl_1"].classification == "settlement_not_in_bank"

    def test_parts_that_do_not_sum_exactly_are_not_matched(self):
        out = self._run([credit("B1", 60_000), credit("B2", 39_999)])
        assert out["B1"].classification == "orphan_bank_credit"


class TestPayoutReversal:

    def _batch(self, days_later):
        p = payment()
        net = p.net_amount_paise
        ret = date.fromordinal(PAYOUT.toordinal() + days_later)
        return run([order()], [p], [settlement(total=net)],
                   [credit("B1", net, "UTR1"), debit("B2", net, ret)])

    def test_debit_returning_a_recent_payout_is_named(self):
        out = self._batch(2)
        assert out["B1"].classification == "clean"
        assert out["B2"].classification == "payout_reversal"
        assert not out["B2"].resolved and out["B2"].matched_to == "setl_1"

    def test_debit_long_after_the_payout_stays_an_orphan(self):
        out = self._batch(30)
        assert out["B2"].classification == "orphan_bank_credit"


def test_every_class_the_engine_can_emit_is_in_the_taxonomy():
    """
    The agent's allowed values and the report's break grouping both read
    taxonomy.py. A class emitted by the matcher but missing there would be
    silently downgraded by the agent and mis-grouped by the report.
    """
    import re
    from taxonomy import AGENT_CLASSIFICATIONS, TAXONOMY
    src = (Path(__file__).resolve().parent.parent / "src" / "matcher.py").read_text()
    emitted = set(re.findall(r'classification="([a-z_]+)"', src))
    emitted |= {"refund", "partial_refund"}      # chosen by expression
    assert emitted <= set(TAXONOMY), emitted - set(TAXONOMY)
    assert set(TAXONOMY) - {"clean"} <= set(AGENT_CLASSIFICATIONS)
