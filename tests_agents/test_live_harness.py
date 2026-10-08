"""
Tests for the live-evaluation harness (scripts/live_engine_compare.py).

No network and no model: a scripted provider plays the vendor, including one
that rate-limits. The harness is measurement code, so what is tested is that it
never loses a call, never spends past its cap, waits as long as it was told to,
and resumes from saved progress without repeating or duplicating work.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import live_engine_compare as lec  # noqa: E402

from agent import CLASSIFICATIONS  # noqa: E402
from llm import LLMResponse, Provider  # noqa: E402

ANSWER = LLMResponse(
    text=json.dumps({"classification": CLASSIFICATIONS[0], "resolved": False,
                     "reasoning": "r", "analyst_note": "n"}),
    provider="scripted", usage={"input": 100, "output": 10})


def limited(retry_after=None, text="Error code: 429 rate limit", daily=False):
    return LLMResponse(provider="scripted", error=text,
                       retry_after=retry_after, quota_exhausted=daily)


class Scripted(Provider):
    """Plays back responses in order; once exhausted it keeps answering."""
    name = "scripted"
    available = True
    model = "scripted-model"

    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def complete(self, system, messages, tools=None, max_tokens=1024, model=None):
        self.calls += 1
        return self.script.pop(0) if self.script else ANSWER

    @staticmethod
    def assistant_turn(resp):
        return {"role": "assistant", "content": resp.text}

    @staticmethod
    def tool_results_turn(results):
        return {"role": "user", "content": results}


@pytest.fixture
def ledger(tmp_path):
    return lec.Ledger(tmp_path / "ledger.json", cap=50)


def measured(script, ledger, naps):
    return lec.MeasuredProvider(Scripted(script), ledger, sleep=naps.append)


class TestRetryHints:

    def test_groq_style_hint(self):
        assert lec.parse_retry_hint("Please try again in 7.5s.") == 7.5
        assert lec.parse_retry_hint("try again in 1m2.5s") == 62.5

    def test_gemini_style_hint(self):
        assert lec.parse_retry_hint("{'retryDelay': '30s'}") == 30.0

    def test_no_hint(self):
        assert lec.parse_retry_hint("internal error") is None


class TestRateLimits:

    def test_waits_the_vendor_hint_then_succeeds(self, ledger):
        naps = []
        p = measured([limited(retry_after=12.0)], ledger, naps)
        resp = p.complete("s", [])
        assert resp.ok and naps == [13.0]
        assert (p.retries, ledger.calls, ledger.retries) == (1, 1, 1)
        assert p.calls[-1]["retries"] == 1 and p.calls[-1]["waited_seconds"] == 13.0

    def test_hint_in_the_message_is_used_when_no_header(self, ledger):
        naps = []
        p = measured([limited(text="429 try again in 4s")], ledger, naps)
        p.complete("s", [])
        assert naps == [5.0]

    def test_backs_off_exponentially_without_a_hint(self, ledger):
        naps = []
        p = measured([limited(), limited(), limited()], ledger, naps)
        p.complete("s", [])
        assert naps == [3.0, 5.0, 9.0]

    def test_a_retry_is_not_counted_as_a_call(self, ledger):
        p = measured([limited(), limited()], ledger, [])
        p.complete("s", [])
        assert ledger.calls == 1 and ledger.retries == 2

    def test_daily_limit_stops_instead_of_waiting(self, ledger):
        naps = []
        p = measured([limited(daily=True, text="429 tokens per day")], ledger, naps)
        with pytest.raises(lec.DailyLimit):
            p.complete("s", [])
        assert naps == []

    def test_a_very_long_wait_is_treated_as_a_daily_limit(self, ledger):
        p = measured([limited(retry_after=lec.MAX_WAIT_S + 1)], ledger, [])
        with pytest.raises(lec.DailyLimit):
            p.complete("s", [])

    def test_gives_up_loudly_after_too_many_retries(self, ledger):
        p = measured([limited()] * 20, ledger, [])
        with pytest.raises(lec.RetriesExhausted):
            p.complete("s", [])

    def test_other_errors_are_returned_not_retried(self, ledger):
        bad = LLMResponse(provider="scripted", error="400 bad request")
        p = measured([bad], ledger, [])
        resp = p.complete("s", [])
        assert not resp.ok and p.retries == 0 and p.inner.calls == 1


class TestCap:

    def test_refuses_the_call_past_the_cap(self, tmp_path):
        small = lec.Ledger(tmp_path / "l.json", cap=2)
        p = lec.MeasuredProvider(Scripted([]), small, sleep=lambda s: None)
        p.complete("s", [])
        p.complete("s", [])
        with pytest.raises(lec.CapReached):
            p.complete("s", [])
        assert p.inner.calls == 2

    def test_the_count_survives_a_restart(self, tmp_path):
        a = lec.Ledger(tmp_path / "l.json", cap=5)
        a.spend()
        a.retry()
        b = lec.Ledger(tmp_path / "l.json", cap=5)
        assert (b.calls, b.retries) == (1, 1)


class TestRunAndResume:

    @pytest.fixture
    def args(self):
        return Namespace(provider="groq", model="", data=str(ROOT / "data"),
                         seed=42, engines="loop", reps=1, rep_offset=0, limit=3,
                         only="", cap=100, label="t", restart=False)

    @pytest.fixture(autouse=True)
    def sandbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lec, "RESULTS", tmp_path / "results")
        monkeypatch.setattr(lec, "LEDGER", tmp_path / "ledger.json")

    def saved(self):
        (path,) = list(lec.RESULTS.glob("*.json"))
        return json.loads(path.read_text(encoding="utf-8"))

    def test_records_provider_model_and_retries(self, args):
        script = [limited(retry_after=1.0)]
        assert lec.run(args, lambda: Scripted(script), sleep=lambda s: None) == 0
        doc = self.saved()
        assert doc["meta"]["provider"] == "groq"
        assert doc["meta"]["model"] == "scripted-model"
        assert doc["meta"]["failover"] is False
        assert len(doc["records"]) == 3
        assert doc["meta"]["sessions"][0]["retries"] == 1
        assert sum(r["retries"] for r in doc["records"]) == 1

    def test_a_daily_limit_saves_progress_and_the_next_run_resumes(self, args):
        # First call of the second exception hits the daily limit.
        script = [ANSWER, limited(daily=True, text="429 per day")]
        assert lec.run(args, lambda: Scripted(script), sleep=lambda s: None) == 1
        first = self.saved()
        assert len(first["records"]) == 1
        assert first["meta"]["status"].startswith("incomplete")
        assert first["meta"]["sessions"][0]["discarded_investigation"]

        assert lec.run(args, lambda: Scripted([]), sleep=lambda s: None) == 0
        done = self.saved()
        ids = [r["entity_id"] for r in done["records"]]
        assert len(ids) == 3 and len(set(ids)) == 3
        assert ids[0] == first["records"][0]["entity_id"]
        assert len(done["meta"]["sessions"]) == 2
        assert done["meta"]["sessions"][1]["resumed_records"] == 1

    def test_refuses_to_resume_into_a_file_with_different_settings(self, args):
        lec.run(args, lambda: Scripted([]), sleep=lambda s: None)
        args.limit = 2
        assert lec.run(args, lambda: Scripted([]), sleep=lambda s: None) == 2

    def test_unavailable_provider_is_reported(self, args):
        class Down(Scripted):
            available = False
            reason = "GROQ_API_KEY not set"
        assert lec.run(args, lambda: Down([]), sleep=lambda s: None) == 2
