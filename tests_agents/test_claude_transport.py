"""
The real Claude client, against a fake HTTP server.

The other router tests play the model with a scripted stand-in, which never
reaches ADK's Anthropic class or the Anthropic SDK. A mismatch between the two
(ADK passing a keyword the installed SDK does not accept) therefore only showed
up in a live run. These tests build the real ClaudeLlm and the real SDK client
and replace only the network with httpx.MockTransport, so that mismatch fails
here. Nothing leaves the machine and no key is used.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx2
import pytest

pytest.importorskip("google.adk")
pytest.importorskip("anthropic")
pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from adk_helpers import route, verdict  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.genai import types  # noqa: E402

from multi_agent.app import RouterApp  # noqa: E402
from multi_agent.claude import ClaudeLlm  # noqa: E402
from multi_agent.handoff import Reason  # noqa: E402

SAMPLING = ("temperature", "top_p", "top_k")


def message(*blocks: dict, stop: str = "end_turn") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant",
            "model": "claude-haiku-5-5", "content": list(blocks), "stop_reason": stop,
            "stop_sequence": None, "usage": {"input_tokens": 21, "output_tokens": 5}}


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool_use(name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": "toolu_test", "name": name, "input": args}


class FakeAnthropic:
    """Answers each POST with the next message and keeps what was sent."""

    def __init__(self, *replies: dict):
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=self.replies.pop(0))

    def model(self) -> ClaudeLlm:
        client = AsyncAnthropic(api_key="sk-fake-key-for-test", max_retries=0,
                                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self)))
        return ClaudeLlm(model="claude-haiku-5-5", client=client)


def ask(model: ClaudeLlm, config: types.GenerateContentConfig) -> list:
    request = LlmRequest(
        model="claude-haiku-5-5", config=config,
        contents=[types.Content(role="user", parts=[types.Part(text="Reply OK.")])])

    async def go():
        return [r async for r in model.generate_content_async(request, stream=False)]

    return asyncio.run(go())


class TestSamplingParameters:

    def test_a_request_with_temperature_zero_is_sent_without_it(self):
        fake = FakeAnthropic(message(text("OK")))
        replies = ask(fake.model(), types.GenerateContentConfig(temperature=0))
        assert replies[0].content.parts[0].text == "OK"
        body = fake.bodies[0]
        assert not [k for k in SAMPLING if k in body]
        assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] > 0

    def test_top_p_and_top_k_are_dropped_too(self):
        fake = FakeAnthropic(message(text("OK")))
        ask(fake.model(), types.GenerateContentConfig(temperature=0.2, top_p=0.9, top_k=40))
        assert not [k for k in SAMPLING if k in fake.bodies[0]]

    def test_the_callers_request_is_not_changed(self):
        fake = FakeAnthropic(message(text("OK")))
        config = types.GenerateContentConfig(temperature=0)
        request = LlmRequest(model="claude-haiku-5-5", config=config, contents=[
            types.Content(role="user", parts=[types.Part(text="hi")])])

        async def go():
            return [r async for r in fake.model().generate_content_async(request)]
        asyncio.run(go())
        assert request.config.temperature == 0

    def test_a_request_with_no_config_still_works(self):
        fake = FakeAnthropic(message(text("OK")))
        request = LlmRequest(model="claude-haiku-5-5", contents=[
            types.Content(role="user", parts=[types.Part(text="hi")])])

        async def go():
            return [r async for r in fake.model().generate_content_async(request)]
        assert asyncio.run(go())[0].content.parts[0].text == "OK"


class TestPreflightOnTheRealClient:

    def test_the_probe_passes_through_the_real_sdk_without_sampling_parameters(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import router_eval as ev
        fake = FakeAnthropic(message(text("OK")))
        assert asyncio.run(ev.preflight(fake.model())) is None
        assert len(fake.bodies) == 1
        assert not [k for k in SAMPLING if k in fake.bodies[0]]


class TestWholeRequestThroughTheRealClient:
    """The router and a specialist, every agent setting temperature=0 as it does
    live, with real MCP tools and the real SDK; only the network is fake."""

    def handle(self, fake: FakeAnthropic, request: str):
        async def go():
            async with RouterApp(model=fake.model(), data_dir=ROOT / "data") as app:
                return await app.handle(request)
        return asyncio.run(go())

    def test_a_request_routed_to_a_person_makes_one_valid_call(self):
        fake = FakeAnthropic(message(text(route("human"))))
        out = self.handle(fake, "Please approve this refund.")
        assert out.handoff.reason is Reason.ROUTED_TO_HUMAN
        assert len(fake.bodies) == 1
        assert not [k for k in SAMPLING if k in fake.bodies[0]]

    def test_an_investigation_with_a_tool_call_round_trips(self):
        fake = FakeAnthropic(
            message(text(route("investigator"))),
            message(tool_use("get_record_facts", {"entity_id": "ORD4026"}),
                    stop="tool_use"),
            message(text(verdict("missing_payment"))))
        out = self.handle(fake, "Why is ORD4026 unpaid?")
        assert out.status == "answered" and out.answer.data["classification"] == "missing_payment"
        assert [t.name for t in out.tools] == ["get_record_facts"]
        assert len(fake.bodies) == 3
        for body in fake.bodies:
            assert not [k for k in SAMPLING if k in body]
        # The tool schemas reached the API and the tool result came back to the model.
        assert fake.bodies[1]["tools"]
        last = json.dumps(fake.bodies[2]["messages"][-1])
        assert "tool_result" in last
