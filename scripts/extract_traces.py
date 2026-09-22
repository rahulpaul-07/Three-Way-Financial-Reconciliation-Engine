"""
Extract the agent's recorded investigation of the reference batch from the
published report into JSON, for the dashboard's trace viewer.

The traces came from a live model run (see README, "The agent") and cannot be
regenerated without an API key and some cost, so they are preserved from the
report that recorded them rather than re-run on every site build.

    python scripts/extract_traces.py web/public/report.html web/public/data/agent_traces.json
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path


def text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def extract(page: str) -> dict:
    head = page[page.find("Agent investigation"):page.find("Investigation traces")]
    stats = [text(x) for x in re.findall(
        r'<div class="[^"]*"\s*>([^<]{1,40})</div>', head)]

    traces = []
    for cls, body in re.findall(r'<details class="([^"]*)">(.*?)</details>',
                                page, flags=re.S):
        m = re.search(r'<span class="id">(.*?)</span><span class="tag">(.*?)'
                      r'</span>(?:</span>)?<span class="verdict">(.*?)</span>', body)
        if not m:
            continue
        steps = [{"n": int(n), "call": text(call), "result": text(out)}
                 for n, call, out in re.findall(
                     r'<span class="n">(\d+)</span><span class="tool">(.*?)</span>'
                     r'<span class="out">(.*?)</span>', body)]
        concl = re.search(r'<span class="lab">Conclusion</span>(.*?)</div>', body, re.S)
        note = re.search(r'<div class="note"><strong>.*?</strong>(.*?)</div>', body, re.S)
        traces.append({
            "entity_id": text(m.group(1)),
            # The tag may carry a nested "disagreed" badge; the label is the
            # text before it.
            "label": text(m.group(2).split("<", 1)[0]),
            "verdict": text(m.group(3)),
            "flag": cls.strip(),
            "steps": steps,
            "conclusion": text(concl.group(1)) if concl else "",
            "analyst_note": text(note.group(1)) if note else "",
        })
    return {"source": "live model run over datasets/01-reference, recorded "
                      "in the published report", "stats": stats,
            "traces": traces}


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    data = extract(src.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(data['traces'])} traces -> {out}")
