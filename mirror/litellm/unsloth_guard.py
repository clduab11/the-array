"""the-array — G-SEC strip for Unsloth-backed deployments (LiteLLM v1.100.1; OP UNSLOTH CHARLIE C-0, plan §6.7 item 1).

Unsloth's OpenAI-compatible API accepts about 29 non-standard request fields. With the key, `enable_tools: true` ran
server-side Python as the Windows user (ALPHA p12), and LiteLLM forwards 28 of the 29 to an `openai/` upstream inside
`extra_body` (ALPHA p17), including the `provider_*` fields that make Unsloth call an external provider (egress that
never passes through LiteLLM).

This hook runs once per deployment attempt: `litellm.utils.async_pre_call_deployment_hook`, called from the core async
wrapper after the router has picked a deployment. A fallback that lands on an Unsloth route is therefore covered, not
only a direct request. For a deployment whose api_base is the Unsloth host it:
  - keeps only OpenAI chat-completion params, LiteLLM's own kwargs and `chat_template_kwargs`;
  - rebuilds extra_body as {chat_template_kwargs (if sent), enable_tools: False};
  - drops X-Unsloth-* request headers;
  - refuses every non-chat call type (no embeddings, audio, image, rerank, file or batch traffic reaches :8888).
Stripped field NAMES (never values) are logged as `unsloth_guard` warnings.

Loaded via litellm_settings.callbacks as `unsloth_guard.guard_instance`; mounted at /app/unsloth_guard.py.
"""
import os
from typing import Any
from urllib.parse import urlparse

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_logger import CustomLogger

try:  # LiteLLM's own registries: its internal kwargs and the OpenAI chat params it knows how to map.
    from litellm.types.utils import all_litellm_params as _LITELLM_PARAMS
except Exception:  # noqa: BLE001 — a missing registry must fail closed (strip more), never open
    _LITELLM_PARAMS = []
try:
    from litellm import OPENAI_CHAT_COMPLETION_PARAMS as _OPENAI_PARAMS
except Exception:  # noqa: BLE001
    _OPENAI_PARAMS = []

# The 29 Unsloth request fields ALPHA saw forwarded (p17), minus chat_template_kwargs, denied even if a LiteLLM
# registry ever grows a same-named entry.
UNSLOTH_FIELDS = frozenset({
    "anthropic_code_exec_container_id", "bypass_permissions", "compaction_headroom_ratio", "compaction_threshold",
    "confirm_tool_calls", "context_overflow", "context_policy", "deep_research_armed", "disable_sandbox", "enable_tools",
    "enabled_tools", "encrypted_api_key", "external_model", "fast_mode", "max_tool_calls_per_message", "mcp_enabled",
    "openai_code_exec_container_id", "permission_mode", "prompt_cache_ttl", "provider_base_url", "provider_id",
    "provider_type", "rag_scope", "run_tools_locally", "session_id", "studio_tool_history", "thread_id",
    "tool_call_timeout", "enable_prompt_caching",
})
# Standard OpenAI fields that only mean something to a server that runs tools itself; a local model needs neither.
SERVER_TOOL_PARAMS = frozenset({"web_search_options", "include_server_side_tool_invocations"})
KEEP_TOP_LEVEL = frozenset({"model", "messages", "chat_template_kwargs", "extra_body", "headers"})
ALLOWED_TOP_LEVEL = (frozenset(_LITELLM_PARAMS) | frozenset(_OPENAI_PARAMS) | KEEP_TOP_LEVEL) - UNSLOTH_FIELDS - SERVER_TOOL_PARAMS
CHAT_CALL_TYPES = frozenset({
    "completion", "acompletion", "text_completion", "atext_completion",
    "anthropic_messages", "aanthropic_messages", "responses", "aresponses",
})
HEADER_KEYS = ("extra_headers", "headers", "default_headers")


def _unsloth_netlocs() -> set[str]:
    locs = set()
    configured = os.environ.get("UNSLOTH_PC_URL", "").strip()
    if configured:
        locs.add(urlparse(configured).netloc.lower())
    # Belt and braces: the Desktop's fixed port on the addresses a container or the host can use.
    locs.update({"host.docker.internal:8888", "127.0.0.1:8888", "localhost:8888"})
    return locs


def _is_unsloth(kwargs: dict[str, Any]) -> bool:
    bases = [kwargs.get("api_base"), kwargs.get("base_url")]
    lp = kwargs.get("litellm_params")
    if isinstance(lp, dict):
        bases.append(lp.get("api_base"))
    netlocs = _unsloth_netlocs()
    return any(isinstance(b, str) and urlparse(b).netloc.lower() in netlocs for b in bases)


class UnslothGuard(CustomLogger):
    async def async_pre_call_deployment_hook(self, kwargs: dict[str, Any], call_type: Any) -> dict | None:
        if not _is_unsloth(kwargs):
            return None
        ct = getattr(call_type, "value", call_type)
        if ct is not None and str(ct) not in CHAT_CALL_TYPES:
            verbose_proxy_logger.warning("unsloth_guard: refused call_type=%s for an Unsloth deployment", ct)
            raise ValueError(f"unsloth_guard: call type {ct!r} is not allowed on an Unsloth deployment")

        out = dict(kwargs)
        dropped = sorted(k for k in out if k not in ALLOWED_TOP_LEVEL)
        for k in dropped:
            out.pop(k, None)

        client_extra = out.get("extra_body") if isinstance(out.get("extra_body"), dict) else {}
        dropped_extra = sorted(k for k in client_extra if k != "chat_template_kwargs")
        extra: dict[str, Any] = {}
        if isinstance(client_extra.get("chat_template_kwargs"), dict):
            extra["chat_template_kwargs"] = client_extra["chat_template_kwargs"]
        extra["enable_tools"] = False
        out["extra_body"] = extra

        dropped_headers = []
        for hk in HEADER_KEYS:
            h = out.get(hk)
            if isinstance(h, dict):
                bad = [name for name in h if str(name).lower().startswith("x-unsloth-")]
                if bad:
                    out[hk] = {n: v for n, v in h.items() if n not in bad}
                    dropped_headers.extend(bad)

        if dropped or dropped_extra or dropped_headers:
            verbose_proxy_logger.warning(
                "unsloth_guard: model=%s stripped top=%s extra_body=%s headers=%s",
                out.get("model"), dropped, dropped_extra, sorted(dropped_headers),
            )
        return out


guard_instance = UnslothGuard()
