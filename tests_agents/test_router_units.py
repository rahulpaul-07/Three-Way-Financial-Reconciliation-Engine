"""
Unit tests for the pieces of the router that need no MCP server: the model
wrapper's error mapping and secret scrubbing, the route parser, the note.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("google.adk")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adk_helpers import ScriptedLlm  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402

from multi_agent.budget import (  # noqa: E402
    BudgetedModel,
    BudgetExhausted,
    CallBudget,
    ModelFailure,
    ProviderUnavailable,
    StepLimitExceeded,
    quiet_handled_errors,
    scrub_secrets,
)
from multi_agent.handoff import Handoff, Reason, ToolUse  # noqa: E402
from multi_agent.routing import parse_route  # noqa: E402


def drain(model: BudgetedModel) -> None:
    async def go():
        async for _ in model.generate_content_async(LlmRequest()):
            pass
    asyncio.run(go())


def wrapped(script, *, limit=5, max_calls=5) -> tuple[BudgetedModel, ScriptedLlm]:
    inner = ScriptedLlm(script=list(script))
    return BudgetedModel(model="scripted", inner=inner, budget=CallBudget(limit),
                         agent_name="a", max_calls=max_calls), inner


class TestBudgetedModel:

    def test_refuses_the_call_after_the_total_without_calling_the_model(self):
        model, inner = wrapped(["x", "y"], limit=1)
        drain(model)
        with pytest.raises(BudgetExhausted):
            drain(model)
        assert len(inner.calls) == 1

    def test_refuses_the_call_after_the_agents_own_limit(self):
        model, inner = wrapped(["x", "y"], max_calls=1)
        drain(model)
        with pytest.raises(StepLimitExceeded):
            drain(model)
        assert len(inner.calls) == 1

    def test_a_failed_call_still_costs_budget(self):
        model, _ = wrapped([genai_errors.APIError(503, {"error": {"message": "down"}})])
        with pytest.raises(ModelFailure):
            drain(model)
        assert len(model.budget.calls) == 1

    @pytest.mark.parametrize("exc", [
        genai_errors.APIError(429, {"error": {"message": "quota"}}),
        httpx.ConnectError("no route"),
        TimeoutError("slow"),
    ])
    def test_transport_and_api_errors_become_model_failure(self, exc):
        model, _ = wrapped([exc])
        with pytest.raises(ModelFailure):
            drain(model)

    @pytest.mark.parametrize("code", [500, 503, 504])
    def test_a_provider_outage_is_told_apart_from_other_failures(self, code):
        model, _ = wrapped([genai_errors.APIError(code, {"error": {"message": "busy"}})])
        with pytest.raises(ProviderUnavailable):
            drain(model)

    @pytest.mark.parametrize("code", [400, 401, 403, 429])
    def test_other_api_errors_are_a_plain_model_failure(self, code):
        model, _ = wrapped([genai_errors.APIError(code, {"error": {"message": "no"}})])
        with pytest.raises(ModelFailure) as caught:
            drain(model)
        assert not isinstance(caught.value, ProviderUnavailable)

    def test_a_programming_error_is_not_mapped(self):
        model, _ = wrapped([KeyError("bug")])
        with pytest.raises(KeyError):
            drain(model)

    def test_the_api_key_is_removed_from_the_failure_message(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-value-for-test")
        model, _ = wrapped([httpx.ConnectError("GET https://x/?key=fake-key-value-for-test")])
        with pytest.raises(ModelFailure) as caught:
            drain(model)
        assert "fake-key-value-for-test" not in str(caught.value)
        assert "[redacted]" in str(caught.value)

    def test_scrub_leaves_text_alone_when_no_key_is_set(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert scrub_secrets("plain") == "plain"


class TestQuietHandledErrors:

    def emit(self, caplog, logger_name, exc):
        logger = logging.getLogger(logger_name)
        try:
            raise exc
        except Exception:
            logger.error("Node execution failed with exception", exc_info=True)

    @pytest.fixture
    def adk_logger(self, caplog):
        # Created after the install, as ADK creates some of its loggers lazily.
        quiet_handled_errors()
        name = "google_adk.test_quiet.node"
        caplog.set_level(logging.INFO)
        return name

    @pytest.mark.parametrize("exc", [
        ModelFailure("x"), ProviderUnavailable("x"), BudgetExhausted("x"),
        StepLimitExceeded("x")])
    def test_a_traceback_for_an_error_the_wrapper_already_handled_is_dropped(
            self, caplog, adk_logger, exc):
        self.emit(caplog, adk_logger, exc)
        assert caplog.records == []

    def test_a_traceback_for_any_other_error_still_appears(self, caplog, adk_logger):
        self.emit(caplog, adk_logger, KeyError("bug"))
        assert len(caplog.records) == 1

    def test_a_message_without_an_exception_still_appears(self, caplog, adk_logger):
        logging.getLogger(adk_logger).warning("something else")
        assert [r.getMessage() for r in caplog.records] == ["something else"]

    def test_our_own_loggers_are_untouched(self, caplog, adk_logger):
        self.emit(caplog, "multi_agent.app", ModelFailure("ours"))
        assert len(caplog.records) == 1

    def test_installing_twice_does_not_stack_filters(self, adk_logger):
        quiet_handled_errors()
        assert len(logging.lastResort.filters) == 1


class TestParseRoute:

    @pytest.mark.parametrize("route", ["investigator", "data", "human"])
    def test_accepts_exactly_the_three_routes(self, route):
        decision = parse_route(f'{{"route": "{route}", "reason": "r"}}')
        assert (decision.route, decision.valid) == (route, True)

    @pytest.mark.parametrize("text", [
        '{"route": "DATA"}', '{"route": " data"}', '{"route": null}', '{"route": 1}',
        '{"route": ["data"]}', "```json\n{\"route\": \"data\"}\n```", "null", "42", "",
    ])
    def test_everything_else_is_human_and_flagged(self, text):
        decision = parse_route(text)
        assert (decision.route, decision.valid) == ("human", False)


class TestNote:

    def test_the_note_lists_the_tools_with_their_arguments(self):
        note = Handoff("q", Reason.STEP_LIMIT, "d", "data",
                       [ToolUse("data", "run_sql", {"query": "SELECT 1"}, True)]).note()
        assert "run_sql" in note and "SELECT 1" in note
