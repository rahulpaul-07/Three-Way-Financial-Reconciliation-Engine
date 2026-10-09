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

import anthropic
import httpx
import pytest

pytest.importorskip("google.adk")
pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import router_eval as ev  # noqa: E402
from adk_helpers import HANG, ScriptedLlm, route, verdict  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from live_engine_compare import CapReached, DailyLimit, Ledger, RetriesExhausted  # noqa: E402
from router_eval_gold import load_eval  # noqa: E402

ITEMS = {i["id"]: i for i in load_eval()}


def quota_error(text: str) -> genai_errors.APIError:
    return genai_errors.APIError(429, {"error": {"message": text}})


def outage(code=503, headers=None) -> genai_errors.APIError:
    response = httpx.Response(code, headers=headers or {})
    return genai_errors.APIError(
        code, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}, response)


def claude_error(status: int, headers: dict | None = None) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return anthropic.APIStatusError(f"claude said {status}", response=response, body=None)


def measured(script, tmp_path, cap=50):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    ledger = Ledger(tmp_path / "ledger.json", cap)
    model = ev.MeasuredModel(model="scripted", inner=ScriptedLlm(script=list(script)),
                             ledger=ledger, sleep=fake_sleep, jitter=lambda: 0.0,
                             call_timeout=0.2, waits=[], retries=0)
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

    @pytest.mark.parametrize("code", [500, 503, 504])
    def test_a_provider_outage_that_clears_is_retried_with_backoff(self, tmp_path, code):
        model, ledger, sleeps = measured([outage(code), outage(code), "ok"], tmp_path)
        drain(model)
        assert sleeps == [2.0, 4.0]                 # exponential, jitter pinned to zero
        assert (ledger.calls, ledger.retries, model.retries) == (1, 2, 2)

    def test_a_provider_outage_that_never_clears_stops_after_four_attempts(self, tmp_path):
        model, ledger, sleeps = measured([outage()] * 10, tmp_path)
        with pytest.raises(genai_errors.APIError) as caught:
            drain(model)
        assert caught.value.code == 503
        assert len(model.inner.calls) == 4
        assert sleeps == [2.0, 4.0, 8.0]
        assert (ledger.calls, ledger.retries) == (1, 3)

    @pytest.mark.parametrize("exc", [
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
        anthropic.APITimeoutError(httpx.Request("POST", "https://x")),
        httpx.ConnectError("refused"),
        httpx.RemoteProtocolError("closed"),
    ], ids=["claude-connection", "claude-timeout", "gemini-connect", "gemini-protocol"])
    def test_a_connection_error_is_retried_like_a_503(self, tmp_path, exc):
        model, ledger, sleeps = measured([exc, exc, "ok"], tmp_path)
        drain(model)
        assert sleeps == [2.0, 4.0]
        assert (ledger.calls, ledger.retries, model.retries) == (1, 2, 2)

    def test_a_connection_error_that_never_clears_stops_after_four_attempts(self, tmp_path):
        exc = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        model, ledger, sleeps = measured([exc] * 10, tmp_path)
        with pytest.raises(anthropic.APIConnectionError):
            drain(model)
        assert len(model.inner.calls) == 4
        assert sleeps == [2.0, 4.0, 8.0]
        assert (ledger.calls, ledger.retries) == (1, 3)

    def test_retry_after_is_honoured_for_an_outage(self, tmp_path):
        model, _, sleeps = measured([outage(headers={"Retry-After": "5"}), "ok"], tmp_path)
        drain(model)
        assert sleeps == [5.0]

    def test_an_absurd_retry_after_is_clamped(self, tmp_path):
        model, _, sleeps = measured([outage(headers={"Retry-After": "5000"}), "ok"], tmp_path)
        drain(model)
        assert sleeps == [60.0]

    def test_jitter_widens_the_backoff(self, tmp_path):
        model, _, sleeps = measured([outage(), "ok"], tmp_path)
        model.jitter = lambda: 0.5
        drain(model)
        assert sleeps == [3.0]

    def test_a_claude_429_is_retried_after_its_retry_after_header(self, tmp_path):
        model, ledger, sleeps = measured(
            [claude_error(429, {"retry-after": "7"}), "ok"], tmp_path)
        drain(model)
        assert sleeps == [8.0]
        assert (ledger.calls, ledger.retries) == (1, 1)

    def test_a_claude_429_without_a_hint_backs_off(self, tmp_path):
        model, _, sleeps = measured([claude_error(429), "ok"], tmp_path)
        drain(model)
        assert sleeps == [3.0]                  # 2s base plus the one-second cushion

    def test_claude_529_overloaded_is_retried_then_succeeds(self, tmp_path):
        model, ledger, sleeps = measured([claude_error(529), claude_error(529), "ok"], tmp_path)
        drain(model)
        assert sleeps == [2.0, 4.0]
        assert (ledger.calls, ledger.retries) == (1, 2)

    def test_claude_529_that_never_clears_stops_after_four_attempts(self, tmp_path):
        model, _, _ = measured([claude_error(529)] * 10, tmp_path)
        with pytest.raises(anthropic.APIStatusError) as caught:
            drain(model)
        assert caught.value.status_code == 529
        assert len(model.inner.calls) == 4

    @pytest.mark.parametrize("status", [500, 503, 504])
    def test_claude_server_errors_are_retried(self, tmp_path, status):
        model, _, sleeps = measured([claude_error(status), "ok"], tmp_path)
        drain(model)
        assert sleeps == [2.0]

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_claude_client_and_auth_errors_fail_fast(self, tmp_path, status):
        model, ledger, sleeps = measured([claude_error(status)], tmp_path)
        with pytest.raises(anthropic.APIStatusError):
            drain(model)
        assert sleeps == [] and ledger.retries == 0 and len(model.inner.calls) == 1

    def test_a_call_that_never_returns_is_timed_out_and_retried(self, tmp_path):
        model, ledger, sleeps = measured([HANG, "ok"], tmp_path)
        drain(model)
        assert sleeps == [2.0]
        assert (ledger.calls, ledger.retries) == (1, 1)

    def test_a_call_that_always_hangs_ends_as_a_timeout_after_four_attempts(self, tmp_path):
        model, _, sleeps = measured([HANG] * 4, tmp_path)
        with pytest.raises(TimeoutError):
            drain(model)
        assert len(model.inner.calls) == 4
        assert sleeps == [2.0, 4.0, 8.0]

    def test_each_failed_attempt_keeps_its_error_text(self, tmp_path):
        model, _, _ = measured([claude_error(529), claude_error(503), "ok"], tmp_path)
        drain(model)
        assert len(model.errors) == 2
        assert "529" in model.errors[0] and "503" in model.errors[1]

    def test_stored_attempt_errors_are_truncated_and_scrubbed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-for-test")
        long_text = "sk-fake-key-for-test " + "y" * 2000
        model, _, _ = measured(
            [genai_errors.APIError(503, {"error": {"message": long_text}}), "ok"], tmp_path)
        drain(model)
        assert len(model.errors[0]) <= 300
        assert "sk-fake-key-for-test" not in model.errors[0]

    def test_other_api_errors_are_not_retried(self, tmp_path):
        model, ledger, sleeps = measured(
            [genai_errors.APIError(400, {"error": {"message": "bad request"}})], tmp_path)
        with pytest.raises(genai_errors.APIError):
            drain(model)
        assert sleeps == [] and ledger.retries == 0


