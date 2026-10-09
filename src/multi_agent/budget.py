"""
The call budget and the model wrapper that enforces it.

Every agent in a request, the router included, talks to the model through a
BudgetedModel. That one seam does three jobs: it counts calls against a
per-request total, it applies each agent's own step limit, and it records
tokens and latency. Nothing about the limits lives in a prompt.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import anthropic
import httpx
from google.adk.models.base_llm import BaseLlm
from google.genai import errors as genai_errors
from pydantic import ConfigDict


class RunLimit(Exception):
    """A request ran into a limit that the code, not the model, enforces."""


class BudgetExhausted(RunLimit):
    """The per-request total of model calls, across all agents, is used up."""


class StepLimitExceeded(RunLimit):
    """One agent asked for more model calls than its own limit allows."""


class ModelFailure(Exception):
    """The model could not be reached or refused the call (quota, 5xx, timeout)."""


class ProviderUnavailable(ModelFailure):
    """The provider answered 500, 503, 504 or 529, or the call timed out: it, not
    the request, is the problem. Kept apart from other failures so an evaluation
    can leave these out of a score."""


# Errors that say the service is overloaded or down, not that the call was
# wrong (529 is Anthropic's "overloaded"). A caller may retry these; a 400,
# 401 or 403 will not improve.
PROVIDER_OUTAGE_CODES = frozenset({500, 503, 504, 529})

# Both vendors' status-carrying errors, and the timeouts either can produce.
API_STATUS_ERRORS = (genai_errors.APIError, anthropic.APIStatusError)
TIMEOUT_ERRORS = (TimeoutError, httpx.TimeoutException, anthropic.APITimeoutError)

ERROR_TEXT_LIMIT = 300


def error_status(exc: BaseException) -> int | None:
    """The HTTP status of a vendor error: `code` on Google's, `status_code` on Anthropic's."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def retry_after_seconds(exc: BaseException) -> float | None:
    """The vendor's Retry-After header, in seconds, when it sent a usable one."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        value = float(headers.get("retry-after", "")) if headers is not None else None
    except (TypeError, ValueError):
        return None
    return value if value is not None and value >= 0 else None


def is_outage(exc: BaseException) -> bool:
    return error_status(exc) in PROVIDER_OUTAGE_CODES or isinstance(exc, TIMEOUT_ERRORS)


@dataclass
class CallRecord:
    agent: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str = ""                 # scrubbed and truncated; empty when the call succeeded


@dataclass
class CallBudget:
    limit: int
    calls: list[CallRecord] = field(default_factory=list)

    def reserve(self, agent: str) -> CallRecord:
        """Claim one call, or refuse. Counted before the call is made, so a
        call that then fails still costs budget, as it would cost money."""
        if len(self.calls) >= self.limit:
            raise BudgetExhausted(f"{self.limit} model calls used")
        record = CallRecord(agent=agent)
        self.calls.append(record)
        return record


def scrub_secrets(text: str) -> str:
    """Remove the API key from an error message before it can reach a log or a note."""
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        key = os.environ.get(name)
        if key:
            text = text.replace(key, "[redacted]")
    return text


def short_error(text: str) -> str:
    """An error message that is safe to store: scrubbed first, so a key cut by the
    truncation cannot survive as a fragment, then cut to a fixed length."""
    return scrub_secrets(text)[:ERROR_TEXT_LIMIT]


class BudgetedModel(BaseLlm):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: BaseLlm
    budget: CallBudget
    agent_name: str
    max_calls: int
    calls_made: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        # The agent's own limit is checked before the shared one, so a runaway
        # specialist is reported as that, not as an empty budget.
        if self.calls_made >= self.max_calls:
            raise StepLimitExceeded(f"{self.agent_name}: {self.max_calls} model calls")
        record = self.budget.reserve(self.agent_name)
        self.calls_made += 1
        started = time.monotonic()
        try:
            async for response in self.inner.generate_content_async(llm_request, stream=False):
                usage = response.usage_metadata
                if usage is not None:
                    record.input_tokens = usage.prompt_token_count or 0
                    record.output_tokens = usage.candidates_token_count or 0
                yield response
        except (*API_STATUS_ERRORS, anthropic.APIError, httpx.HTTPError, TimeoutError) as exc:
            record.error = short_error(f"{type(exc).__name__}: {exc}")
            if is_outage(exc):
                raise ProviderUnavailable(record.error) from None
            raise ModelFailure(record.error) from None
        finally:
            record.seconds = time.monotonic() - started


class _HandledErrorFilter(logging.Filter):
    """Drops an ADK log record only when it carries an exception this module
    raises. Records from any other logger, ours included, always pass."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("google_adk"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        return not isinstance(exc, (RunLimit, ModelFailure))


_HANDLED = _HandledErrorFilter()


def quiet_handled_errors() -> None:
    """ADK logs a full traceback for any exception that leaves a model call, then
    the orchestrator turns it into a handoff. The traceback is noise for the
    errors the wrapper raises on purpose; every other error, and every message
    without an exception, still logs. The filter sits on the handlers, because a
    logger's filter does not see records from its child loggers and ADK creates
    some of those lazily."""
    for handler in (*logging.getLogger().handlers, logging.lastResort):
        if handler is not None and _HANDLED not in handler.filters:
            handler.addFilter(_HANDLED)
