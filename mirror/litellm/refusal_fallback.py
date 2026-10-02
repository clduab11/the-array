"""the-array — fall back on refusals in STREAMED chat completions (LiteLLM v1.100.1).

Non-streamed refusals are already handled by LiteLLM: when a response ends with
finish_reason "content_filter", Router._acompletion raises ContentPolicyViolationError,
but only when `content_policy_fallbacks` has an entry for the requested model group.

Streamed responses get no such check, so a refusal (Anthropic stop_reason "refusal"
maps to finish_reason "content_filter") reaches the client as an empty stream. This
module adds the same check to the stream: if a stream ends with content_filter before
producing any text or tool call, it raises MidStreamFallbackError, which the Router's
own streaming wrapper (stream_with_fallbacks) catches and walks the group's fallback
chain. It acts only for model groups that have a `content_policy_fallbacks` entry, so
one config key opts a group in for both paths.

Loaded via litellm_settings.callbacks; the patch is applied at import.
"""
from litellm._logging import verbose_proxy_logger
from litellm.exceptions import MidStreamFallbackError
from litellm.integrations.custom_logger import CustomLogger
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

_ORIGINAL_ANEXT = CustomStreamWrapper.__anext__


def _model_group(stream: CustomStreamWrapper) -> str | None:
    details = getattr(getattr(stream, "logging_obj", None), "model_call_details", None) or {}
    params = details.get("litellm_params") or {}
    for meta in (params.get("metadata"), params.get("litellm_metadata"), details.get("metadata")):
        if isinstance(meta, dict) and meta.get("model_group"):
            return str(meta["model_group"])
    return None


def _has_content_policy_fallback(group: str | None) -> bool:
    if not group:
        return False
    try:
        from litellm.proxy.proxy_server import llm_router
    except Exception:  # noqa: BLE001 — outside the proxy there is no router to fall back through
        return False
    chains = getattr(llm_router, "content_policy_fallbacks", None) or []
    return any(isinstance(chain, dict) and chain.get(group) for chain in chains)


def _produced_output(stream: CustomStreamWrapper) -> bool:
    if (stream.response_uptil_now or "").strip():
        return True
    for chunk in getattr(stream, "chunks", None) or []:
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "tool_calls", None):
                return True
    return False


async def _drain(stream: CustomStreamWrapper) -> None:
    """Pull the refused stream to its end so LiteLLM's end-of-stream logging records the refused call's cost."""
    try:
        for _ in range(64):  # a refused stream has at most a usage chunk left
            await _ORIGINAL_ANEXT(stream)
    except StopAsyncIteration:
        pass
    except Exception as exc:  # noqa: BLE001 — logging the refused call must never block the fallback
        verbose_proxy_logger.debug("refusal_fallback: drain stopped early: %s", exc)


async def _anext_with_refusal_fallback(self: CustomStreamWrapper):
    chunk = await _ORIGINAL_ANEXT(self)
    finish = self.received_finish_reason
    if finish is None:
        choices = getattr(chunk, "choices", None) or []
        finish = getattr(choices[0], "finish_reason", None) if choices else None
    if finish == "content_filter" and not _produced_output(self):
        group = _model_group(self)
        if _has_content_policy_fallback(group):
            await _drain(self)
            verbose_proxy_logger.warning(
                "refusal_fallback: stream refused before any output (model_group=%s, model=%s); falling back",
                group,
                self.model,
            )
            raise MidStreamFallbackError(
                message=f"Refusal before any output (finish_reason=content_filter) on model group {group}",
                model=self.model,
                llm_provider=self.custom_llm_provider or "",
                generated_content="",
                is_pre_first_chunk=True,
            )
    return chunk


CustomStreamWrapper.__anext__ = _anext_with_refusal_fallback


class RefusalFallback(CustomLogger):
    """No-op callback; registering it in litellm_settings.callbacks imports this module at boot."""


proxy_handler_instance = RefusalFallback()
