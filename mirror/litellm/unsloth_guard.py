"""the-array — G-SEC strip and GPU rule for Unsloth-backed deployments (LiteLLM v1.100.1; a change CHARLIE C-0, plan §6.7 item 1).

Unsloth's OpenAI-compatible API accepts about 29 non-standard request fields. With the key, `enable_tools: true` ran
server-side Python as the Windows user, and LiteLLM forwards 28 of the 29 to an `openai/` upstream inside
`extra_body`, including the `provider_*` fields that make Unsloth call an external provider (egress that
never passes through LiteLLM).

This hook runs once per deployment attempt: `litellm.utils.async_pre_call_deployment_hook`, called from the core async
wrapper after the router has picked a deployment. A fallback that lands on an Unsloth route is therefore covered, not
only a direct request. For a deployment whose api_base is the Unsloth host it:
  - keeps only OpenAI chat-completion params, LiteLLM's own kwargs and `chat_template_kwargs`;
  - rebuilds extra_body as {chat_template_kwargs (if sent), enable_tools: False};
  - drops X-Unsloth-* request headers;
  - refuses every non-chat call type, and any call type LiteLLM does not know (no embeddings, audio, image, rerank,
    file, batch or compaction traffic reaches :8888), with a 400 (litellm.BadRequestError). Until 2026-10-07 it raised a bare ValueError, which the proxy answered as HTTP 500 with
    LiteLLM's "bug in LiteLLM" banner and the router retried three times; a 400 is not retried and never cools a deployment.
Stripped field NAMES (never values) are logged as `unsloth_guard` warnings.

GPU rule, on the same hook:
  - While Unsloth is training (LLM or diffusion), every Unsloth deployment refuses with a 503. Unsloth's own chat-load guard
    returns early for a GGUF row in Manual GPU mode, which is every pinned row here, so without this a routed call could
    load beside a running trainer (studio/backend/routes/inference.py, source-read 2026-11-04).
  - While a Hub download runs, a call that would load a model refuses with a 503 (a load during a download took the backend
    down on the reference deployment). A call the resident model can serve still runs.
  - A file at CARD_HOLD_FILE inside the container closes local routes by hand; a container recreate clears it.
    Status is cached for CARD_TTL_S, so a call can still pass in the first seconds of a run. Set the hold first when that matters.
A 503 walks the caller's chain, every Unsloth rung refuses too, and the caller's own fallback takes the turn. The status read
fails OPEN: if Unsloth's status can't be read, calls go through. This rule protects a run; the G-SEC strip is the security
control and it still fails closed. Refusals count in praxen_unsloth_card_refusals_total{reason} and log as warnings.

Loaded via litellm_settings.callbacks as `unsloth_guard.guard_instance`; mounted at /app/unsloth_guard.py.
"""
import asyncio
import os
import re
import time
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
try:
    from litellm.exceptions import BadRequestError as _BadRequestError
except Exception:  # noqa: BLE001 — without it the refusal falls back to ValueError (still refused, as a 500)
    _BadRequestError = None
try:
    from litellm.exceptions import ServiceUnavailableError as _ServiceUnavailableError
except Exception:  # noqa: BLE001 — without it the GPU rule falls back to ValueError (a 500, which still walks the chain)
    _ServiceUnavailableError = None
try:
    import httpx
except Exception:  # noqa: BLE001 — without it the GPU rule reads nothing and stays open
    httpx = None
try:
    from prometheus_client import REGISTRY, Counter

    try:
        _M_CARD = Counter("praxen_unsloth_card_refusals_total", "Unsloth deployments refused by the GPU rule", ["reason"])
    except ValueError:  # already registered (module re-import)
        _M_CARD = REGISTRY._names_to_collectors["praxen_unsloth_card_refusals_total"]  # noqa: SLF001
except Exception:  # noqa: BLE001 — a missing meter never blocks a call
    _M_CARD = None

# The 29 Unsloth request fields seen forwarded, minus chat_template_kwargs, denied even if a LiteLLM
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

CARD_TTL_S = 3.0
CARD_HOLD_FILE = "/tmp/unsloth-card-hold"
# The phases /api/train/status reports while a run holds or is about to hold the card (routes/training.py _build_training_status).
TRAINING_PHASES = frozenset({"configuring", "loading_model", "training_drafter", "training", "finalizing"})


def _unsloth_netlocs() -> set[str]:
    locs = set()
    configured = os.environ.get("UNSLOTH_PC_URL", "").strip()
    if configured:
        locs.add(urlparse(configured).netloc.lower())
    # Belt and braces: the Desktop's fixed port on the addresses a container or the host can use.
    locs.update({"host.docker.internal:8888", "127.0.0.1:8888", "localhost:8888"})
    return locs


def _refusal(message: str, kwargs: dict[str, Any]) -> Exception:
    """The exception that blocks a call: a 400 when LiteLLM's BadRequestError can be built, else a ValueError. Either blocks."""
    if _BadRequestError is not None:
        try:
            return _BadRequestError(message=message, model=str(kwargs.get("model") or ""),
                                    llm_provider=str(kwargs.get("custom_llm_provider") or "openai"))
        except Exception:  # noqa: BLE001 — a changed constructor must not turn the refusal into a pass
            pass
    return ValueError(message)


