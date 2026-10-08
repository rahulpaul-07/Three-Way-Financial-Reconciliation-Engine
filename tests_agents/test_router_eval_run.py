"""
Tests for scripts/router_eval.py: the call cap, the 429 handling, resume,
the scoring, and one scripted end-to-end run. No network and no real model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("google.adk")
pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import router_eval as ev  # noqa: E402
from adk_helpers import ScriptedLlm, route, verdict  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from live_engine_compare import CapReached, DailyLimit, Ledger, RetriesExhausted  # noqa: E402
from router_eval_gold import load_eval  # noqa: E402

ITEMS = {i["id"]: i for i in load_eval()}


def quota_error(text: str) -> genai_errors.APIError:
    return genai_errors.APIError(429, {"error": {"message": text}})


def measured(script, tmp_path, cap=50):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    ledger = Ledger(tmp_path / "ledger.json", cap)
    model = ev.MeasuredModel(model="scripted", inner=ScriptedLlm(script=list(script)),
                             ledger=ledger, sleep=fake_sleep, waits=[], retries=0)
    return model, ledger, sleeps


def drain(model) -> None:
    async def go():
        async for _ in model.generate_content_async(LlmRequest()):
            pass
    asyncio.run(go())


class TestMeasuredModel:

    def test_a_429_is_retried_after_the_vendors_hint_and_not_counted_as_a_call(self, tmp_path):
        model, ledger, sleeps = measured(
            [quota_error("slow down retryDelay': '7s'"), "ok"], tmp_path)
        drain(model)
        assert sleeps == [8.0]          # the hint plus a one-second cushion
        assert (ledger.calls, ledger.retries, model.retries) == (1, 1, 1)
        assert model.waits == [8.0]

    def test_the_cap_stops_the_call_before_the_model_is_reached(self, tmp_path):
        model, ledger, _ = measured(["a", "b"], tmp_path, cap=1)
        drain(model)
        with pytest.raises(CapReached):
            drain(model)
        assert len(model.inner.calls) == 1

    def test_the_ledger_persists_across_runs(self, tmp_path):
        model, ledger, _ = measured(["a"], tmp_path)
        drain(model)
        assert Ledger(tmp_path / "ledger.json", 50).calls == 1

    def test_a_daily_quota_stops_the_run_instead_of_waiting(self, tmp_path):
        model, _, sleeps = measured(
            [quota_error("quota_metric GenerateRequestsPerDayPerProject")], tmp_path)
        with pytest.raises(DailyLimit):
            drain(model)
        assert sleeps == []

    def test_a_very_long_wait_stops_the_run(self, tmp_path):
        model, _, _ = measured([quota_error("retryDelay': '5000s'")], tmp_path)
        with pytest.raises(DailyLimit):
            drain(model)

    def test_too_many_retries_on_one_call_stops_the_run(self, tmp_path):
        model, _, _ = measured([quota_error("retryDelay': '1s'")] * 20, tmp_path)
        with pytest.raises(RetriesExhausted):
            drain(model)

    def test_other_api_errors_are_not_retried(self, tmp_path):
        model, ledger, sleeps = measured(
            [genai_errors.APIError(503, {"error": {"message": "down"}})], tmp_path)
        with pytest.raises(genai_errors.APIError):
            drain(model)
        assert sleeps == [] and ledger.retries == 0


class TestScoring:

    def rec(self, rid, route, status="answered", text="", classification=None, calls=3):
        return {"id": rid, "route": route, "status": status, "answer_text": text,
                "classification": classification, "handoff_reason": None
                if status == "answered" else "unexplained",
                "model_calls": calls, "seconds_excluding_waits": 1.0, "retries": 0,
                "input_tokens": 10, "output_tokens": 5}

    def test_end_to_end_agreement_is_split_by_hint(self):
        records = [
            # R01 hinted, agrees; R02 hinted, wrong; R06 unhinted, agrees;
            # R07 unhinted, handed off; R08 misrouted, so excluded.
            self.rec("R01", "investigator", classification="fee_mismatch"),
            self.rec("R02", "investigator", classification="fee_mismatch"),
            self.rec("R06", "investigator", classification="orphan_bank_credit"),
            self.rec("R07", "investigator", status="handoff"),
            self.rec("R08", "human"),
        ]
        s = ev.score(records, load_eval())
        assert (s["hinted"]["agreed"], s["hinted"]["routed"]) == (1, 2)
        assert (s["unhinted"]["agreed"], s["unhinted"]["routed"]) == (1, 2)
        assert s["unhinted"]["handed_off"] == 1

    def test_a_human_request_that_was_answered_is_a_missed_handoff(self):
        records = [self.rec("R21", "investigator", classification="x"),
                   self.rec("R22", "human", status="handoff")]
        s = ev.score(records, load_eval())
        assert s["missed_handoffs"] == ["R21"]

    def test_a_specialist_request_that_ended_in_handoff_is_an_unneeded_handoff(self):
        records = [self.rec("R11", "data", status="handoff")]
        s = ev.score(records, load_eval())
        assert s["unneeded_handoffs"] == [("R11", "unexplained")]

    def test_routing_accuracy_counts_a_missing_route_as_wrong(self):
        records = [self.rec("R25", None, status="handoff"), self.rec("R26", "human",
                                                                       status="handoff")]
        s = ev.score(records, load_eval())
        assert s["routing_right"] == 1
        assert s["confusion"][("human", "none")] == 1

    def test_the_four_boundary_cases_are_reported_separately(self):
        records = [self.rec(i, "human", status="handoff") for i in ("R19", "R20", "R24", "R30")]
        assert [b[0] for b in ev.score(records, load_eval())["boundary"]] == [
            "R19", "R20", "R24", "R30"]

    def test_data_correctness_needs_every_expected_figure_and_string(self):
        r11 = ITEMS["R11"]
        assert ev.data_correct(r11, "card 37, netbanking 7, upi 65, wallet 11")
        assert not ev.data_correct(r11, "card 37, netbanking 7, upi 65")
        assert not ev.data_correct(r11, "37, 7, 65, 11")           # strings missing
        assert ev.data_correct(ITEMS["R16"], "6 orders worth INR 14,348.00 in total")

    def test_data_results_are_split_into_correct_wrong_and_handed_off(self):
        records = [self.rec("R15", "data", text="There are 3."),
                   self.rec("R16", "data", text="There are 9."),
                   self.rec("R17", "data", status="handoff")]
        d = ev.score(records, load_eval())["data"]
        assert (d["correct"], d["wrong"], d["handed_off"]) == (["R15"], ["R16"], ["R17"])


def args(tmp_path, **kw):
    base = dict(model="scripted", data=str(ROOT / "data"), reps=1, rep_offset=0,
                only="R02,R11,R21", budget=7, cap=50, label="t", restart=False)
    return argparse.Namespace(**{**base, **kw})


SCRIPT = [
    route("investigator"), ("get_record_facts", {"entity_id": "ORD4026"}),
    verdict("missing_payment"),
    route("data"),
    ("run_sql", {"query": "SELECT payment_method, COUNT(*) AS n FROM orders "
                          "GROUP BY payment_method ORDER BY payment_method"}),
    "card 37, netbanking 7, upi 65, wallet 11.",
    route("human"),
]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(ev, "LEDGER", tmp_path / "ledger.json")
    return tmp_path


def factory(script):
    return lambda: ScriptedLlm(script=list(script))


class TestRun:

    def test_a_scripted_run_records_every_request_and_counts_every_call(self, paths):
        assert ev.run(args(paths), factory(SCRIPT)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert [(r["id"], r["route"], r["status"]) for r in doc["records"]] == [
            ("R02", "investigator", "answered"), ("R11", "data", "answered"),
            ("R21", "human", "handoff")]
        assert sum(r["model_calls"] for r in doc["records"]) == 7
        assert json.loads((paths / "ledger.json").read_text())["calls"] == 7
        assert doc["records"][0]["classification"] == "missing_payment"

    def test_no_key_value_reaches_the_result_file(self, paths, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-value-for-test")
        ev.run(args(paths), factory(SCRIPT))
        text = (paths / "results" / "scripted_t.json").read_text()
        assert "fake-key-value-for-test" not in text

    def test_resume_skips_finished_requests_and_makes_no_new_calls(self, paths):
        ev.run(args(paths), factory(SCRIPT))
        assert ev.run(args(paths), factory([])) == 0      # an empty script fails if called
        assert json.loads((paths / "ledger.json").read_text())["calls"] == 7

    def test_the_cap_stops_the_run_and_saves_progress_and_resume_finishes_it(self, paths):
        assert ev.run(args(paths, cap=4), factory(SCRIPT)) == 1
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert [r["id"] for r in doc["records"]] == ["R02"]
        assert doc["meta"]["status"].startswith("incomplete")
        assert json.loads((paths / "ledger.json").read_text())["calls"] == 4

        assert ev.run(args(paths, cap=50), factory(SCRIPT[3:])) == 0
        done = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert [r["id"] for r in done["records"]] == ["R02", "R11", "R21"]

    def test_a_changed_prompt_refuses_to_resume_into_old_results(self, paths, monkeypatch):
        ev.run(args(paths), factory(SCRIPT))
        monkeypatch.setattr(ev, "prompt_hash", lambda: "changed")
        assert ev.run(args(paths), factory([])) == 2

    def test_an_unknown_request_id_is_refused_before_any_call(self, paths):
        assert ev.run(args(paths, only="R99"), factory([])) == 2

    def test_a_missing_key_means_no_call_is_made(self, paths, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert ev.run(args(paths)) == 2
        assert not (paths / "ledger.json").exists()


class TestModelListing:

    def test_only_models_that_generate_text_are_listed_without_the_prefix(self):
        class M:
            def __init__(self, name, actions):
                self.name, self.supported_actions = name, actions

        class Models:
            def list(self):
                return [M("models/b-model", ["generateContent"]),
                        M("models/embed", ["embedContent"]),
                        M("models/a-model", ["generateContent", "countTokens"]),
                        M("models/none", None)]

        class Client:
            models = Models()

        assert ev.list_models(Client()) == ["a-model", "b-model"]
