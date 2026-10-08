"""
Run the multi-agent router on the 30-request evaluation set against a live
Gemini model, record everything, and score it.

    python scripts/router_eval.py models
    python scripts/router_eval.py run --model MODEL --label smoke --only R02,R11,R21 --cap 20
    python scripts/router_eval.py run --model MODEL --label full --reps 2 --cap 300
    python scripts/router_eval.py summarise results/router_eval/*_full.json

Measurement rules, the same as scripts/live_engine_compare.py:

  * One model, pinned, no failover. It is written into every result file.
  * A hard cap on model calls, counted across every run in this script's own
    ledger (results/router_ledger.json), so a bad loop cannot spend past it.
    Rate-limit retries are counted separately, never as successful calls.
  * A call is never dropped. A 429 is retried after the vendor's hint (or a
    backoff); a daily limit, an unreasonably long wait or too many retries stops
    the run, saves progress, and the same command resumes from the saved file.
  * The key is read from GOOGLE_API_KEY by the Gemini client and is never
    written to a result.
  * The router, prompts and tools are used as they are. A result file records a
    hash of every prompt, and a resume against changed prompts is refused, so
    numbers measured before and after prompt tuning cannot be mixed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from live_engine_compare import (  # noqa: E402
    BACKOFF_BASE_S,
    BACKOFF_MAX_S,
    MAX_RETRIES_PER_CALL,
    MAX_WAIT_S,
    DailyLimit,
    Ledger,
    RetriesExhausted,
    RunStopped,
    _atomic_write,
    _git_head,
    _slug,
    parse_retry_hint,
)
from pydantic import ConfigDict  # noqa: E402
from router_eval_gold import load_eval  # noqa: E402

from multi_agent.app import DEFAULT_TOTAL_BUDGET, RouterApp  # noqa: E402
from multi_agent.budget import PROVIDER_OUTAGE_CODES, scrub_secrets  # noqa: E402
from multi_agent.handoff import Reason  # noqa: E402
from multi_agent.routing import ROUTER_PROMPT  # noqa: E402
from multi_agent.specialists import DATA_BASE_PROMPT, INVESTIGATOR_BASE_PROMPT  # noqa: E402
from sql_ask import numbers_in  # noqa: E402

RESULTS = ROOT / "results" / "router_eval"
LEDGER = ROOT / "results" / "router_ledger.json"
DEFAULT_CAP = 300
OUTAGE_ATTEMPTS = 4          # tries per call on a 500, 503 or 504, the first included
KEY_ENV = "GOOGLE_API_KEY"
UNAVAILABLE = Reason.PROVIDER_UNAVAILABLE.value


# --------------------------------------------------------------------------
# The live model: counts calls against the ledger and waits out 429s
# --------------------------------------------------------------------------

class MeasuredModel(BaseLlm):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: BaseLlm
    ledger: Ledger
    sleep: object = asyncio.sleep
    jitter: object = random.random
    waits: list = []
    retries: int = 0

    def _outage_pause(self, exc: genai_errors.APIError, attempt: int) -> float:
        """The vendor's Retry-After when it sends one, else exponential backoff
        with jitter so concurrent runs do not retry in step. Clamped either way."""
        header = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "")
        try:
            hinted = float(header)
        except ValueError:
            hinted = None
        if hinted is not None and hinted >= 0:
            return min(hinted, BACKOFF_MAX_S)
        delay = BACKOFF_BASE_S * 2 ** (attempt - 1)
        return min(delay + self.jitter() * delay, BACKOFF_MAX_S)

    async def generate_content_async(self, llm_request, stream=False):
        self.ledger.spend()
        attempt, outages, waited = 0, 0, 0.0
        while True:
            try:
                responses = [r async for r in
                             self.inner.generate_content_async(llm_request, stream=False)]
                break
            except genai_errors.APIError as exc:
                if exc.code in PROVIDER_OUTAGE_CODES:
                    outages += 1
                    if outages >= OUTAGE_ATTEMPTS:
                        raise
                    pause = self._outage_pause(exc, outages)
                    self.retries += 1
                    self.ledger.retry()
                    print(f"    provider unavailable ({exc.code}); waiting {pause:.0f}s "
                          f"(attempt {outages + 1}/{OUTAGE_ATTEMPTS})", flush=True)
                    await self.sleep(pause)
                    waited += pause
                    continue
                if exc.code != 429:
                    raise
                message = str(exc)
                self.retries += 1
                self.ledger.retry()
                # Gemini's free-tier daily quota is reported by metric name.
                if "PerDay" in message:
                    raise DailyLimit(f"daily limit: {scrub_secrets(message)[:200]}") from None
                hint = parse_retry_hint(message)
                wait = hint if hint is not None else min(
                    BACKOFF_BASE_S * 2 ** attempt, BACKOFF_MAX_S)
                if wait > MAX_WAIT_S:
                    raise DailyLimit(f"asked to wait {wait:.0f}s") from None
                attempt += 1
                if attempt > MAX_RETRIES_PER_CALL:
                    raise RetriesExhausted(
                        f"{MAX_RETRIES_PER_CALL} retries on one call") from None
                pause = wait + 1.0
                print(f"    rate limited; waiting {pause:.0f}s "
                      f"(retry {attempt}/{MAX_RETRIES_PER_CALL})", flush=True)
                await self.sleep(pause)
                waited += pause
        self.waits.append(waited)
        for response in responses:
            yield response


def prompt_hash() -> str:
    """Identifies the prompts a result was measured with."""
    text = "\x00".join([ROUTER_PROMPT, INVESTIGATOR_BASE_PROMPT, DATA_BASE_PROMPT])
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def list_models(client) -> list[str]:
    """Names of the models that can generate text. Listing is free."""
    return sorted(m.name.removeprefix("models/") for m in client.models.list()
                  if "generateContent" in (m.supported_actions or []))


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def _record(item: dict, rep: int, out, seconds: float, waited: float, retries: int) -> dict:
    handoff, answer = out.handoff, out.answer
    return {
        "id": item["id"], "rep": rep, "expected_route": item["route"],
        "route": out.route, "status": out.status,
        "handoff_reason": handoff.reason.value if handoff else None,
        "handoff_agent": handoff.agent if handoff else None,
        "answer_agent": answer.agent if answer else None,
        "answer_text": answer.text if answer else "",
        "classification": (answer.data.get("classification") if answer else None),
        "resolved": (answer.data.get("resolved") if answer else None),
        "model_calls": out.model_calls,
        "calls": [asdict(c) for c in out.calls],
        "tools": [asdict(t) for t in out.tools],
        "router_raw": out.router_raw[:300],
        "seconds": round(seconds, 2),
        "seconds_excluding_waits": round(seconds - waited, 2),
        "retries": retries,
        "input_tokens": sum(c.input_tokens for c in out.calls),
        "output_tokens": sum(c.output_tokens for c in out.calls),
    }


def _make_model(name: str) -> BaseLlm:
    from google.adk.models.google_llm import Gemini
    return Gemini(model=name)


async def _run_requests(args, model, items, doc, path, done, session, ledger) -> str:
    measured = MeasuredModel(model=model.model, inner=model, ledger=ledger,
                             waits=[], retries=0)
    status = "complete"
    async with RouterApp(model=measured, data_dir=args.data,
                         total_budget=args.budget) as app:
        try:
            for rep in range(args.rep_offset + 1, args.rep_offset + args.reps + 1):
                for item in items:
                    if (rep, item["id"]) in done:
                        continue
                    waits_before, retries_before = len(measured.waits), measured.retries
                    t0 = time.perf_counter()
                    try:
                        out = await app.handle(item["request"])
                    except RunStopped:
                        session["discarded_request"] = f"rep {rep} {item['id']}"
                        raise
                    seconds = time.perf_counter() - t0
                    waited = sum(measured.waits[waits_before:])
                    rec = _record(item, rep, out, seconds, waited,
                                  measured.retries - retries_before)
                    doc["records"].append(rec)
                    _atomic_write(path, doc)
                    shown = out.handoff.reason.value if out.handoff else "answered"
                    print(f"rep {rep} {item['id']} want={item['route']:<12} "
                          f"got={str(out.route):<12} {shown:<20} "
                          f"{out.model_calls} calls {seconds:.1f}s", flush=True)
        except RunStopped as exc:
            status = f"incomplete: {exc}"
            print(f"\nstopped: {exc}\nprogress saved; run the same command to resume",
                  file=sys.stderr)
    session["retries"] = measured.retries
    return status


def run(args, model_factory=None) -> int:
    items = load_eval()
    if args.only:
        wanted = args.only.split(",")
        unknown = set(wanted) - {i["id"] for i in items}
        if unknown:
            print(f"unknown request ids: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        items = [i for i in items if i["id"] in wanted]

    if model_factory is None and not os.environ.get(KEY_ENV):
        print(f"{KEY_ENV} is not set in this terminal; no call was made", file=sys.stderr)
        return 2
    model = model_factory() if model_factory else _make_model(args.model)

    identity = {"model": model.model, "data": args.data, "reps": args.reps,
                "rep_offset": args.rep_offset, "budget": args.budget,
                "prompt_sha": prompt_hash(), "request_ids": [i["id"] for i in items]}
    path = RESULTS / f"{_slug(model.model)}_{args.label}.json"
    doc = {"meta": {**identity, "sessions": []}, "records": []}
    if path.exists() and not args.restart:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if {k: saved["meta"].get(k) for k in identity} != identity:
            print(f"{path.name} exists with different settings or prompts; use "
                  f"--restart to overwrite it", file=sys.stderr)
            return 2
        doc = saved
    done = {(r["rep"], r["id"]) for r in doc["records"]}

    ledger = Ledger(LEDGER, args.cap)
    session = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "git_head": _git_head(), "command": " ".join(sys.argv),
               "resumed_records": len(doc["records"])}
    doc["meta"]["sessions"].append(session)
    doc["meta"]["cap"] = args.cap
    calls_at_start = ledger.calls

    status = asyncio.run(_run_requests(args, model, items, doc, path, done, session, ledger))

    session["status"] = status
    session["calls"] = ledger.calls - calls_at_start
    doc["meta"]["status"] = status
    doc["meta"]["ledger_calls_total"] = ledger.calls
    _atomic_write(path, doc)
    print(f"\nwrote {path}\n  this session: {session['calls']} calls, "
          f"{session.get('retries', 0)} rate-limit retries; ledger total "
          f"{ledger.calls}/{args.cap} calls")
    return 0 if status == "complete" else 1


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def data_correct(item: dict, answer: str) -> bool:
    """Every expected number and string appears in the answer. This checks
    presence, not exclusivity: an answer that adds a wrong extra figure still
    passes here, though the grounding check has already refused ungrounded ones."""
    expected = item["expected"]
    found = set(numbers_in(answer))
    return (all(Decimal(n) in found for n in expected["numbers"])
            and all(s in answer.lower() for s in expected["strings"]))


def _pct(num: int, den: int) -> str:
    return f"{num}/{den}" + (f" ({100 * num / den:.0f}%)" if den else "")


def score(records: list[dict], items: list[dict]) -> dict:
    """All the numbers the report prints, from the saved records alone."""
    by_id = {i["id"]: i for i in items}
    # A request the provider could not serve says nothing about the router, so
    # it is listed and left out of every rate. Its calls still count toward cost.
    unavailable = [r["id"] for r in records if r["handoff_reason"] == UNAVAILABLE]
    recs = [(r, by_id[r["id"]]) for r in records if r["handoff_reason"] != UNAVAILABLE]

    routed_right = [(r, i) for r, i in recs if r["route"] == i["route"]]
    confusion = Counter((i["route"], r["route"] or "none") for r, i in recs)

    # The costly error: a request that needed a person and was answered anyway.
    missed = [r["id"] for r, i in recs
              if i["route"] == "human" and r["status"] == "answered"]
    unneeded = [(r["id"], r["handoff_reason"]) for r, i in recs
                if i["route"] != "human" and r["status"] == "handoff"]

    data = {"correct": [], "wrong": [], "handed_off": []}
    for r, i in recs:
        if i["route"] != "data" or r["route"] != "data":
            continue
        if r["status"] == "handoff":
            data["handed_off"].append(r["id"])
        elif data_correct(i, r["answer_text"]):
            data["correct"].append(r["id"])
        else:
            data["wrong"].append(r["id"])

    def agreement(hinted: bool) -> dict:
        group = [(r, i) for r, i in routed_right
                 if i["route"] == "investigator" and i["hint_in_request"] == hinted]
        agreed = [r for r, i in group
                  if r["status"] == "answered"
                  and r["classification"] == i["matcher_classification"]]
        return {"routed": len(group), "agreed": len(agreed),
                "handed_off": sum(r["status"] == "handoff" for r, _ in group),
                "items": len({i["id"] for _, i in group})}

    calls = [r["model_calls"] for r in records]
    secs = sorted(r["seconds_excluding_waits"] for r in records)
    return {
        "n": len(recs),
        "unavailable": unavailable,
        "routing_right": len(routed_right),
        "confusion": confusion,
        "boundary": [(i["id"], i["route"], r["route"], r["status"])
                     for r, i in recs if i["boundary"]],
        "missed_handoffs": missed,
        "unneeded_handoffs": unneeded,
        "data": data,
        "data_total": sum(i["route"] == "data" for _, i in recs),
        "hinted": agreement(True),
        "unhinted": agreement(False),
        "model_calls": sum(calls),
        "calls_per_request": statistics.mean(calls) if calls else 0,
        "input_tokens": sum(r["input_tokens"] for r in records),
        "output_tokens": sum(r["output_tokens"] for r in records),
        "retries": sum(r["retries"] for r in records),
        "p50_s": statistics.median(secs) if secs else 0,
        "max_s": secs[-1] if secs else 0,
    }


def summarise(args) -> int:
    metas, records = [], []
    for p in args.files:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        metas.append(doc["meta"])
        records.extend(doc["records"])
    if not records:
        print("no records")
        return 1
    s = score(records, load_eval())
    priced = args.price_in is not None and args.price_out is not None

    print("# Router evaluation\n")
    for m in metas:
        print(f"- model={m['model']}  prompts={m['prompt_sha']}  "
              f"reps={m['reps']}  status={m.get('status', '?')}")
        for ses in m["sessions"]:
            print(f"    - {ses['started_utc']}  git={ses['git_head']}  "
                  f"calls={ses.get('calls', '?')}  {ses.get('status', '?')}")
    print(f"- {s['n']} request runs scored")
    print(f"- provider_unavailable: {len(s['unavailable'])} {s['unavailable']} "
          f"(left out of every rate below; the service, not the router, failed)\n")

    print("## Routing\n")
    print(f"- routed to the correct destination: {_pct(s['routing_right'], s['n'])}")
    print("- expected -> chosen: " + ", ".join(
        f"{e}->{c}: {n}" for (e, c), n in sorted(s["confusion"].items())))
    print("- boundary cases (id, expected, chosen, outcome): " + "; ".join(
        f"{i} {e}/{c}/{st}" for i, e, c, st in s["boundary"]))
    print(f"- missed handoffs (needed a person, answered anyway; the costly error): "
          f"{len(s['missed_handoffs'])} {s['missed_handoffs']}")
    print(f"- unneeded handoffs (a specialist could have answered): "
          f"{len(s['unneeded_handoffs'])} {s['unneeded_handoffs']}\n")

    d = s["data"]
    print("## Data agent\n")
    print(f"- correct: {len(d['correct'])}, wrong: {len(d['wrong'])} {d['wrong']}, "
          f"handed off: {len(d['handed_off'])} {d['handed_off']} "
          f"(of {s['data_total']} data requests; correct means every expected figure "
          f"and string is present in the answer)\n")

    print("## Investigator: end-to-end agreement with the matcher\n")
    print("Counted over requests routed to the investigator. A handoff there is "
          "not an agreement.\n")
    for key, label in (("hinted", "hinted (R01-R05, R09)"),
                       ("unhinted", "unhinted (R06-R08, R10)")):
        a = s[key]
        print(f"- {label}: {_pct(a['agreed'], a['routed'])} agreed, "
              f"{a['handed_off']} handed off")
    print("\nHints in the request make the hinted number easier. The unhinted group "
          "has only 4 items, so one miss moves that number by 25 points per "
          "repetition.\n")

    print("## Cost and latency\n")
    print(f"- model calls: {s['model_calls']} ({s['calls_per_request']:.1f} per request)")
    print(f"- tokens: {s['input_tokens']} in, {s['output_tokens']} out; "
          f"{s['retries']} rate-limit retries")
    print(f"- seconds per request excluding waits: median {s['p50_s']:.1f}, "
          f"max {s['max_s']:.1f}")
    if priced:
        cost = (s["input_tokens"] / 1e6 * args.price_in
                + s["output_tokens"] / 1e6 * args.price_out)
        print(f"- cost at ${args.price_in}/M in and ${args.price_out}/M out: ${cost:.2f}")
    return 0


# --------------------------------------------------------------------------

def models(_args) -> int:
    if not os.environ.get(KEY_ENV):
        print(f"{KEY_ENV} is not set in this terminal", file=sys.stderr)
        return 2
    from google.genai import Client
    for name in list_models(Client()):
        print(name)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="list text models (free)").set_defaults(fn=models)

    r = sub.add_parser("run")
    r.add_argument("--model", required=True, help="pinned for the whole run")
    r.add_argument("--data", default="data")
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--rep-offset", type=int, default=0)
    r.add_argument("--only", default="", help="comma-separated request ids, e.g. R02,R11,R21")
    r.add_argument("--budget", type=int, default=DEFAULT_TOTAL_BUDGET,
                   help="model calls allowed per request, all agents together")
    r.add_argument("--cap", type=int, default=DEFAULT_CAP,
                   help="hard cap on model calls, cumulative in the ledger")
    r.add_argument("--label", default="run")
    r.add_argument("--restart", action="store_true")
    r.set_defaults(fn=run)

    s = sub.add_parser("summarise")
    s.add_argument("files", nargs="+")
    s.add_argument("--price-in", type=float, default=None)
    s.add_argument("--price-out", type=float, default=None)
    s.set_defaults(fn=summarise)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
