"""
Compute the expected answers for data/router_eval.jsonl without any model.

    python scripts/router_eval_gold.py --check     # recompute and compare (exit 1 on drift)
    python scripts/router_eval_gold.py --write     # fill in computed fields

The request set, the routes and the gold SQL are written by hand. This script
only runs the gold SQL on a plain connection to the reconciled batch (it does
not go through run_query, so the answer key shares no code with the system
being scored) and records what it returns:

  * data requests get `expected`: {"numbers": [...], "strings": [...]}.
    A paise column becomes rupees, any other integer is kept as it is, and a
    text cell becomes a lowercase string. Numbers are stored as magnitudes,
    because the grounding check (numbers_in) does not read signs.
  * investigator requests get `matcher_classification`, the engine's own label
    for the record, so a run can be compared with it later. The record must be
    an unresolved exception, or the request would be mislabelled.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core import paise_to_rupees_str  # noqa: E402
from matcher import Engine, load  # noqa: E402
from sql_ask import build_from_dir  # noqa: E402

EVAL_PATH = ROOT / "data" / "router_eval.jsonl"
ROUTES = ("investigator", "data", "human")


def load_eval(path: Path = EVAL_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _magnitude(text: str) -> str:
    return str(abs(Decimal(text)))


def compute_expected(conn, gold_sql: str) -> dict[str, list[str]]:
    cur = conn.execute(gold_sql)
    names = [d[0] for d in cur.description]
    numbers: list[str] = []
    strings: list[str] = []
    for row in cur.fetchall():
        for name, value in zip(names, row, strict=True):
            if value is None:
                continue
            if isinstance(value, int):
                text = paise_to_rupees_str(value) if name.endswith("_paise") else str(value)
                numbers.append(_magnitude(text))
            else:
                strings.append(str(value).lower())
    return {"numbers": numbers, "strings": strings}


def unresolved_classifications(datadir: Path = ROOT / "data") -> dict[str, str]:
    orders, txns, settlements, bank = load(datadir)
    return {r.entity_id: r.classification
            for r in Engine(orders, txns, settlements, bank).run() if not r.resolved}


def recompute(items: list[dict]) -> list[dict]:
    """Return copies of the items with every computed field filled in."""
    conn = build_from_dir(ROOT / "data")
    exceptions = unresolved_classifications()
    out = []
    for item in items:
        item = {k: v for k, v in item.items()
                if k not in ("expected", "matcher_classification")}
        if item["route"] == "data":
            item["expected"] = compute_expected(conn, item["gold_sql"])
        elif item["route"] == "investigator":
            item["matcher_classification"] = exceptions[item["entity_id"]]
        out.append(item)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = ap.parse_args()

    stored = load_eval()
    fresh = recompute(stored)
    if args.write:
        EVAL_PATH.write_text(
            "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in fresh),
            encoding="utf-8")
        print(f"wrote {len(fresh)} requests to {EVAL_PATH.relative_to(ROOT)}")
        return 0

    drift = [s["id"] for s, f in zip(stored, fresh, strict=True) if s != f]
    if drift:
        print(f"stored answers differ from the recomputed ones: {', '.join(drift)}",
              file=sys.stderr)
        return 1
    print(f"{len(stored)} requests; stored answers match the gold SQL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
