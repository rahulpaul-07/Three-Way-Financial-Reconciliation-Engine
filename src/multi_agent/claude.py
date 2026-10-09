"""Claude through ADK's own Anthropic class, minus the parameters it cannot send."""

from __future__ import annotations

from google.adk.models.anthropic_llm import AnthropicLlm

SAMPLING_FIELDS = ("temperature", "top_p", "top_k")


class ClaudeLlm(AnthropicLlm):
    """AnthropicLlm that never sends temperature, top_p or top_k.

    ADK forwards them whenever an agent's config sets one, and our agents set
    temperature=0 for the Gemini runs. The installed anthropic SDK's
    messages.create takes none of the three (current Claude models do not accept
    sampling parameters), so the call raised TypeError before any request was
    made. Dropping them here keeps the agents provider-neutral. The cost is that
    Claude runs are not pinned to temperature 0, which the README says.
    """

    async def generate_content_async(self, llm_request, stream: bool = False):
        config = llm_request.config
        if config is not None and any(getattr(config, f) is not None for f in SAMPLING_FIELDS):
            # A copy: the same request object is also shown to the budget wrapper.
            llm_request = llm_request.model_copy(update={
                "config": config.model_copy(update=dict.fromkeys(SAMPLING_FIELDS))})
        async for response in super().generate_content_async(llm_request, stream=stream):
            yield response
