"""
Structured, JSON-ready view of one reconciliation run.

`report.py` renders a run as HTML for a person to read. This module renders
the same run as data, for the web dashboard and for anything else that wants
to consume it programmatically. Both read the same engine output; neither
recomputes a classification.

Everything numeric stays in integer paise. The dashboard formats for display;
converting to rupees here would reintroduce floats into a money pipeline at
the last step.

Run directly to write a snapshot:

    python src/analysis.py --data datasets/01-reference --out run.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import MONEY_MOVING_STATUSES, NON_SETTLING_STATUSES  # noqa: E402
from evaluate import grade, grade_detection, load_truth, wilson_interval  # noqa: E402
from matcher import Engine, Resolution, load  # noqa: E402
from taxonomy import TAXONOMY, describe  # noqa: E402

# The bundled batches in datasets/, with what each one is for. Read by the API
# (to list and validate names) and by the site build (to label snapshots).
DATASET_INFO = [
    {"name": "01-reference", "title": "Reference",
     "blurb": "The batch every headline figure refers to. 120 orders, seed 42."},
    {"name": "02-small", "title": "Small",
     "blurb": "60 orders. A proportionally larger unsettled tail."},
    {"name": "03-large", "title": "Large",
     "blurb": "1,000 orders. Defect counts fixed, so the defect rate falls."},
    {"name": "04-ambiguous", "title": "Ambiguous",
     "blurb": "Settlements sharing an amount and window, references stripped."},
    {"name": "05-compound", "title": "Compound",
     "blurb": "Several defects on one record -- where accuracy degrades."},
    {"name": "06-dense", "title": "Dense",
     "blurb": "Four times the defect rate, non-interacting. Accuracy holds."},
    {"name": "08-unseen", "title": "Unseen defects",
     "blurb": "Nine defect classes planted from outside the original taxonomy."},
]

TIER_NAMES = {0: "self-consistency", 1: "exact key join",
              2: "deterministic inference", 3: "reference recovery"}

# Above this many rows the raw records are left out of the payload. The
# dashboard's lineage drawer needs them, but a 50,000-row upload would make
# the response larger than the insight is worth.
RECORD_LIMIT = 20_000


def _iso(v) -> str:
    return v.isoformat() if isinstance(v, (date, datetime)) else str(v)


def _records(orders, txns, settlements, bank) -> dict:
    def row(obj) -> dict:
        return {k: (_iso(v) if isinstance(v, (date, datetime)) else v)
                for k, v in asdict(obj).items()}
    return {"orders": [row(o) for o in orders],
            "txns": [row(t) for t in txns],
            "settlements": [row(s) for s in settlements],
            "bank": [row(b) | {"movement_paise": b.movement_paise}
                     for b in bank]}


def _amount_and_date(r: Resolution, idx: dict) -> tuple[int, str]:
    """The money a resolution concerns and the date it belongs to."""
    if r.entity_type == "order" and r.entity_id in idx["order"]:
        o = idx["order"][r.entity_id]
        return o.order_amount_paise, o.order_datetime.date().isoformat()
    if r.entity_type == "txn" and r.entity_id in idx["txn"]:
        t = idx["txn"][r.entity_id]
        return t.gross_amount_paise, t.txn_datetime.date().isoformat()
    if r.entity_type == "settlement" and r.entity_id in idx["settlement"]:
        s = idx["settlement"][r.entity_id]
        return s.total_paise, s.payout_date.isoformat()
    if r.entity_type == "bank_row" and r.entity_id in idx["bank"]:
        b = idx["bank"][r.entity_id]
        return b.movement_paise, b.value_date.isoformat()
    if r.entity_type == "statement_gap":
        bid = r.entity_id.removeprefix("GAP_BEFORE_")
        rows = idx["bank_list"]
        for i, b in enumerate(rows):
            if b.bank_txn_id == bid and i > 0:
                gap = b.balance_paise - (rows[i - 1].balance_paise + b.movement_paise)
                return gap, b.value_date.isoformat()
    return 0, ""


def _money_flow(txns, settlements, resolutions) -> dict:
    """
    Where the captured money went, as a set of flows that conserve.

    Every node's outflows sum to its inflow by construction: net is derived as
    gross - fee - gst rather than read from the net column, so a row with an
    arithmetic error cannot make the diagram leak. That error is reported by
    the engine; the diagram's job is to show proportions.
    """
    known = {s.settlement_id for s in settlements}
    pay = [t for t in txns if t.txn_type == "payment"
           and t.status not in NON_SETTLING_STATUSES]

    gross = sum(t.gross_amount_paise for t in pay)
    fees = sum(t.fee_paise for t in pay)
    gst = sum(t.gst_on_fee_paise for t in pay)
    net_of = lambda ts: sum(t.gross_amount_paise - t.fee_paise  # noqa: E731
                            - t.gst_on_fee_paise for t in ts)
    in_setl = net_of(t for t in pay if t.settlement_id in known)
    awaiting = net_of(t for t in pay if not t.settlement_id)
    dangling = net_of(t for t in pay if t.settlement_id and t.settlement_id not in known)

    # Each settlement's payout is the sum of its members' nets, refunds and
    # chargebacks included. What the settlements pay out is therefore the net
    # that entered them minus those reversals, and the reversal flow is that
    # difference -- defined so the diagram cannot leak.
    computed: dict[str, int] = defaultdict(int)
    for t in txns:
        if t.settlement_id in known:
            computed[t.settlement_id] += t.net_amount_paise
    payout = min(in_setl, sum(max(0, v) for v in computed.values()))
    reversals = in_setl - payout

    matched_ids = {r.matched_to for r in resolutions
                   if r.entity_type == "bank_row"
                   and r.classification in ("clean", "split_settlement")}
    credited = min(payout, sum(max(0, v) for k, v in computed.items()
                               if k in matched_ids))
    not_credited = payout - credited

    nodes = ["Captured gross", "MDR fees", "GST on fees", "Net of fees",
             "In a settlement", "Awaiting payout", "Unknown settlement",
             "Refunds & chargebacks", "Net payout", "Credited & matched",
             "Not matched in bank"]
    links = [
        (0, 1, fees), (0, 2, gst), (0, 3, gross - fees - gst),
        (3, 4, in_setl), (3, 5, awaiting), (3, 6, dangling),
        (4, 7, reversals), (4, 8, payout),
        (8, 9, credited), (8, 10, not_credited),
    ]
    return {
        "nodes": [{"name": n} for n in nodes],
        "links": [{"source": a, "target": b, "value": v}
                  for a, b, v in links if v > 0],
        "totals": {"gross": gross, "fees": fees, "gst": gst,
                   "awaiting": awaiting, "reversals": reversals,
                   "payout": payout, "credited": credited,
                   "not_credited": not_credited, "dangling": dangling},
    }


def _daily(orders, txns, settlements, bank, rows) -> list[dict]:
    days: dict[str, Counter] = defaultdict(Counter)
    for t in txns:
        if t.txn_type == "payment" and t.status not in NON_SETTLING_STATUSES:
            days[t.txn_datetime.date().isoformat()]["captured"] += t.gross_amount_paise
    for s in settlements:
        days[s.payout_date.isoformat()]["settled"] += s.total_paise
    for b in bank:
        days[b.value_date.isoformat()]["banked"] += b.movement_paise
    for r in rows:
        if not r["resolved"] and r["date"]:
            days[r["date"]]["exceptions"] += 1
    return [{"date": d, "captured": c["captured"], "settled": c["settled"],
             "banked": c["banked"], "exceptions": c["exceptions"]}
            for d, c in sorted(days.items())]


def analyse(datadir: Path, source: str = "", include_records: bool = True) -> dict:
    """Run the engine over a batch directory and describe the result."""
    orders, txns, settlements, bank = load(datadir)
    if not orders:
        raise ValueError("the ledger contains no rows")

    t0 = time.perf_counter()
    resolutions = Engine(orders, txns, settlements, bank).run()
    engine_ms = (time.perf_counter() - t0) * 1000

    idx = {"order": {o.order_id: o for o in orders},
           "txn": {t.txn_id: t for t in txns},
           "settlement": {s.settlement_id: s for s in settlements},
           "bank": {b.bank_txn_id: b for b in bank},
           "bank_list": bank}

    rows = []
    for r in resolutions:
        amount, day = _amount_and_date(r, idx)
        info = describe(r.classification)
        rows.append({**asdict(r), "amount_paise": amount, "date": day,
                     "severity": info.severity})

    resolved = sum(1 for r in resolutions if r.resolved)
    lo, hi = wilson_interval(resolved, len(resolutions))
    by_class = Counter(r.classification for r in resolutions)
    by_severity = Counter(x["severity"] for x in rows)
    tiers = Counter(r.tier for r in resolutions if r.resolved)
    exposure = sum(abs(x["amount_paise"]) for x in rows
                   if x["severity"] == "break")

    grading = None
    truth_path = datadir / "ground_truth.csv"
    if truth_path.exists() and load_truth(datadir):
        metrics, summ = grade(datadir)
        grading = {
            "graded": summ["graded"], "correct": summ["correct"],
            "accuracy": summ["accuracy"], "accuracy_ci": summ["accuracy_ci"],
            "per_class": sorted(
                ({"label": m.label, "tp": m.tp, "fp": m.fp, "fn": m.fn,
                  "precision": m.precision, "recall": m.recall, "f1": m.f1,
                  "support": m.support} for m in metrics.values()),
                key=lambda m: -m["support"]),
            "misclassified": [{"entity_id": a, "expected": b, "got": c}
                              for a, b, c in summ["misclassified"]],
        }

    detection = None
    if truth_path.exists():
        try:
            outcomes, dsum = grade_detection(datadir)
        except Exception:                                 # noqa: BLE001
            outcomes, dsum = [], {"total": 0}
        if dsum.get("total"):
            detection = {k: v for k, v in dsum.items()} | {
                "outcomes": [asdict(o) for o in outcomes]}

    n_rows = len(orders) + len(txns) + len(settlements) + len(bank)
    return {
        "schema": 1,
        "source": source or datadir.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine_ms": round(engine_ms, 3),
        "sources": {"orders": len(orders), "txns": len(txns),
                    "settlements": len(settlements), "bank": len(bank)},
        "summary": {
            "entities": len(resolutions), "resolved": resolved,
            "unresolved": len(resolutions) - resolved,
            "resolution_rate": resolved / len(resolutions) if resolutions else 0,
            "resolution_ci": [lo, hi],
            "tiers": {str(k): v for k, v in sorted(tiers.items())},
            "by_class": dict(by_class.most_common()),
            "by_severity": dict(by_severity),
            "exposure_paise": exposure,
        },
        "grading": grading,
        "detection": detection,
        "money_flow": _money_flow(txns, settlements, resolutions),
        "daily": _daily(orders, txns, settlements, bank, rows),
        "resolutions": rows,
        "records": (_records(orders, txns, settlements, bank)
                    if include_records and n_rows <= RECORD_LIMIT else None),
    }


def taxonomy_payload() -> dict:
    return {"tiers": {str(k): v for k, v in TIER_NAMES.items()},
            "classes": [asdict(c) | {"real_break": c.real_break}
                        for c in TAXONOMY.values()]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--no-records", action="store_true")
    args = ap.parse_args()
    payload = analyse(Path(args.data), include_records=not args.no_records)
    text = json.dumps(payload, separators=(",", ":"))
    if args.out == "-":
        print(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text) // 1024} KB)")


if __name__ == "__main__":
    main()
