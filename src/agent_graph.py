"""
The resolution agent as a LangGraph state machine.

agent.py runs the investigation as a loop. This module runs the same
investigation as an explicit graph, which makes the control flow something you
can read off a diagram instead of reconstruct from a for-loop:

                    +--> verdict ------------------> END   (model answered)
    START --> model +--> END                               (model error)
                    +--> tools --+--> model                (more evidence)
                                 +--> step_limit --> END   (out of steps)

It is a port, not a redesign. The four constraints that make the agent safe on
financial data are the same four, and each lives in a node, in code, where the
model cannot negotiate with it:

  * step limit      the router after `tools` ends the run when the round budget
                    is spent; it escalates and never guesses
  * closed registry the `tools` node refuses any name outside the dispatch table
  * taxonomy        the `verdict` node downgrades a classification the fixed
                    taxonomy does not contain
  * evidence        the `verdict` node overrules "resolved" when no tool was
                    called

The model call, the prompt, the verdict parser and the result type are all
imported from agent.py rather than copied, so there is one definition of each
and a change to the rules cannot reach one engine and miss the other. The
provider layer (llm.py, seven providers with scoped failover) is reused for
the same reason: a framework port should change how the steps are sequenced,
not which models you can call.

Why have both engines? The loop is eighty lines with no dependency and is what
the engine ships with, so a bare checkout still runs. The graph is the same
behaviour in the shape agent frameworks use, which is what lets you add
checkpointing, streaming or a human-approval interrupt without rewriting the
control flow. A test runs both against the same scripted model and requires
identical results.

Run:
    python src/investigate.py --data data --engine langgraph
"""

from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from langgraph.graph import END, START, StateGraph  # noqa: E402

from agent import (  # noqa: E402
    CLASSIFICATIONS,
    MAX_STEPS,
    SYSTEM_PROMPT,
    AgentResult,
    ResolutionAgent,
    Step,
)
from llm import Provider, get_provider  # noqa: E402
from tools import TOOL_SCHEMA, InvestigationTools, build_dispatch  # noqa: E402


class InvestigationState(TypedDict, total=False):
    # Reducers: the nodes return only what they add, and LangGraph appends it.
    messages: Annotated[list[dict], operator.add]
    steps: Annotated[list[Step], operator.add]

    rounds: int                 # model rounds used so far
    model_calls: int
    pending: list[Any]          # tool calls the model asked for this round
    verdict_text: str
    terminated: str             # answered | step_limit | model_error
    classification: str
    resolved: bool
    reasoning: str
    analyst_note: str


