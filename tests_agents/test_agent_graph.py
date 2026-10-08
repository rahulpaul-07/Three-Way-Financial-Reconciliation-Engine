"""
Tests for the LangGraph resolution agent.

No model is involved. A scripted provider plays the part of a model, including
a misbehaving one, and the graph is checked two ways:

  * against the loop agent (agent.py). The graph is a port, so for any
    conversation both engines must reach the same result. This is the strongest
    test available: it does not assert what the right answer is, only that
    rewriting the control flow changed nothing.

  * against the four constraints directly. Each is enforced in code, so each
    is tested by giving the agent the output a model that ignores its prompt
    would produce.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("langgraph")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent import CLASSIFICATIONS, ResolutionAgent  # noqa: E402
from agent_graph import GraphResolutionAgent  # noqa: E402
from llm import LLMResponse, Provider, ToolCall  # noqa: E402
from matcher import load  # noqa: E402
from tools import InvestigationTools  # noqa: E402

VALID = CLASSIFICATIONS[0]


class Scripted(Provider):
    """Plays back a fixed list of responses, one per model call."""
    name = "scripted"
    available = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete(self, system, messages, tools=None, max_tokens=1024, model=None):
        self.calls += 1
        if not self.script:
            raise AssertionError("agent asked the model more often than scripted")
        return self.script.pop(0)

    @staticmethod
    def assistant_turn(resp):
        return {"role": "assistant", "content": resp.text}

    @staticmethod
    def tool_results_turn(results):
        return {"role": "user", "content": results}


def call(name, **args):
    return ToolCall(id=f"id-{name}", name=name, arguments=args)


def asks(*calls):
    return LLMResponse(tool_calls=list(calls), provider="scripted")


def says(text):
    return LLMResponse(text=text, provider="scripted")


def verdict(classification=VALID, resolved=True):
    body = {"classification": classification, "resolved": resolved,
            "reasoning": "r", "analyst_note": ""}
    return says(json.dumps(body))


@pytest.fixture(scope="module")
def batch():
    return load(ROOT / "data")


def engines(batch, script_factory, **kw):
    """Run the same scripted conversation through both engines."""
    out = []
    for cls in (ResolutionAgent, GraphResolutionAgent):
        provider = Scripted(script_factory())
        agent = cls(InvestigationTools(*batch), provider=provider, **kw)
        out.append((agent.investigate("E1", "order", "context"), provider))
    return out


def comparable(result, with_numbers=True):
    steps = [(s.n if with_numbers else None, s.tool, s.tool_input, s.ok, s.summary)
             for s in result.steps]
    return (result.classification, result.resolved, result.reasoning,
            result.analyst_note, result.terminated, result.model_calls, steps)


# --------------------------------------------------------------------------
# Equivalence with the loop agent
# --------------------------------------------------------------------------

class TestSameAsTheLoop:

    def scenarios(self, batch):
        orders, txns, settlements, bank = batch
        oid = orders[0].order_id
        return {
            "answers with no investigation": lambda: [verdict()],
            "one tool then resolves": lambda: [
                asks(call("get_order", order_id=oid)), verdict()],
            "escalates honestly": lambda: [
                asks(call("get_order", order_id=oid)),
                verdict(resolved=False)],
            "several calls in one round": lambda: [
                asks(call("get_order", order_id=oid),
                     call("find_related_transactions", order_id=oid)),
                verdict()],
            "invalid arguments": lambda: [
                asks(call("get_order", wrong_name=1)), verdict()],
            "invented classification": lambda: [
                asks(call("get_order", order_id=oid)),
                verdict(classification="made_up_category")],
            "unparseable verdict": lambda: [
                asks(call("get_order", order_id=oid)), says("looks fine to me")],
            "model error mid-investigation": lambda: [
                asks(call("get_order", order_id=oid)),
                LLMResponse(error="503 upstream", provider="scripted")],
            "never stops asking": lambda: [
                asks(call("get_order", order_id=oid)) for _ in range(5)],
        }

    def test_every_scenario_gives_identical_results(self, batch):
        for label, factory in self.scenarios(batch).items():
            (loop, _), (graph, _) = engines(batch, factory)
            assert comparable(graph) == comparable(loop), label

    def test_unknown_tool_is_refused_the_same_way(self, batch):
        """
        One deliberate difference. For a tool outside the registry the loop
        numbers the refused step by model round, so a refusal after one earlier
        call in the same round repeats a number; the graph numbers every call
        in sequence. Everything else must still match.
        """
        oid = batch[0][0].order_id

        def script():
            return [asks(call("get_order", order_id=oid), call("execute_sql", q="x")),
                    verdict()]
        (loop, _), (graph, _) = engines(batch, script)
        assert comparable(graph, with_numbers=False) == comparable(loop, with_numbers=False)
        assert [s.n for s in graph.steps] == [1, 2]
        assert [s.n for s in loop.steps] == [1, 1]      # the quirk, pinned


# --------------------------------------------------------------------------
# The four constraints, each in code
# --------------------------------------------------------------------------

class TestConstraints:

    def agent(self, batch, script, max_steps=5):
        provider = Scripted(script)
        return GraphResolutionAgent(InvestigationTools(*batch),
                                    max_steps=max_steps, provider=provider), provider

    def test_step_limit_ends_the_run_and_escalates(self, batch):
        oid = batch[0][0].order_id
        agent, provider = self.agent(
            batch, [asks(call("get_order", order_id=oid)) for _ in range(10)],
            max_steps=3)
        res = agent.investigate("E1", "order", "ctx")
        assert provider.calls == 3, "the model was called past the budget"
        assert res.terminated == "step_limit"
        assert res.classification == "unexplained" and not res.resolved
        assert "3 steps" in res.analyst_note

    @pytest.mark.parametrize("name", [
        "delete_all_records",   # does not exist anywhere
        "_record",              # exists on the tools object but is not a tool
        "calls",                # an attribute, not a method
    ])
    def test_registry_is_closed(self, batch, name):
        """
        Refusal is by the dispatch table, not by whether the name happens to
        resolve. The second and third cases fail if lookup ever becomes
        getattr on the tools object, which would hand the model every method
        that object has.
        """
        agent, _ = self.agent(batch, [asks(call(name)), verdict()])
        res = agent.investigate("E1", "order", "ctx")
        assert res.steps[0].ok is False
        assert "not available" in res.steps[0].summary
        assert name not in agent.dispatch

    def test_taxonomy_is_enforced(self, batch):
        oid = batch[0][0].order_id
        agent, _ = self.agent(batch, [asks(call("get_order", order_id=oid)),
                                      verdict(classification="definitely_fine")])
        res = agent.investigate("E1", "order", "ctx")
        assert res.classification == "unexplained" and not res.resolved
        assert "outside the taxonomy" in res.analyst_note

    def test_resolution_needs_evidence(self, batch):
        agent, _ = self.agent(batch, [verdict()])
        res = agent.investigate("E1", "order", "ctx")
        assert not res.resolved
        assert "without calling any tool" in res.analyst_note

    def test_a_model_failure_becomes_an_escalation(self, batch):
        agent, _ = self.agent(batch,
                              [LLMResponse(error="boom", provider="scripted")])
        res = agent.investigate("E1", "order", "ctx")
        assert res.terminated == "model_error" and not res.resolved
        assert "remains an exception" in res.analyst_note


class TestAvailability:

    def test_no_provider_means_no_run_and_says_so(self, batch):
        class Off(Scripted):
            available = False
            reason = "no key"
        agent = GraphResolutionAgent(InvestigationTools(*batch), provider=Off([]))
        res = agent.investigate("E1", "order", "ctx")
        assert res.terminated == "unavailable"
        assert "no key" in res.analyst_note


class TestStructure:

    def test_graph_has_the_documented_nodes(self, batch):
        agent = GraphResolutionAgent(InvestigationTools(*batch),
                                     provider=Scripted([]))
        diagram = agent.mermaid()
        for node in ("model", "tools", "verdict", "step_limit"):
            assert node in diagram