class TestScoring:

    def rec(self, rid, route, status="answered", text="", classification=None, calls=3,
            reason="unexplained"):
        return {"id": rid, "route": route, "status": status, "answer_text": text,
                "classification": classification,
                "handoff_reason": None if status == "answered" else reason,
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

    def test_provider_unavailable_is_listed_and_left_out_of_every_denominator(self):
        records = [self.rec("R11", "data", status="handoff", reason="provider_unavailable"),
                   self.rec("R12", None, status="handoff", reason="provider_unavailable"),
                   self.rec("R21", "human", status="handoff")]
        s = ev.score(records, load_eval())
        assert s["unavailable"] == ["R11", "R12"]
        assert (s["n"], s["routing_right"]) == (1, 1)
        assert s["unneeded_handoffs"] == [] and s["data"]["handed_off"] == []
        assert s["model_calls"] == 9            # the calls were still made and still cost

    def test_an_unavailable_investigator_request_is_not_a_handoff_in_the_agreement(self):
        records = [self.rec("R01", "investigator", status="handoff",
                            reason="provider_unavailable")]
        s = ev.score(records, load_eval())
        assert (s["hinted"]["routed"], s["hinted"]["handed_off"]) == (0, 0)

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

    def test_a_number_written_as_a_word_is_the_same_figure(self):
        assert ev.data_correct(ITEMS["R15"], "Three credits have no UTR.")
        assert ev.data_correct(ITEMS["R16"], "Six orders, worth INR 14,348.00 in total")
        assert not ev.data_correct(ITEMS["R16"], "Seven orders, worth INR 14,348.00")

    def test_the_scorer_counts_word_answers_as_correct(self):
        records = [self.rec("R15", "data", text="Three credits."),
                   self.rec("R16", "data", text="Six orders, INR 14348.00 in total.")]
        assert ev.score(records, load_eval())["data"]["correct"] == ["R15", "R16"]

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

    def test_a_persistent_outage_is_recorded_as_provider_unavailable_and_the_run_goes_on(
            self, paths, monkeypatch):
        monkeypatch.setattr(ev, "BACKOFF_BASE_S", 0.0)
        script = [route("investigator"), ("get_record_facts", {"entity_id": "ORD4026"}),
                  verdict("missing_payment"),
                  route("data")] + [outage()] * 4 + [route("human")]
        assert ev.run(args(paths), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        by_id = {r["id"]: r for r in doc["records"]}
        assert by_id["R11"]["handoff_reason"] == "provider_unavailable"
        assert by_id["R11"]["retries"] == 3
        assert by_id["R02"]["status"] == "answered"
        assert [r["id"] for r in doc["records"]] == ["R02", "R11", "R21"]
        assert json.loads((paths / "ledger.json").read_text())["retries"] == 3

    def test_a_connection_that_never_comes_back_is_provider_unavailable_after_retries(
            self, paths, monkeypatch):
        monkeypatch.setattr(ev, "BACKOFF_BASE_S", 0.0)
        down = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        script = [down] * 4 + [route("human"), route("human")]
        assert ev.run(args(paths, only="R02,R11,R21"), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        first = doc["records"][0]
        assert first["handoff_reason"] == "provider_unavailable"
        assert first["retries"] == 3

    def test_an_auth_failure_is_a_model_error_with_its_text_in_the_record(
            self, paths, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-for-test")
        script = [route("investigator"), claude_error(401), route("human"), route("human")]
        assert ev.run(args(paths, only="R02,R11,R21"), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        record = doc["records"][0]
        assert record["handoff_reason"] == "model_error"
        assert "401" in record["handoff_detail"] and len(record["handoff_detail"]) <= 300
        assert "sk-fake-key-for-test" not in json.dumps(doc)
        assert any("401" in c["error"] for c in record["calls"])
        assert record["retries"] == 0

    def test_retried_attempt_errors_are_kept_on_the_record(self, paths, monkeypatch):
        monkeypatch.setattr(ev, "BACKOFF_BASE_S", 0.0)
        script = [route("investigator"), ("get_record_facts", {"entity_id": "ORD4026"}),
                  claude_error(529), verdict("missing_payment"), route("human")]
        ev.run(args(paths, only="R02,R21"), factory(script))
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert doc["records"][0]["retries"] == 1
        assert "529" in doc["records"][0]["attempt_errors"][0]

    def test_a_request_that_hangs_is_recorded_with_its_own_reason_and_the_run_goes_on(
            self, paths, monkeypatch):
        monkeypatch.setattr(ev, "REQUEST_TIMEOUT_S", 0.5)
        monkeypatch.setattr(ev, "CALL_TIMEOUT_S", 30)
        script = [HANG, route("human"), route("human")]
        assert ev.run(args(paths, only="R02,R11,R21"), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert [r["handoff_reason"] for r in doc["records"]] == [
            "request_timeout", "routed_to_human", "routed_to_human"]

    def test_summarise_names_the_unavailable_requests(self, paths, capsys):
        ev.run(args(paths), factory(SCRIPT))
        file = paths / "results" / "scripted_t.json"
        doc = json.loads(file.read_text())
        doc["records"][1].update(status="handoff", handoff_reason="provider_unavailable",
                                 answer_text="", route="data")
        file.write_text(json.dumps(doc))
        ns = argparse.Namespace(files=[str(file)], price_in=None, price_out=None)
        assert ev.summarise(ns) == 0
        out = capsys.readouterr().out
        assert "provider_unavailable: 1 ['R11']" in out
        assert "2 request runs scored" in out

    def test_a_crash_inside_a_request_is_recorded_as_internal_error_and_the_run_goes_on(
            self, paths, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-for-test")
        bug = TypeError("create() got an unexpected keyword argument 'temperature' "
                        "sk-fake-key-for-test " + "x" * 2000)
        script = [route("investigator"), bug, route("human"), route("human")]
        assert ev.run(args(paths, only="R02,R11,R21"), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert doc["meta"]["status"] == "complete"
        assert [r["handoff_reason"] for r in doc["records"]] == [
            "internal_error", "routed_to_human", "routed_to_human"]
        first = doc["records"][0]
        assert first["handoff_detail"].startswith("TypeError")
        assert len(first["handoff_detail"]) <= 300
        assert "sk-fake-key-for-test" not in json.dumps(doc)
        assert first["handoff_agent"] == "investigator"

    def repair_script(self, second_answer):
        script = list(SCRIPT)
        script[5:6] = ["card 37, netbanking 7, upi 65, wallet 11. Total 120.", second_answer]
        return script

    def test_a_repaired_answer_is_recorded_as_repaired(self, paths):
        script = self.repair_script("card 37, netbanking 7, upi 65, wallet 11.")
        assert ev.run(args(paths), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        by_id = {r["id"]: r for r in doc["records"]}
        assert by_id["R11"]["repaired"] is True and by_id["R11"]["status"] == "answered"
        assert by_id["R11"]["model_calls"] == 4
        assert by_id["R02"]["repaired"] is False and by_id["R21"]["repaired"] is False

    def test_a_repair_that_fails_is_recorded_as_repaired_and_handed_off(self, paths):
        script = self.repair_script("card 37, netbanking 7, upi 65, wallet 11, total 999.")
        assert ev.run(args(paths), factory(script)) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        record = {r["id"]: r for r in doc["records"]}["R11"]
        assert record["repaired"] is True
        assert record["handoff_reason"] == "ungrounded_numbers"
        assert "999" in record["handoff_detail"]

    def test_repair_calls_are_counted_against_the_ledger(self, paths):
        script = self.repair_script("card 37, netbanking 7, upi 65, wallet 11.")
        ev.run(args(paths), factory(script))
        assert json.loads((paths / "ledger.json").read_text())["calls"] == len(script)

    def summary(self, paths, capsys, edits):
        ev.run(args(paths), factory(SCRIPT))
        file = paths / "results" / "scripted_t.json"
        doc = json.loads(file.read_text())
        for index, change in edits.items():
            doc["records"][index].update(change)
        file.write_text(json.dumps(doc))
        capsys.readouterr()
        assert ev.summarise(argparse.Namespace(
            files=[str(file)], price_in=None, price_out=None)) == 0
        return capsys.readouterr().out

    def test_summarise_counts_repaired_answers_against_repaired_handoffs(
            self, paths, capsys):
        out = self.summary(paths, capsys, {
            1: {"repaired": True},
            2: {"repaired": True, "status": "handoff",
                "handoff_reason": "ungrounded_numbers", "answer_text": ""}})
        assert ("repair round: 1 answered after a repair ['R11'], "
                "1 handed off after a repair ['R21']") in out

    def test_summarise_reports_no_repairs_and_reads_older_records(self, paths, capsys):
        ev.run(args(paths), factory(SCRIPT))
        file = paths / "results" / "scripted_t.json"
        doc = json.loads(file.read_text())
        for record in doc["records"]:
            del record["repaired"]
        file.write_text(json.dumps(doc))
        capsys.readouterr()
        assert ev.summarise(argparse.Namespace(
            files=[str(file)], price_in=None, price_out=None)) == 0
        out = capsys.readouterr().out
        assert "repair round: 0 answered after a repair [], 0 handed off" in out

    def test_a_spend_cap_still_stops_the_run_rather_than_becoming_an_internal_error(
            self, paths):
        assert ev.run(args(paths, cap=2), factory(SCRIPT)) == 1
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert doc["meta"]["status"].startswith("incomplete")
        assert "internal_error" not in [r["handoff_reason"] for r in doc["records"]]

    def test_summarise_lists_internal_errors_and_keeps_them_in_the_rates(
            self, paths, capsys):
        ev.run(args(paths), factory(SCRIPT))
        file = paths / "results" / "scripted_t.json"
        doc = json.loads(file.read_text())
        doc["records"][1].update(status="handoff", handoff_reason="internal_error",
                                 answer_text="", route="data")
        file.write_text(json.dumps(doc))
        ns = argparse.Namespace(files=[str(file)], price_in=None, price_out=None)
        assert ev.summarise(ns) == 0
        out = capsys.readouterr().out
        assert "internal_error: 1 ['R11']" in out
        assert "3 request runs scored" in out          # unlike provider_unavailable

    def test_a_missing_key_means_no_call_is_made(self, paths, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert ev.run(args(paths)) == 2
        assert not (paths / "ledger.json").exists()


class TestPreflight:
    """One tiny real call before the first request, so a broken setup stops the
    run before it writes anything or spends from the cap."""

    def go(self, paths, script, **kw):
        return ev.run(args(paths), factory(script), probe=ev.preflight, **kw)

    def test_a_working_model_is_probed_and_the_probe_is_not_an_eval_call(self, paths):
        assert self.go(paths, ["OK", *SCRIPT]) == 0
        doc = json.loads((paths / "results" / "scripted_t.json").read_text())
        assert doc["meta"]["ledger_calls_total"] == len(SCRIPT)
        assert json.loads((paths / "ledger.json").read_text())["calls"] == len(SCRIPT)

    def test_a_failing_probe_stops_the_run_cleanly_with_one_line(self, paths, capsys):
        error = TypeError("create() got an unexpected keyword argument 'temperature'")
        assert self.go(paths, [error]) == 3
        err = capsys.readouterr().err.strip().splitlines()
        assert len(err) == 1 and err[0].startswith("preflight failed")
        assert "TypeError" in err[0] and "temperature" in err[0]
        assert not (paths / "results").exists() and not (paths / "ledger.json").exists()

    def test_a_probe_that_never_returns_fails_instead_of_hanging(self, paths, monkeypatch):
        monkeypatch.setattr(ev, "CALL_TIMEOUT_S", 0.2)
        assert self.go(paths, [HANG]) == 3
        assert not (paths / "results").exists()

    def test_a_provider_error_in_the_probe_is_not_retried(self, paths):
        model = ScriptedLlm(script=[claude_error(529), "OK"])
        assert ev.run(args(paths), lambda: model, probe=ev.preflight) == 3
        assert len(model.calls) == 1

    def test_the_probe_failure_text_is_scrubbed_and_short(self, paths, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-for-test")
        assert self.go(paths, [RuntimeError("sk-fake-key-for-test " + "q" * 2000)]) == 3
        err = capsys.readouterr().err
        assert "sk-fake-key-for-test" not in err and len(err) < 600

    def test_no_probe_without_the_flag_so_scripted_runs_use_only_their_script(self, paths):
        assert ev.run(args(paths), factory(SCRIPT)) == 0


class TestModelChoice:

    def test_a_claude_model_is_run_through_adks_native_anthropic_class(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-key-for-test")
        from google.adk.models.anthropic_llm import AnthropicLlm

        from multi_agent.claude import ClaudeLlm
        model = ev._make_model("claude-haiku-5-5")
        assert isinstance(model, AnthropicLlm) and model.model == "claude-haiku-5-5"
        # Plain AnthropicLlm forwards temperature=0, which the SDK rejects.
        assert type(model) is ClaudeLlm
        # The SDK's own retries would hide calls from the ledger and the cap.
        assert model.client.max_retries == 0
        assert model.client.timeout == ev.CLAUDE_CALL_TIMEOUT_S

    def test_a_gemini_model_still_goes_through_adks_gemini_class(self):
        from google.adk.models.google_llm import Gemini
        assert isinstance(ev._make_model("gemini-3.8-flash"), Gemini)

    @pytest.mark.parametrize("name, env", [("claude-haiku-5-5", "ANTHROPIC_API_KEY"),
                                           ("gemini-3.8-flash", "GOOGLE_API_KEY")])
    def test_each_provider_needs_its_own_key_and_no_call_is_made_without_it(
            self, paths, monkeypatch, name, env):
        monkeypatch.delenv(env, raising=False)
        assert ev.run(args(paths, model=name)) == 2
        assert not (paths / "ledger.json").exists()

    def test_a_key_for_the_other_provider_does_not_satisfy_the_check(self, paths, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert ev.run(args(paths, model="claude-haiku-5-5")) == 2


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
