"""
The router application: one request in, an answer or a handoff out.

Control flow is plain code, not a model decision. The router agent proposes one
of three destinations; this module validates it, runs the chosen specialist,
and judges the result. The rules it enforces:

  * the router can only choose investigator, data or human; anything else is human
  * each specialist is offered its own closed tool set; no write tool exists
  * one budget of model calls covers every agent in a request; when it runs
    out the request becomes a handoff
  * a specialist that escalates, fails or cannot ground its figures becomes a
    handoff with a note, never a guessed answer
  * the request is a user message only; it is never placed in an instruction
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from google.adk.models.base_llm import BaseLlm
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import Client, StdioServerParameters

from agent import MAX_STEPS as INVESTIGATOR_STEPS
from sql_ask import MAX_STEPS as DATA_STEPS

from .budget import (
    BudgetedModel,
    BudgetExhausted,
    CallBudget,
    CallRecord,
    ModelFailure,
    ProviderUnavailable,
    StepLimitExceeded,
    quiet_handled_errors,
    scrub_secrets,
    short_error,
)
from .handoff import Answer, Handoff, Reason, ToolUse
from .routing import ROUTER_PROMPT, parse_route
from .specialists import (
    DATA_TOOLS,
    INVESTIGATOR_TOOLS,
    AgentRun,
    data_follow_up,
    data_prompt,
    investigator_prompt,
    judge_data,
    judge_investigator,
    run_agent,
)

logger = logging.getLogger(__name__)

MCP_SERVER = Path(__file__).resolve().parents[1] / "mcp_server.py"
MCP_TIMEOUT_SECONDS = 30
# One request, router and specialist together, retries and tool calls included.
# Nothing a model or a tool does can hold a request longer than this.
REQUEST_TIMEOUT_S = 300

# The router, plus the longest specialist (the data agent).
DEFAULT_TOTAL_BUDGET = 1 + DATA_STEPS


class McpUnavailable(RuntimeError):
    """The MCP server did not start and answer within the timeout."""


@dataclass
class Outcome:
    request: str
    route: str | None = None
    status: str = "handoff"                  # answered | handoff
    answer: Answer | None = None
    handoff: Handoff | None = None
    calls: list[CallRecord] = field(default_factory=list)
    tools: list[ToolUse] = field(default_factory=list)
    router_raw: str = ""
    agent: str | None = None         # the agent running when the request ended
    specialist: AgentRun | None = None

    @property
    def repaired(self) -> bool:
        """The specialist was sent a repair follow-up, whatever came of it."""
        return self.specialist is not None and self.specialist.repaired

    @property
    def model_calls(self) -> int:
        return len(self.calls)


class RouterApp:
    def __init__(self, model: BaseLlm, data_dir: str | Path = "data",
                 total_budget: int = DEFAULT_TOTAL_BUDGET,
                 request_timeout: float = REQUEST_TIMEOUT_S,
                 fatal: tuple[type[Exception], ...] = ()):
        self._model = model
        # Exceptions the caller wants to stop its run (a spend cap, say); any
        # other unexpected one becomes an internal_error handoff.
        self._fatal = fatal
        self._request_timeout = request_timeout
        self._data_dir = str(data_dir)
        self._total_budget = total_budget
        self._schema = ""
        self._toolsets: list[McpToolset] = []

    def _server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable, args=[str(MCP_SERVER), "--data", self._data_dir])

    def _toolset(self, allowed: frozenset[str]) -> McpToolset:
        toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=self._server_params(), timeout=MCP_TIMEOUT_SECONDS),
            tool_filter=sorted(allowed))
        self._toolsets.append(toolset)
        return toolset

    async def __aenter__(self) -> RouterApp:
        # The schema goes into the data agent's prompt. It is fetched once, over
        # MCP, with no model call.
        try:
            async with asyncio.timeout(MCP_TIMEOUT_SECONDS):
                async with Client(self._server_params()) as client:
                    result = await client.call_tool("describe_schema", {})
        except TimeoutError:
            raise McpUnavailable(
                f"the MCP server gave no answer within {MCP_TIMEOUT_SECONDS}s") from None
        self._schema = result.content[0].text
        quiet_handled_errors()
        self._investigator_tools = self._toolset(INVESTIGATOR_TOOLS)
        self._data_tools = self._toolset(DATA_TOOLS)
        return self

    async def __aexit__(self, *exc_info) -> None:
        for toolset in self._toolsets:
            try:
                async with asyncio.timeout(MCP_TIMEOUT_SECONDS):
                    await toolset.close()
            except TimeoutError:
                logger.warning("an MCP toolset did not close within %ss; moving on",
                               MCP_TIMEOUT_SECONDS)

    def _wrap(self, name: str, budget: CallBudget, max_calls: int) -> BudgetedModel:
        return BudgetedModel(model=self._model.model, inner=self._model, budget=budget,
                             agent_name=name, max_calls=max_calls)

    async def handle(self, request: str) -> Outcome:
        budget = CallBudget(self._total_budget)
        outcome = Outcome(request=request, calls=budget.calls)
        limit = asyncio.timeout(self._request_timeout)
        try:
            async with limit:
                return await self._handle(request, budget, outcome)
        except self._fatal:
            raise
        except Exception as exc:
            # Only this request's own limit is a request timeout. A TimeoutError
            # from a model call never gets here: the wrapper makes it a
            # ProviderUnavailable first.
            if isinstance(exc, TimeoutError) and limit.expired():
                handoff = Handoff(request, Reason.REQUEST_TIMEOUT,
                                  f"no result within {self._request_timeout:g}s",
                                  outcome.agent, outcome.tools)
            else:
                # A bug, not a model or provider failure. It is a handoff so one
                # bad request does not end a run, and it is logged in full so it
                # is not lost. Kept apart from model_error so it cannot hide in
                # that count.
                logger.error("unexpected error in a request: %s",
                             scrub_secrets("".join(traceback.format_exception(exc))))
                handoff = Handoff(request, Reason.INTERNAL_ERROR,
                                  short_error(f"{type(exc).__name__}: {exc}"),
                                  outcome.agent, outcome.tools)
            return self._finish(outcome, handoff=handoff)

    async def _handle(self, request: str, budget: CallBudget, outcome: Outcome) -> Outcome:
        router = AgentRun("router")
        outcome.agent = "router"
        stop = await self._run("router", router, request, run_agent(
            name="router", instruction=ROUTER_PROMPT, tools=[], request=request, run=router,
            model=self._wrap("router", budget, 1),
            config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json")))
        outcome.router_raw = router.final_text
        if stop:
            return self._finish(outcome, handoff=stop)

        decision = parse_route(router.final_text)
        outcome.route = decision.route
        if decision.route == "human":
            reason = Reason.ROUTED_TO_HUMAN if decision.valid else Reason.INVALID_ROUTE
            return self._finish(outcome, handoff=Handoff(request, reason, decision.reason))

        if decision.route == "investigator":
            name, instruction, tools, limit = (
                "investigator", investigator_prompt(), self._investigator_tools,
                INVESTIGATOR_STEPS)
            judge = judge_investigator
        else:
            name, instruction, tools, limit = (
                "data", data_prompt(self._schema), self._data_tools, DATA_STEPS)
            judge = judge_data

        specialist = AgentRun(name)
        # Shared, not copied, so a request cut off mid-run still has its trace.
        outcome.agent, outcome.tools, outcome.specialist = name, specialist.tools, specialist
        stop = await self._run(name, specialist, request, run_agent(
            name=name, instruction=instruction, tools=[tools], request=request,
            run=specialist, model=self._wrap(name, budget, limit),
            review=(lambda run: data_follow_up(request, run)) if name == "data" else None))
        if stop:
            return self._finish(outcome, handoff=stop)
        verdict = judge(request, specialist)
        if isinstance(verdict, Handoff):
            return self._finish(outcome, handoff=verdict)
        return self._finish(outcome, answer=verdict)

    @staticmethod
    async def _run(agent: str, run: AgentRun, request: str, coro) -> Handoff | None:
        """Await one agent; turn the three expected stops into a handoff.
        Anything else is a bug and is left to propagate."""
        try:
            await coro
        except BudgetExhausted as exc:
            return Handoff(request, Reason.BUDGET_EXHAUSTED, str(exc), agent, run.tools)
        except StepLimitExceeded as exc:
            return Handoff(request, Reason.STEP_LIMIT, str(exc), agent, run.tools)
        except ProviderUnavailable as exc:
            return Handoff(request, Reason.PROVIDER_UNAVAILABLE, str(exc), agent, run.tools)
        except ModelFailure as exc:
            return Handoff(request, Reason.MODEL_ERROR, str(exc), agent, run.tools)
        return None

    @staticmethod
    def _finish(outcome: Outcome, handoff: Handoff | None = None,
                answer: Answer | None = None) -> Outcome:
        outcome.handoff, outcome.answer = handoff, answer
        outcome.status = "answered" if answer else "handoff"
        return outcome
