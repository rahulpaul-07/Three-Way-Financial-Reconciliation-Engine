"""
Build the static data the dashboard ships with.

The dashboard works in two modes. With the live API reachable it reconciles on
request; without it (GitHub Pages, a sleeping free-tier instance) it falls back
to these snapshots. Every figure in them is produced by running the engine and
the evaluator here, at build time -- nothing is typed in by hand except the
pre-fix detection result, which is a historical record and says so.

    python scripts/build_site_data.py --out web/public/data            # full
    python scripts/build_site_data.py --out web/public/data --quick    # CI
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from analysis import DATASET_INFO, analyse, taxonomy_payload  # noqa: E402
from evaluate import run_stress, run_throughput, run_variance  # noqa: E402

# Measured on commit be38a48, before the four blind spots were closed. Kept as
# the "before" half of the before/after comparison; it cannot be regenerated
# from the current engine by definition.
DETECTION_BEFORE = {
    "commit": "be38a48",
    "detected": 15, "total": 26,
    "silent_classes": ["currency_mismatch", "duplicate_bank_row",
                       "dangling_settlement_ref", "unreversed_refund_fee"],
}


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"  {path.relative_to(ROOT) if ROOT in path.parents else path}"
          f"  {path.stat().st_size // 1024} KB")


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True
                              ).stdout.strip()
    except Exception:                                     # noqa: BLE001
        return "unknown"


def test_count() -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q",
                        "--collect-only"], cwd=ROOT, capture_output=True,
                       text=True)
    for line in r.stdout.splitlines()[::-1]:
        if "tests collected" in line or "test collected" in line:
            return int(line.split()[0])
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data"))
    ap.add_argument("--quick", action="store_true",
                    help="fewer seeds and sizes; for CI")
    args = ap.parse_args()
    out = Path(args.out).resolve()

    print("datasets")
    index = []
    for info in DATASET_INFO:
        d = ROOT / "datasets" / info["name"]
        if not d.is_dir():
            continue
        payload = analyse(d, source=info["name"])
        dump(out / "datasets" / f"{info['name']}.json", payload)
        s = payload["summary"]
        index.append(info | {
            "entities": s["entities"], "resolution_rate": s["resolution_rate"],
            "accuracy": (payload["grading"] or {}).get("accuracy"),
            "exceptions": s["unresolved"]})

    print("benchmarks")
    work = Path(tempfile.mkdtemp(prefix="site-"))
    try:
        seeds = 4 if args.quick else 12
        variance = quiet(run_variance, seeds, 150, work)
        sizes = [120, 500] if args.quick else [120, 500, 1000, 2500, 5000]
        throughput = quiet(run_throughput, sizes, work)
        scales = [1.0, 3.0] if args.quick else [1.0, 2.0, 3.0, 4.0, 6.0]
        compound = quiet(run_stress, scales, 120, 3, work, compound=True)
        density = quiet(run_stress, scales, 120, 3, work, compound=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    unseen = json.loads((out / "datasets" / "08-unseen.json").read_text())
    det = unseen["detection"]
    benchmarks = {
        "variance": variance, "throughput": throughput,
        "stress_compound": compound, "stress_density": density,
        "detection": {
            "before": DETECTION_BEFORE,
            "after": {"detected": det["detected"], "total": det["total"],
                      "named": det["named"],
                      "silent_classes": det["blind_spot_classes"],
                      "by_class": det["by_class"], "labels": det["labels"]},
        },
    }
    dump(out / "benchmarks.json", benchmarks)
    dump(out / "taxonomy.json", taxonomy_payload())

    # The agent's recorded run lives in the static report shipped with the site.
    traces_src = ROOT / "web" / "public" / "report.html"
    traces_out = out / "agent_traces.json"
    if traces_src.exists() and "Investigation traces" in traces_src.read_text(
            encoding="utf-8"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "extract_traces.py"),
                        str(traces_src), str(traces_out)], check=True)

    ref = next(i for i in index if i["name"] == "01-reference")
    dump(out / "meta.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git_sha(), "tests": test_count(), "datasets": index,
        "headline": {
            "resolution_rate": ref["resolution_rate"],
            "accuracy": ref["accuracy"], "exceptions": ref["exceptions"],
            "entities": ref["entities"],
            "throughput": max(r["entities_per_second"] for r in throughput),
            "variance_mean": sum(v["resolution_rate"] for v in variance) / len(variance),
            "detection": f"{det['detected']}/{det['total']}",
        },
    })


if __name__ == "__main__":
    main()