def _unavailable(message: str, kwargs: dict[str, Any]) -> Exception:
    """The GPU rule's refusal: a 503, so the caller's fallback chain takes the call. Falls back to a ValueError."""
    if _ServiceUnavailableError is not None:
        try:
            return _ServiceUnavailableError(message=message, model=str(kwargs.get("model") or ""),
                                            llm_provider=str(kwargs.get("custom_llm_provider") or "openai"))
        except Exception:  # noqa: BLE001 — a changed constructor must not turn the refusal into a pass
            pass
    return ValueError(message)


def _is_unsloth(kwargs: dict[str, Any]) -> bool:
    bases = [kwargs.get("api_base"), kwargs.get("base_url")]
    lp = kwargs.get("litellm_params")
    if isinstance(lp, dict):
        bases.append(lp.get("api_base"))
    netlocs = _unsloth_netlocs()
    return any(isinstance(b, str) and urlparse(b).netloc.lower() in netlocs for b in bases)


class _CardState:
    """What Unsloth is doing with the card, read at most once per CARD_TTL_S. Never raises: a route it can't read counts as idle."""

    def __init__(self) -> None:
        self._at = 0.0
        self._val: tuple[str, bool, str] = ("", False, "")
        self._client: Any = None

    async def _fetch(self, path: str) -> dict[str, Any]:
        base = re.sub(r"/v1/?$", "", os.environ.get("UNSLOTH_PC_URL", "").strip().rstrip("/"))
        if not base or httpx is None:
            return {}
        key = os.environ.get("UNSLOTH_PC_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=1.0)
            response = await self._client.get(base + path, headers=headers)
            body = response.json() if response.status_code == 200 else {}
        except Exception:  # noqa: BLE001
            return {}
        return body if isinstance(body, dict) else {}

    async def get(self) -> tuple[str, bool, str]:
        """-> (training kind or "", a Hub download is running, the resident "repo:quantization" lower-cased or "")."""
        if time.monotonic() - self._at < CARD_TTL_S:
            return self._val
        llm, diffusion, hub, status = await asyncio.gather(
            self._fetch("/api/train/status"),
            self._fetch("/api/train/diffusion/status"),
            self._fetch("/api/hub/active-downloads"),
            self._fetch("/api/inference/status"),
        )
        training = ""
        if llm.get("is_training_running") or str(llm.get("phase") or "") in TRAINING_PHASES:
            training = "training"
        elif diffusion.get("active"):
            training = "diffusion_training"
        loaded, variant = status.get("loaded") or [], status.get("gguf_variant")
        resident = str(loaded[0]).lower() if loaded else ""
        if resident and variant:
            resident = f"{resident}:{str(variant).lower()}"
        self._val, self._at = (training, bool(hub.get("downloads")), resident), time.monotonic()
        return self._val


_CARD = _CardState()


def _is_resident(resident: str, names: list[str]) -> bool:
    """Whether a deployment's model is the file already loaded: the whole "repo:quantization", with any provider prefix.
    Another quantization is another file to load. If Unsloth reports no quantization, only a name without one can match."""
    return any(name == resident or name.endswith("/" + resident) for name in names)


async def _card_refusal(kwargs: dict[str, Any]) -> tuple[str, str] | None:
    """(reason, message) when the GPU rule closes this deployment, else None. Never raises: any fault here lets the call through."""
    try:
        if os.path.exists(CARD_HOLD_FILE):
            return "hold", "Local models are on hold by hand (the-array GPU rule)."
        training, downloading, resident = await _CARD.get()
        if training:
            return training, "Unsloth is training, so local models are closed until the run ends (the-array GPU rule)."
        if downloading:
            lp = kwargs.get("litellm_params")
            names = [str(n).lower() for n in (kwargs.get("model"), lp.get("model") if isinstance(lp, dict) else None) if n]
            if not resident or not _is_resident(resident, names):
                return "download", "An Unsloth Hub download is running, so no local model can load until it ends (the-array GPU rule)."
    except Exception:  # noqa: BLE001
        return None
    return None


class UnslothGuard(CustomLogger):
    async def async_pre_call_deployment_hook(self, kwargs: dict[str, Any], call_type: Any) -> dict | None:
        if not _is_unsloth(kwargs):
            return None
        ct = getattr(call_type, "value", call_type)
        # An unknown call type arrives as None (utils.async_pre_call_deployment_hook maps names missing from CallTypes, such
        # as acompact_responses, to None): refuse it too. Every chat path resolves to a CallTypes member (2026-10-07).
        if ct is None or str(ct) not in CHAT_CALL_TYPES:
            verbose_proxy_logger.warning("unsloth_guard: refused call_type=%s for an Unsloth deployment", ct)
            raise _refusal(f"unsloth_guard: call type {ct!r} is not allowed on an Unsloth deployment", kwargs)

        card = await _card_refusal(kwargs)
        if card is not None:
            reason, message = card
            verbose_proxy_logger.warning("unsloth_guard: GPU rule refused model=%s reason=%s", kwargs.get("model"), reason)
            if _M_CARD is not None:
                try:
                    _M_CARD.labels(reason).inc()
                except Exception:  # noqa: BLE001
                    pass
            raise _unavailable(message, kwargs)

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
