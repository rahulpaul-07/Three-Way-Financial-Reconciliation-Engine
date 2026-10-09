"""What a request ends in: an answer, or a handoff note for a person."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Reason(StrEnum):
    ROUTED_TO_HUMAN = "routed_to_human"
    INVALID_ROUTE = "invalid_route"
    UNEXPLAINED = "unexplained"
    INVALID_VERDICT = "invalid_verdict"
    NO_EVIDENCE = "no_evidence"
    STEP_LIMIT = "step_limit"
    MODEL_ERROR = "model_error"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    REQUEST_TIMEOUT = "request_timeout"
    UNGROUNDED_NUMBERS = "ungrounded_numbers"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class ToolUse:
    agent: str
    name: str
    args: dict[str, Any]
    ok: bool


@dataclass
class Answer:
    agent: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Handoff:
    request: str
    reason: Reason
    detail: str
    agent: str | None = None
    tools: list[ToolUse] = field(default_factory=list)

    def note(self) -> str:
        """The note a person reads: what was asked, who tried, what they did, why it stopped."""
        lines = [f"Request: {self.request}"]
        lines.append("Tried by: " + (self.agent or "no agent tried this request"))
        if self.tools:
            lines.append("Tools called:")
            for t in self.tools:
                args = ", ".join(f"{k}={v!r}" for k, v in t.args.items())
                lines.append(f"  {t.name}({args}) -> {'ok' if t.ok else 'failed or refused'}")
        elif self.agent is not None:
            lines.append("Tools called: none")
        lines.append(f"Stopped because: {self.reason.value}"
                     + (f" ({self.detail})" if self.detail else ""))
        return "\n".join(lines)
