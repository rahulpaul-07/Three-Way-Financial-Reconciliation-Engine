"""
Evaluation harness.

Grades the reconciliation engine against `ground_truth.csv` -- the answer key
written by the generator and never read by the engine.

This is the part of the project that turns a match rate into a measured claim.
Reporting "92% resolved" says nothing about whether the 92% were classified
correctly. Reporting per-class precision and recall against a known answer key
says exactly that, and makes every number falsifiable.

Three levels of reporting:

  1. headline      resolution rate with a Wilson confidence interval
  2. per-class     precision, recall and F1 for each defect class
  3. variance      the same run repeated across independently seeded batches

Run:
    python src/evaluate.py --data data
    python src/evaluate.py --seeds 20          # variance across batches
    python src/evaluate.py --throughput        # scaling behaviour
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matcher import Engine, load  # noqa: E402


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def wilson_interval(successes: int, total: int, z: float = 1.96
                    ) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion.

    A match rate measured on 141 records is an estimate, not a constant. The
    normal approximation behaves badly near 0 and 1 and for small samples;
    the Wilson interval does not, which is why it is used here rather than
    the textbook p +/- z*sqrt(p(1-p)/n).
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt(p * (1 - p) / total
                            + z * z / (4 * total * total))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass
class ClassMetrics:
    """Per-class confusion counts and derived rates."""
    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def support(self) -> int:
        return self.tp + self.fn


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------

# The engine and the answer key describe the same facts from different angles.
# A few labels are equivalent rather than identical, and mapping them is a
# judgement that belongs here, stated openly, rather than hidden inside the
# matcher where it would inflate the score invisibly.
EQUIVALENT = {
    # the engine reports a missing statement line from the settlement side;
    # the answer key records it against the bank row that was dropped
    ("settlement_not_in_bank", "missing_bank_row"),
    ("missing_bank_row", "settlement_not_in_bank"),
    # a settlement recovered by amount+date when its narration was mangled is
    # a correct resolution; the key records why it was hard, not what it is
    ("clean", "messy_narration"),
}


def load_truth(datadir: Path) -> dict[str, str]:
    # utf-8-sig for the same reason as matcher.load: an answer key written by
    # Excel carries a byte order mark that would corrupt the first column name.
    with (datadir / "ground_truth.csv").open(encoding="utf-8-sig") as f:
        return {r["entity_id"]: r["expected_classification"]
                for r in csv.DictReader(f)}


def grade(datadir: Path) -> tuple[dict[str, ClassMetrics], dict]:
    orders, txns, settlements, bank = load(datadir)
    engine = Engine(orders, txns, settlements, bank)
    resolutions = engine.run()
    truth = load_truth(datadir)

    metrics: dict[str, ClassMetrics] = defaultdict(
        lambda: ClassMetrics(label=""))
    unmatched_entities: list[tuple[str, str, str]] = []

    graded = 0
    correct = 0

    for r in resolutions:
        expected = truth.get(r.entity_id)
        if expected is None:
            # Not in the answer key. The key records planted defects and clean
            # orders; entities it does not mention are not gradeable and are
            # counted separately rather than silently scored as correct.
            continue

        graded += 1
        got = r.classification
        ok = (got == expected) or ((got, expected) in EQUIVALENT)

        for label in (got, expected):
            if not metrics[label].label:
                metrics[label] = ClassMetrics(label=label)

        if ok:
            correct += 1
            metrics[expected].tp += 1
        else:
            metrics[got].fp += 1
            metrics[expected].fn += 1
            unmatched_entities.append((r.entity_id, expected, got))

    resolved = sum(1 for r in resolutions if r.resolved)
    tiers = Counter(r.tier for r in resolutions if r.resolved)

    lo, hi = wilson_interval(resolved, len(resolutions))
    acc_lo, acc_hi = wilson_interval(correct, graded) if graded else (0, 0)

    summary = {
        "entities": len(resolutions),
        "resolved": resolved,
        "resolution_rate": resolved / len(resolutions) if resolutions else 0,
        "resolution_ci": (lo, hi),
        "graded": graded,
        "correct": correct,
        "accuracy": correct / graded if graded else 0,
        "accuracy_ci": (acc_lo, acc_hi),
        "tiers": dict(tiers),
        "misclassified": unmatched_entities,
    }
    return dict(metrics), summary


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def print_report(metrics: dict[str, ClassMetrics], summary: dict) -> None:
    print("=" * 74)
    print("RECONCILIATION EVALUATION")
    print("=" * 74)
    print()

    lo, hi = summary["resolution_ci"]
    print(f"  entities examined     {summary['entities']}")
    print(f"  resolved              {summary['resolved']} "
          f"({summary['resolution_rate']:.1%})  "
          f"95% CI [{lo:.1%}, {hi:.1%}]")
    print(f"  exceptions            "
          f"{summary['entities'] - summary['resolved']}")
    print()

    alo, ahi = summary["accuracy_ci"]
    print(f"  graded vs answer key  {summary['graded']}")
    print(f"  classified correctly  {summary['correct']} "
          f"({summary['accuracy']:.1%})  "
          f"95% CI [{alo:.1%}, {ahi:.1%}]")
    print()

    print("  resolution by tier")
    tier_names = {0: "self-consistency", 1: "exact key join",
                  2: "deterministic inference", 3: "reference recovery"}
    for t in sorted(summary["tiers"]):
        n = summary["tiers"][t]
        print(f"    tier {t}  {n:>4}  "
              f"({n / summary['resolved']:.1%})  {tier_names.get(t, '')}")
    print()

    print("-" * 74)
    print(f"  {'class':<26}{'prec':>7}{'recall':>8}{'F1':>7}"
          f"{'support':>9}{'FP':>5}{'FN':>5}")
    print("-" * 74)

    for label in sorted(metrics, key=lambda k: -metrics[k].support):
        m = metrics[label]
        if m.support == 0 and m.fp == 0:
            continue
        print(f"  {label:<26}{m.precision:>7.2f}{m.recall:>8.2f}"
              f"{m.f1:>7.2f}{m.support:>9}{m.fp:>5}{m.fn:>5}")
    print("-" * 74)
    print()

    if summary["misclassified"]:
        print("  misclassified entities")
        for eid, expected, got in summary["misclassified"]:
            print(f"    {eid:<14} expected {expected:<24} got {got}")
    else:
        print("  no misclassifications against the answer key")
    print()


# --------------------------------------------------------------------------
# Variance across independently generated batches
# --------------------------------------------------------------------------

def run_variance(n_seeds: int, orders: int, workdir: Path) -> None:
    """
    A single run proves nothing. Regenerate the batch under different seeds
    and report the spread: same defect proportions, different data.
    """
    print("=" * 74)
    print(f"VARIANCE ACROSS {n_seeds} INDEPENDENTLY GENERATED BATCHES")
    print("=" * 74)
    print()

    rates, accs = [], []
    gen = Path(__file__).resolve().parent / "generate_data.py"

    for seed in range(1, n_seeds + 1):
        out = workdir / f"_eval_seed_{seed}"
        subprocess.run(
            [sys.executable, str(gen), "--seed", str(seed),
             "--orders", str(orders), "--out", str(out)],
            check=True, capture_output=True)
        _, summary = grade(out)
        rates.append(summary["resolution_rate"])
        accs.append(summary["accuracy"])
        print(f"  seed {seed:>3}   resolved {summary['resolution_rate']:>6.1%}"
              f"   accuracy {summary['accuracy']:>6.1%}"
              f"   entities {summary['entities']:>4}")

    def stats(xs):
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / len(xs)
        return mean, math.sqrt(var), min(xs), max(xs)

    rm, rs, rmin, rmax = stats(rates)
    am, asd, amin, amax = stats(accs)

    print()
    print("-" * 74)
    print(f"  resolution rate   {rm:.1%} +/- {rs:.1%}   "
          f"range [{rmin:.1%}, {rmax:.1%}]")
    print(f"  accuracy          {am:.1%} +/- {asd:.1%}   "
          f"range [{amin:.1%}, {amax:.1%}]")
    print("-" * 74)
    print()


# --------------------------------------------------------------------------
# Throughput
# --------------------------------------------------------------------------

def run_throughput(sizes: list[int], workdir: Path) -> None:
    """
    The track bar names throughput explicitly. Measured, not asserted.
    """
    print("=" * 74)
    print("THROUGHPUT")
    print("=" * 74)
    print()
    print(f"  {'orders':>8}{'entities':>10}{'generate':>12}"
          f"{'reconcile':>12}{'rows/sec':>12}")
    print("-" * 74)

    gen = Path(__file__).resolve().parent / "generate_data.py"

    for n in sizes:
        out = workdir / f"_eval_scale_{n}"
        t0 = time.perf_counter()
        subprocess.run(
            [sys.executable, str(gen), "--seed", "42",
             "--orders", str(n), "--out", str(out)],
            check=True, capture_output=True)
        t_gen = time.perf_counter() - t0

        orders, txns, settlements, bank = load(out)
        t1 = time.perf_counter()
        resolutions = Engine(orders, txns, settlements, bank).run()
        t_rec = time.perf_counter() - t1

        print(f"  {n:>8}{len(resolutions):>10}{t_gen:>11.2f}s"
              f"{t_rec:>11.3f}s{len(resolutions) / t_rec:>12,.0f}")
    print("-" * 74)
    print()


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """
    Agreement between two classifiers, corrected for chance.

    Reporting that the agent agreed with the deterministic engine on 12 of 13
    records is true and slightly generous. Two classifiers drawing from the
    same small label set will agree on some records by coincidence, and a raw
    percentage counts those as successes.

    Kappa is (observed - expected) / (1 - expected), where expected is the
    agreement two independent classifiers would reach given their individual
    label frequencies. 1.0 is perfect, 0.0 is chance, negative is worse than
    chance.

    On a sample this small the figure is unstable and should be read as an
    indication rather than a measurement -- which is itself worth stating,
    because a confident kappa on 13 records would be its own kind of
    overclaiming.
    """
    if not a or len(a) != len(b):
        return 0.0
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n

    labels = set(a) | set(b)
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


# --------------------------------------------------------------------------
# Adversarial evaluation
# --------------------------------------------------------------------------

def run_stress(scales: list[float], orders: int, seeds: int,
               workdir: Path, compound: bool = False) -> None:
    """
    Measure the engine as defect density rises.

    A reported accuracy on a realistic batch says nothing about where the
    system stops working. This raises the planted defect rate until it does,
    which is a more useful number than a best case -- and it is the number that
    tells an operator when to stop trusting the output.

    Each density is run across several seeds, because a single batch at high
    density is dominated by which defects happened to collide.
    """
    print("=" * 74)
    print("ADVERSARIAL EVALUATION -- accuracy as defect density rises"
          + ("  [compound]" if compound else ""))
    print("=" * 74)
    print()
    print(f"  {'scale':>6}{'defect rate':>14}{'resolved':>12}"
          f"{'accuracy':>12}{'exceptions':>13}{'worst seed':>13}")
    print("-" * 74)

    gen = Path(__file__).resolve().parent / "generate_data.py"

    for scale in scales:
        rates, accs, excs, densities = [], [], [], []
        for seed in range(1, seeds + 1):
            out = workdir / f"_stress_{scale}_{seed}"
            subprocess.run(
                [sys.executable, str(gen), "--seed", str(seed),
                 "--orders", str(orders), "--defect-scale", str(scale),
                 "--out", str(out)]
                + (["--compound"] if compound else []),
                check=True, capture_output=True)

            truth = load_truth(out)
            defective = sum(1 for v in truth.values() if v != "clean")
            densities.append(defective / len(truth) if truth else 0)

            _, summary = grade(out)
            rates.append(summary["resolution_rate"])
            accs.append(summary["accuracy"])
            excs.append(summary["entities"] - summary["resolved"])

        mean = lambda xs: sum(xs) / len(xs)
        print(f"  {scale:>6.1f}{mean(densities):>13.0%}{mean(rates):>12.1%}"
              f"{mean(accs):>12.1%}{mean(excs):>13.0f}{min(accs):>12.1%}")

    print("-" * 74)
    print()
    print("  Resolution rate falls as density rises -- expected and correct:")
    print("  more defects means more records a human must see.")
    print()
    print("  Accuracy is invariant to density alone, because each record is")
    print("  classified independently. Density is not adversarial. Run with")
    print("  --compound to allow several defects on one record, which is the")
    print("  case that does degrade the result.")
    print()


# --------------------------------------------------------------------------
# Detection grading -- defect classes the engine has no label for
# --------------------------------------------------------------------------

@dataclass
class DetectionOutcome:
    entity_id: str
    planted: str            # the unseen class that was planted
    emitted: str | None     # what the engine said, or None if it said nothing
    state: str              # detected | silent_clean | silent_absent


def load_unseen_truth(datadir: Path) -> dict[str, str]:
    """
    Truth rows marked `outside_taxonomy`, produced by adversarial_data.py.

    Returns {entity_id: planted_class}. A ground truth file without the column
    yields an empty mapping, so ordinary datasets pass through unaffected.
    """
    path = datadir / "ground_truth.csv"
    with path.open(encoding="utf-8-sig") as f:
        return {r["entity_id"]: r["expected_classification"]
                for r in csv.DictReader(f)
                if (r.get("outside_taxonomy") or "no").strip().lower() == "yes"}


def grade_detection(datadir: Path) -> tuple[list[DetectionOutcome], dict]:
    """
    Score the engine on defects it was never designed to name.

    Classification accuracy is not the metric here and cannot be: the engine
    has no `currency_mismatch` class, so accuracy on these records is
    structurally zero and measures nothing. The question is whether the engine
    refused to call a broken record clean.

    Iterating over TRUTH rather than over resolutions is deliberate and is the
    part worth understanding. `grade` above walks the engine's resolutions and
    looks each one up in the answer key, so an entity the engine never
    mentioned is never graded -- it simply does not appear in the loop. For
    known defects that is harmless, because every planted defect belongs to an
    entity the engine reports on anyway. For unseen defects it is not: the
    most dangerous failure is a broken record the engine never examined at all,
    and a resolution-driven loop is structurally blind to exactly that case.
    """
    orders, txns, settlements, bank = load(datadir)
    resolutions = Engine(orders, txns, settlements, bank).run()
    emitted = {r.entity_id: r.classification for r in resolutions}

    planted = load_unseen_truth(datadir)
    outcomes: list[DetectionOutcome] = []

    for eid, cls in sorted(planted.items()):
        # The engine does not always report against the entity id in the answer
        # key. A statement-continuity break is emitted against a derived id --
        # `GAP_BEFORE_<row>` -- because the gap describes the space between two
        # rows rather than either row itself. That row may ALSO carry its own
        # `clean` resolution, so the question is not what the first lookup
        # returns; it is whether the engine said anything non-clean about the
        # record at all. Aliases are listed explicitly: guessing at name shapes
        # would let a genuine miss be excused by a coincidental key.
        signals = [emitted[k] for k in (eid, f"GAP_BEFORE_{eid}")
                   if k in emitted]
        flagged = [s for s in signals if s != "clean"]

        if flagged:
            state, got = "detected", flagged[0]
        elif signals:
            state, got = "silent_clean", "clean"
        else:
            state, got = "silent_absent", None
        outcomes.append(DetectionOutcome(eid, cls, got, state))

    by_class: dict[str, Counter] = defaultdict(Counter)
    labels: dict[str, Counter] = defaultdict(Counter)
    for o in outcomes:
        by_class[o.planted][o.state] += 1
        if o.state == "detected":
            labels[o.planted][o.emitted] += 1

    total = len(outcomes)
    detected = sum(1 for o in outcomes if o.state == "detected")
    silent = total - detected
    lo, hi = wilson_interval(detected, total) if total else (0.0, 0.0)

    summary = {
        "total": total,
        "detected": detected,
        "silent": silent,
        "detection_rate": detected / total if total else 0.0,
        "detection_ci": (lo, hi),
        "by_class": {k: dict(v) for k, v in by_class.items()},
        "labels": {k: dict(v) for k, v in labels.items()},
    }
    return outcomes, summary


def print_detection_report(outcomes: list[DetectionOutcome],
                           summary: dict) -> None:
    if not summary["total"]:
        print("No records marked `outside_taxonomy` in this dataset.")
        print("Generate one with:  python src/adversarial_data.py")
        return

    print("=" * 74)
    print("DETECTION ON UNSEEN DEFECT CLASSES")
    print("=" * 74)
    print("The engine has no label for any class below. Classification")
    print("accuracy is therefore structurally zero and is not reported.")
    print("The question asked is only: did it refuse to call the record clean?")
    print()

    lo, hi = summary["detection_ci"]
    print(f"  planted          {summary['total']}")
    print(f"  detected         {summary['detected']}")
    print(f"  silent pass      {summary['silent']}")
    print(f"  detection rate   {summary['detection_rate']:6.1%}  "
          f"[{lo:.1%}, {hi:.1%}] 95% Wilson")
    print()

    print(f"  {'planted class':<26}{'n':>4}{'det':>6}{'clean':>7}{'absent':>8}")
    print("  " + "-" * 51)
    for cls in sorted(summary["by_class"]):
        c = summary["by_class"][cls]
        n = sum(c.values())
        print(f"  {cls:<26}{n:>4}{c.get('detected', 0):>6}"
              f"{c.get('silent_clean', 0):>7}{c.get('silent_absent', 0):>8}")
    print()

    if summary["labels"]:
        print("  Labels emitted where a defect WAS detected. The engine cannot")
        print("  name these classes, so every label here is by definition")
        print("  wrong -- what matters is whether it misdirects an analyst.")
        print()
        for cls in sorted(summary["labels"]):
            got = ", ".join(f"{k} x{v}" for k, v in
                            sorted(summary["labels"][cls].items()))
            print(f"    {cls:<26} -> {got}")
        print()

    silent = [o for o in outcomes if o.state != "detected"]
    if silent:
        print("  SILENT PASSES -- broken records the engine did not flag:")
        print()
        for o in silent[:20]:
            why = ("classified clean" if o.state == "silent_clean"
                   else "never examined; no resolution emitted")
            print(f"    {o.entity_id:<18} {o.planted:<26} {why}")
        if len(silent) > 20:
            print(f"    ... and {len(silent) - 20} more")
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--detection", action="store_true",
                    help="grade detection of defect classes outside the "
                         "engine's taxonomy (see adversarial_data.py)")
    ap.add_argument("--seeds", type=int, default=0,
                    help="run variance analysis across N seeds")
    ap.add_argument("--orders", type=int, default=120)
    ap.add_argument("--throughput", action="store_true")
    ap.add_argument("--stress", action="store_true",
                    help="measure accuracy as defect density rises")
    ap.add_argument("--compound", action="store_true",
                    help="allow several defects per record during stress")
    ap.add_argument("--workdir", default=".eval")
    args = ap.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(exist_ok=True)

    if args.detection:
        outcomes, summary = grade_detection(Path(args.data))
        print_detection_report(outcomes, summary)
    elif args.stress:
        run_stress([1.0, 2.0, 3.0, 4.0, 6.0], args.orders,
                   args.seeds or 3, workdir, compound=args.compound)
    elif args.seeds:
        run_variance(args.seeds, args.orders, workdir)
    elif args.throughput:
        run_throughput([120, 500, 1000, 5000], workdir)
    else:
        metrics, summary = grade(Path(args.data))
        print_report(metrics, summary)


if __name__ == "__main__":
    main()
