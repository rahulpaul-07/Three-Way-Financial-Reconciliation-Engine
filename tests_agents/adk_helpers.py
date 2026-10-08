"""
A scripted model for the router tests.

It plays every agent in a request, in order: the router's first turn, then
whichever specialist the router chose. Each script entry is one model turn:

    "text"                      a final text answer
    ("tool_name", {args})       one tool call
    [("a", {}), ("b", {})]      several tool calls in one turn
    an Exception instance       the call fails with it

The model records what each call was shown (the tools on offer, the system
instruction, the user text) so a test can assert on what the agent could see,
not just on what it did. Nothing here touches the network.
"""

from __future__ import annotations

from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

PROMPT_TOKENS = 11
OUTPUT_TOKENS = 7


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    script: list[Any] = Field(default_factory=list)
    calls: list[dict[str, Any]] = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        system = llm_request.config.system_instruction if llm_request.config else ""
        user = [p.text for c in llm_request.contents if c.role == "user"
                for p in c.parts or [] if p.text]
        self.calls.append({"tools": sorted(llm_request.tools_dict or {}),
                           "system": system if isinstance(system, str) else str(system),
                           "user": user})
        if not self.script:
            raise AssertionError("the scripted model was called more times than scripted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        yield LlmResponse(
            content=types.Content(role="model", parts=_parts(step)),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=PROMPT_TOKENS, candidates_token_count=OUTPUT_TOKENS))


def _parts(step: Any) -> list[types.Part]:
    if isinstance(step, str):
        return [types.Part(text=step)]
    calls = [step] if isinstance(step, tuple) else step
    return [types.Part(function_call=types.FunctionCall(name=n, args=a))
            for n, a in calls]


def route(name: str, reason: str = "scripted") -> str:
    """A router turn choosing `name`, as the router is asked to write it."""
    import json
    return json.dumps({"route": name, "reason": reason})


def verdict(classification: str, resolved: bool = False, reasoning: str = "from tools",
            note: str = "") -> str:
    """An investigator's final turn, in the JSON shape agent.py asks for."""
    import json
    return json.dumps({"classification": classification, "resolved": resolved,
                       "reasoning": reasoning, "analyst_note": note})
