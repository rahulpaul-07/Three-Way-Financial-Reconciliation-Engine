"""
find_subset_summing_to must not build its pool from payments that are already
in a settlement.

The live evaluation on seed 42 showed why. BNK000006 is a planted orphan
credit of 2750.00. The tool handed the agent pay_000060 + pay_000068 +
pay_000079, which sum to exactly that, but all three are already paid out in
setl_0002 and setl_0005. The agent called it a split settlement and marked it
resolved. These tests pin the filter that stops that.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from matcher import load  # noqa: E402
from tools import TOOL_SCHEMA, InvestigationTools  # noqa: E402

SETTLED_TRIPLE = {"pay_000060", "pay_000068", "pay_000079"}
ORPHAN_CREDIT_PAISE = 275000
ORPHAN_CREDIT_DATE = "2026-08-16"


@pytest.fixture(scope="module")
def batch():
    return load(ROOT / "data")


def call(batch, **kw):
    return InvestigationTools(*batch).find_subset_summing_to(**kw)


def test_orphan_credit_is_not_explained_by_settled_payments(batch):
    r = call(batch, target_paise=ORPHAN_CREDIT_PAISE,
             on_date=ORPHAN_CREDIT_DATE, window_days=3, max_terms=5)
    assert not r.ok
    assert r.evidence["excluded_settled"] > 0
    assert "already-settled" in r.summary


def test_wider_window_does_not_bring_the_settled_triple_back(batch):
    r = call(batch, target_paise=ORPHAN_CREDIT_PAISE,
             on_date=ORPHAN_CREDIT_DATE, window_days=5, max_terms=5)
    assert not r.ok


def test_genuine_unsettled_split_is_still_found(batch):
    # pay_000101 and pay_000005 are both 349.00, captured on 21 Aug with no
    # settlement_id: unsettled payments that a lump credit could really cover.
    r = call(batch, target_paise=69800, on_date="2026-08-21",
             window_days=3, max_terms=2)
    assert r.ok
    assert set(r.evidence["txn_ids"]) == {"pay_000101", "pay_000005"}
    by_id = {t.txn_id: t for t in batch[1]}
    assert all(by_id[i].settlement_id is None for i in r.evidence["txn_ids"])


def test_payment_pointing_at_an_unreported_settlement_stays_in_the_pool(batch):
    # A settlement_id that is not in the report means the payment is in no
    # reported payout, so it can still explain an orphan credit.
    orders, txns, settlements, bank = batch
    txns = [replace(t, settlement_id="setl_9999") if t.txn_id in SETTLED_TRIPLE
            else t for t in txns]
    r = InvestigationTools(orders, txns, settlements, bank).find_subset_summing_to(
        target_paise=ORPHAN_CREDIT_PAISE, on_date=ORPHAN_CREDIT_DATE,
        window_days=3, max_terms=5)
    assert r.ok
    assert set(r.evidence["txn_ids"]) == SETTLED_TRIPLE


def test_schema_tells_the_model_about_the_filter():
    desc = next(t["description"] for t in TOOL_SCHEMA
                if t["name"] == "find_subset_summing_to")
    assert "already included in a settlement are excluded" in desc