class GraphResolutionAgent:
    """Same interface as ResolutionAgent: investigate() returns an AgentResult."""

    def __init__(self, tools: InvestigationTools, max_steps: int = MAX_STEPS,
                 provider: Provider | None = None):
        self.tools = tools
        self.dispatch = build_dispatch(tools)
        self.max_steps = max_steps
        self.provider = provider or get_provider()
        self.available = self.provider.available
        self.system = SYSTEM_PROMPT.format(
            max_steps=max_steps, classifications=", ".join(CLASSIFICATIONS))
        self.graph = self._build()

    # -- nodes -------------------------------------------------------------

    def _model(self, state: InvestigationState) -> dict:
        resp = self.provider.complete(self.system, state["messages"],
                                      tools=TOOL_SCHEMA, max_tokens=1024)
        out: dict[str, Any] = {"rounds": state["rounds"] + 1,
                               "model_calls": state["model_calls"] + 1}

        if not resp.ok:
            out["terminated"] = "model_error"
            out["analyst_note"] = (f"agent aborted: {resp.error[:120]}; "
                                   f"record remains an exception")
        elif not resp.wants_tools:
            out["terminated"] = "answered"
            out["verdict_text"] = resp.text
        else:
            out["pending"] = resp.tool_calls
            out["messages"] = [self.provider.assistant_turn(resp)]
        return out

    def _tools(self, state: InvestigationState) -> dict:
        steps: list[Step] = []
        results = []
        n = len(state["steps"])

        for use in state["pending"]:
            n += 1      # numbered by call, not by round, so a trace never repeats
            fn = self.dispatch.get(use.name)
            if fn is None:
                # Closed registry: anything outside it is refused, and the
                # refusal is visible in the trace.
                payload = {"ok": False,
                           "summary": f"tool '{use.name}' is not available"}
                steps.append(Step(n, use.name, dict(use.arguments), False,
                                  payload["summary"]))
            else:
                try:
                    tr = fn(**use.arguments)
                    payload = {"ok": tr.ok, "summary": tr.summary,
                               "evidence": tr.evidence}
                    steps.append(Step(n, use.name, dict(use.arguments),
                                      tr.ok, tr.summary))
                except TypeError as exc:
                    payload = {"ok": False,
                               "summary": f"invalid arguments: {exc}"}
                    steps.append(Step(n, use.name, dict(use.arguments), False,
                                      payload["summary"]))
            results.append((use.id, payload))

        return {"steps": steps, "pending": [],
                "messages": [self.provider.tool_results_turn(results)]}

    def _verdict(self, state: InvestigationState) -> dict:
        # Taxonomy and evidence checks live in ResolutionAgent._parse_verdict,
        # imported rather than copied. It needs the steps taken so far, because
        # a claimed resolution with no tool call behind it is overruled.
        scratch = AgentResult(entity_id="", entity_type="",
                              steps=list(state["steps"]))
        ResolutionAgent._parse_verdict(state["verdict_text"], scratch)
        return {"classification": scratch.classification,
                "resolved": scratch.resolved,
                "reasoning": scratch.reasoning,
                "analyst_note": scratch.analyst_note}

    def _step_limit(self, state: InvestigationState) -> dict:
        return {"terminated": "step_limit", "classification": "unexplained",
                "resolved": False,
                "analyst_note": (f"investigation did not conclude within "
                                f"{self.max_steps} steps; escalated for "
                                f"manual review")}

    # -- routing -----------------------------------------------------------

    @staticmethod
    def _after_model(state: InvestigationState) -> str:
        if state.get("terminated") == "model_error":
            return END
        if state.get("terminated") == "answered":
            return "verdict"
        return "tools"

    def _after_tools(self, state: InvestigationState) -> str:
        # The step limit. The budget counts model rounds, as in agent.py.
        return "step_limit" if state["rounds"] >= self.max_steps else "model"

    def _build(self):
        g = StateGraph(InvestigationState)
        g.add_node("model", self._model)
        g.add_node("tools", self._tools)
        g.add_node("verdict", self._verdict)
        g.add_node("step_limit", self._step_limit)

        g.add_edge(START, "model")
        g.add_conditional_edges("model", self._after_model,
                                {"tools": "tools", "verdict": "verdict", END: END})
        g.add_conditional_edges("tools", self._after_tools,
                                {"model": "model", "step_limit": "step_limit"})
        g.add_edge("verdict", END)
        g.add_edge("step_limit", END)
        return g.compile()

    # -- public ------------------------------------------------------------

    def mermaid(self) -> str:
        """The control flow as a Mermaid diagram, generated from the graph."""
        return self.graph.get_graph().draw_mermaid()

    def investigate(self, entity_id: str, entity_type: str,
                    context: str) -> AgentResult:
        result = AgentResult(entity_id=entity_id, entity_type=entity_type)

        if not self.available:
            result.terminated = "unavailable"
            result.analyst_note = (
                f"agent not run: {getattr(self.provider, 'reason', 'no provider')}; "
                f"record remains an exception")
            return result

        final = self.graph.invoke({
            "messages": [{"role": "user", "content": context}],
            "steps": [], "rounds": 0, "model_calls": 0, "pending": [],
        })

        result.steps = list(final.get("steps", []))
        result.model_calls = final.get("model_calls", 0)
        result.terminated = final.get("terminated", "")
        result.classification = final.get("classification", "unexplained")
        result.resolved = final.get("resolved", False)
        result.reasoning = final.get("reasoning", "")
        result.analyst_note = final.get("analyst_note", "")
        return result
