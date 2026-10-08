"""
Run the loop engine and the LangGraph engine against a live model on the same
exceptions, record everything, and summarise it.

    python scripts/live_engine_compare.py run --provider groq --label smoke --limit 2 --reps 1
    python scripts/live_engine_compare.py run --provider groq --label full --reps 2
    python scripts/live_engine_compare.py run --provider groq --label extra --rep-offset 2 --only ID
    python scripts/live_engine_compare.py summarise results/engine_compare/groq_*_full.json

Measurement rules:

  * One provider, one model, no failover. The provider class is built directly
    with a pinned model, so a result is never attributed to a model that did
    not produce it. Provider and model are written into every result file.
  * A hard cap on model calls, counted across every run in results/ (the
    ledger file), so a bad loop cannot spend past it. Rate-limit retries are
    counted separately and never as successful calls.
  * The agents are used as they are. Nothing here changes their behaviour; the
    provider is wrapped to time, count and wait out rate limits, nothing more.
  * A call is never dropped. A 429 is retried after the vendor's Retry-After
    hint (or an exponential backoff); a daily limit, an unreasonably long wait
    or too many retries stops the run, saves progress, and the same command
    resumes from the saved file.
  * API keys are read from the environment by the provider and never written
    to a result.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent import ResolutionAgent, build_context  # noqa: E402
from evaluate import cohens_kappa  # noqa: E402
from investigate import facts_for  # noqa: E402
from llm import REGISTRY, LLMResponse, Provider  # noqa: E402
from matcher import Engine, load  # noqa: E402
from tools import InvestigationTools  # noqa: E402

RESULTS = ROOT / "results" / "engine_compare"
LEDGER = ROOT / "results" / "call_ledger.json"
DEFAULT_CAP = 600

MAX_RETRIES_PER_CALL = 6
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 60.0
# A wait longer than this is a quota that resets later, not a burst limit.
MAX_WAIT_S = 900.0


class RunStopped(RuntimeError):
    """The run cannot continue; progress is saved and the command can resume."""


class CapReached(RunStopped):
    pass


class DailyLimit(RunStopped):
    pass


class RetriesExhausted(RunStopped):
    pass


class Ledger:
    """Cumulative call and retry counts across runs, saved after every change."""

    def __init__(self, path: Path, cap: int):
        self.path, self.cap = path, cap
        self.calls = self.retries = 0
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.calls, self.retries = doc["calls"], doc.get("retries", 0)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"calls": self.calls,
                                         "retries": self.retries}),
                             encoding="utf-8")

    def spend(self) -> None:
        if self.calls >= self.cap:
            raise CapReached(f"hard cap of {self.cap} model calls reached")
        self.calls += 1
        self._save()

    def retry(self) -> None:
        self.retries += 1
        self._save()


_HINT_PATTERNS = (
    # Groq: "Please try again in 7.66s" or "in 1m2.5s"
    re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.I),
    # Gemini: "retryDelay': '30s'"
    re.compile(r"retry\w*delay\W+(\d+(?:\.\d+)?)s", re.I),
)


def parse_retry_hint(text: str) -> float | None:
    """Seconds the vendor asked us to wait, read out of an error message."""
    m = _HINT_PATTERNS[0].search(text)
    if m and any(m.groups()):
        h, mi, sec = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(sec or 0)
    m = _HINT_PATTERNS[1].search(text)
    return float(m.group(1)) if m else None


def is_rate_limited(resp: LLMResponse) -> bool:
    if resp.ok:
        return False
    low = resp.error.lower()
    return (resp.retry_after is not None or "429" in low
            or any(k in low for k in ("rate limit", "rate_limit",
                                      "resource_exhausted", "too many requests")))


class MeasuredProvider(Provider):
    """Delegates to a real provider, records each call and waits out 429s."""

    def __init__(self, inner: Provider, ledger: Ledger, sleep=time.sleep):
        self.inner, self.ledger, self.sleep = inner, ledger, sleep
        self.name = inner.name
        self.available = inner.available
        self.reason = getattr(inner, "reason", "")
        self.calls: list[dict] = []
        self.retries = 0

    def complete(self, system, messages, tools=None, max_tokens=1024, model=None):
        self.ledger.spend()
        attempt, waited, retries_here = 0, 0.0, 0
        while True:
            t0 = time.perf_counter()
            resp: LLMResponse = self.inner.complete(system, messages, tools,
                                                    max_tokens, model=model)
            elapsed = time.perf_counter() - t0
            if not is_rate_limited(resp):
                break

            self.retries += 1
            retries_here += 1
            self.ledger.retry()
            if resp.quota_exhausted:
                raise DailyLimit(f"daily limit: {resp.error}")
            hint = resp.retry_after
            if hint is None:
                hint = parse_retry_hint(resp.error)
            wait = hint if hint is not None else min(
                BACKOFF_BASE_S * 2 ** attempt, BACKOFF_MAX_S)
            if wait > MAX_WAIT_S:
                raise DailyLimit(f"asked to wait {wait:.0f}s: {resp.error}")
            attempt += 1
            if attempt > MAX_RETRIES_PER_CALL:
                raise RetriesExhausted(
                    f"{MAX_RETRIES_PER_CALL} retries on one call: {resp.error}")
            pause = wait + 1.0      # a small cushion over the vendor's figure
            print(f"    rate limited; waiting {pause:.0f}s "
                  f"(retry {attempt}/{MAX_RETRIES_PER_CALL})", flush=True)
            self.sleep(pause)
            waited += pause

        self.calls.append({
            "seconds": round(elapsed, 3),
            "ok": resp.ok,
            "tool_calls_requested": len(resp.tool_calls),
            "input_tokens": resp.usage.get("input"),
            "output_tokens": resp.usage.get("output"),
            "retries": retries_here,
            "waited_seconds": round(waited, 1),
            "error": resp.error[:120],
        })
        return resp

    def assistant_turn(self, resp):
        return self.inner.assistant_turn(resp)

    def tool_results_turn(self, results):
        return self.inner.tool_results_turn(results)


def _git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _make_agent(engine: str, tools, provider):
    if engine == "langgraph":
        from agent_graph import GraphResolutionAgent
        return GraphResolutionAgent(tools, provider=provider)
    return ResolutionAgent(tools, provider=provider)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", text).strip("-")


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _record(engine, rep, r, out, seconds, made) -> dict:
    waited = sum(c["waited_seconds"] for c in made)
    return {
        "engine": engine, "rep": rep,
        "entity_id": r.entity_id, "entity_type": r.entity_type,
        "matcher_classification": r.classification,
        "classification": out.classification,
        "agreed": out.classification == r.classification,
        "resolved": out.resolved, "terminated": out.terminated,
        "model_calls": out.model_calls,
        "tool_calls": len(out.steps),
        "tool_calls_per_round": [c["tool_calls_requested"] for c in made],
        "seconds": round(seconds, 2),
        "seconds_excluding_waits": round(seconds - waited, 2),
        "retries": sum(c["retries"] for c in made),
        "input_tokens": sum(c["input_tokens"] or 0 for c in made),
        "output_tokens": sum(c["output_tokens"] or 0 for c in made),
        "call_errors": [c["error"] for c in made if c["error"]],
        "reasoning": out.reasoning,
        "analyst_note": out.analyst_note,
        "steps": [asdict(s) for s in out.steps],
    }


def run(args, provider_factory=None, sleep=time.sleep) -> int:
    orders, txns, settlements, bank = load(Path(args.data))
    resolutions = Engine(orders, txns, settlements, bank).run()
    exceptions = [r for r in resolutions if not r.resolved]
    if args.only:
        wanted = set(args.only.split(","))
        exceptions = [r for r in exceptions if r.entity_id in wanted]
    if args.limit:
        exceptions = exceptions[:args.limit]

    # Built directly with one pinned model: no chain, so no failover.
    cls = REGISTRY[args.provider]
    inner = provider_factory() if provider_factory else cls(model=args.model or None)
    if not inner.available:
        print(f"provider unavailable: {inner.reason}", file=sys.stderr)
        return 2
    model = getattr(inner, "model", "") or args.model

    ledger = Ledger(LEDGER, args.cap)
    provider = MeasuredProvider(inner, ledger, sleep=sleep)
    tools = InvestigationTools(orders, txns, settlements, bank)

    engines = args.engines.split(",")
    identity = {
        "provider": args.provider, "model": model, "failover": False,
        "data": args.data, "seed": args.seed, "engines": engines,
        "reps": args.reps, "rep_offset": args.rep_offset,
        "exception_ids": [r.entity_id for r in exceptions],
    }
    path = RESULTS / f"{args.provider}_{_slug(model)}_{args.label}.json"

    doc = {"meta": {**identity, "sessions": []}, "records": []}
    if path.exists() and not args.restart:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if {k: saved["meta"].get(k) for k in identity} != identity:
            print(f"{path.name} exists with different settings; use --restart "
                  f"to overwrite it", file=sys.stderr)
            return 2
        doc = saved
    done = {(r["engine"], r["rep"], r["entity_id"]) for r in doc["records"]}

    session = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "git_head": _git_head(), "command": " ".join(sys.argv),
               "resumed_records": len(doc["records"])}
    doc["meta"]["sessions"].append(session)
    doc["meta"]["cap"] = args.cap
    status = "complete"
    calls_at_start = ledger.calls

    try:
        for rep in range(args.rep_offset + 1, args.rep_offset + args.reps + 1):
            for engine in engines:
                agent = _make_agent(engine, tools, provider)
                for r in exceptions:
                    if (engine, rep, r.entity_id) in done:
                        continue
                    facts = facts_for(r, orders, txns, settlements, bank)
                    ctx = build_context(r.entity_id, r.entity_type, r.detail, facts)
                    first = len(provider.calls)
                    t0 = time.perf_counter()
                    try:
                        out = agent.investigate(r.entity_id, r.entity_type, ctx)
                    except RunStopped:
                        session["discarded_investigation"] = (
                            f"{engine} rep {rep} {r.entity_id}")
                        raise
                    seconds = time.perf_counter() - t0
                    rec = _record(engine, rep, r, out, seconds,
                                  provider.calls[first:])
                    doc["records"].append(rec)
                    _atomic_write(path, doc)
                    print(f"rep {rep} {engine:<9} {r.entity_id:<14} "
                          f"{out.classification:<28} {out.terminated:<10} "
                          f"{out.model_calls} calls {rec['retries']} retries "
                          f"{seconds:.1f}s", flush=True)
    except RunStopped as exc:
        status = f"incomplete: {exc}"
        print(f"\nstopped: {exc}\nprogress saved; run the same command to "
              f"resume", file=sys.stderr)

    session["status"] = status
    session["calls"] = ledger.calls - calls_at_start
    session["retries"] = provider.retries
    doc["meta"]["status"] = status
    doc["meta"]["ledger_calls_total"] = ledger.calls
    _atomic_write(path, doc)
    print(f"\nwrote {path}\n  this session: {session['calls']} calls, "
          f"{session['retries']} rate-limit retries; ledger total "
          f"{ledger.calls}/{args.cap} calls, {ledger.retries} retries")
    return 0 if status == "complete" else 1


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def summarise(args) -> int:
    metas, records = [], []
    for p in args.files:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        metas.append(doc["meta"])
        records.extend(doc["records"])
    if not records:
        print("no records")
        return 1

    priced = args.price_in is not None and args.price_out is not None
    print("# Live engine comparison\n")
    for m in metas:
        print(f"- provider={m['provider']}  model={m['model']}  seed={m['seed']}  "
              f"status={m.get('status', '?')}")
        for s in m["sessions"]:
            print(f"    - {s['started_utc']}  git={s['git_head']}  "
                  f"calls={s.get('calls', '?')}  retries={s.get('retries', '?')}  "
                  f"{s.get('status', '?')}")
    if priced:
        print(f"- cost assumes ${args.price_in}/M input and ${args.price_out}/M "
              f"output tokens")
    print()

    engines = sorted({r["engine"] for r in records})
    by = defaultdict(list)
    for r in records:
        by[(r["engine"], r["entity_id"])].append(r)

    print("## Per engine\n")
    head = ("| engine | investigations | agreed with matcher | kappa | resolved | "
            "model calls | tool calls | max tool calls in one round | "
            "mean s (excl. waits) | retries | in tok | out tok |")
    print(head + (" cost USD |" if priced else ""))
    print("|---|---|---|---|---|---|---|---|---|---|---|---|" + ("---|" if priced else ""))
    for e in engines:
        rs = [r for r in records if r["engine"] == e]
        agreed = sum(r["agreed"] for r in rs)
        kappa = cohens_kappa([r["classification"] for r in rs],
                             [r["matcher_classification"] for r in rs])
        rounds = [n for r in rs for n in r["tool_calls_per_round"]]
        tin = sum(r["input_tokens"] for r in rs)
        tout = sum(r["output_tokens"] for r in rs)
        row = (f"| {e} | {len(rs)} | {agreed}/{len(rs)} | {kappa:.2f} | "
               f"{sum(r['resolved'] for r in rs)} | "
               f"{sum(r['model_calls'] for r in rs)} | "
               f"{sum(r['tool_calls'] for r in rs)} | {max(rounds, default=0)} | "
               f"{statistics.mean(r['seconds_excluding_waits'] for r in rs):.1f} | "
               f"{sum(r['retries'] for r in rs)} | {tin} | {tout} |")
        if priced:
            row += f" {tin / 1e6 * args.price_in + tout / 1e6 * args.price_out:.2f} |"
        print(row)
    if not any(r["input_tokens"] for r in records):
        print("\nToken counts were not reported by this provider.")

    print("\n## Termination\n")
    for e in engines:
        term = Counter(r["terminated"] for r in records if r["engine"] == e)
        print(f"- {e}: " + ", ".join(f"{k}={v}" for k, v in sorted(term.items())))

    print("\n## Tool calls requested per model round (all runs)\n")
    dist = Counter(n for r in records for n in r["tool_calls_per_round"])
    print(", ".join(f"{k} tool call(s): {v} rounds" for k, v in sorted(dist.items())))

    print("\n## Per exception\n")
    ids = sorted({r["entity_id"] for r in records})
    print("| exception | matcher | " + " | ".join(engines) + " |")
    print("|---|---|" + "---|" * len(engines))
    unstable = []
    for i in ids:
        cells, matcher = [], ""
        for e in engines:
            rs = sorted(by[(e, i)], key=lambda r: r["rep"])
            matcher = rs[0]["matcher_classification"] if rs else matcher
            labels = [r["classification"] for r in rs]
            cells.append(" / ".join(labels))
            if len(set(labels)) > 1:
                unstable.append((e, i, labels))
        print(f"| {i} | {matcher} | " + " | ".join(cells) + " |")

    print("\n## Variance across repetitions\n")
    if unstable:
        for e, i, labels in unstable:
            print(f"- {e} {i}: {labels}")
    else:
        print("- every exception got the same classification on every repetition "
              "within each engine")

    if len(engines) == 2:
        print(f"\n## {engines[0]} vs {engines[1]}\n")
        pairs = [(a, b) for i in ids for a in by[(engines[0], i)]
                 for b in by[(engines[1], i)] if a["rep"] == b["rep"]]
        same = sum(a["classification"] == b["classification"] for a, b in pairs)
        print(f"- same classification on the same exception and repetition: "
              f"{same}/{len(pairs)}")
        for a, b in pairs:
            if a["classification"] != b["classification"]:
                print(f"- rep {a['rep']} {a['entity_id']}: {engines[0]}="
                      f"{a['classification']} {engines[1]}={b['classification']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--provider", required=True,
                   choices=sorted(k for k in REGISTRY if k != "none"))
    r.add_argument("--model", default="",
                   help="pinned for the whole run; default is the provider's "
                        "first listed model")
    r.add_argument("--data", default="data")
    r.add_argument("--seed", type=int, default=42,
                   help="recorded in the result; the batch is generated separately")
    r.add_argument("--engines", default="loop,langgraph")
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--rep-offset", type=int, default=0)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--only", default="", help="comma-separated entity ids")
    r.add_argument("--cap", type=int, default=DEFAULT_CAP)
    r.add_argument("--label", default="run")
    r.add_argument("--restart", action="store_true",
                   help="overwrite a saved result with different settings")
    r.set_defaults(fn=run)

    s = sub.add_parser("summarise")
    s.add_argument("files", nargs="+")
    s.add_argument("--price-in", type=float, default=None,
                   help="USD per million input tokens; omit for free tiers")
    s.add_argument("--price-out", type=float, default=None)
    s.set_defaults(fn=summarise)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
