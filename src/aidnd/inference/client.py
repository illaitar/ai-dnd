"""Client to model server (Ollama HTTP API + OpenAI-compatible clouds).

PROJECT RULE: no offline fallbacks. No model / network down → LLMUnavailable
(after retries), and the error honestly reaches the player. Stubs (Stub*)
allowed ONLY in tests — runtime never builds them.

Key functions
-------------
OllamaClient : HTTP client to Ollama/OpenAI-compatible backends with
  streaming, tools, and structured output (fmt).
ModelManager : Route LLM calls by role (intent/narrator/etc) to
  backends; enforces no offline fallbacks (LLMUnavailable on failure).
OllamaClient.chat_stream(..., on_token, think, tools, fmt) -> dict :
  Stream model response, calling on_token() per token piece.
OllamaClient.chat(...) -> dict : Non-streaming wrapper that collects
  full response (calls chat_stream with no-op callback).
ModelManager.call(role, messages, schema, ...) -> dict : Unified
  entry point — routes by role, retries 3x, raises LLMUnavailable.
ModelManager.available() -> bool : Health check for active backends;
  runtime never branches on this (call() raises if unavailable).
LLMUnavailable : Exception raised after retries; caught at server
  boundary and returned to player as honest error (no fallback).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from time import perf_counter as _perf_counter

from .. import config

try:
    import httpx
    _HAS_HTTPX = True
except ModuleNotFoundError:         # no httpx → any call() fails with LLMUnavailable
    httpx = None                    # type: ignore
    _HAS_HTTPX = False


class OllamaError(Exception):
    """Any problem communicating with Ollama server (or httpx not installed)."""


class LLMUnavailable(Exception):
    """Model unavailable (no backend/network/httpx) — after all retries. Caught at server
    boundary and returned to player as honest error, NOT substituted with stub."""


class LLMBadOutput(Exception):
    """Model responded but answer unparseable (invalid JSON/empty) — after retries.
    Also honest error: fake content not substituted for answer."""


class OllamaClient:
    def __init__(self, host: str | None = None, timeout: float | None = None,
                 keep_alive: str | None = None) -> None:
        self.host = (host or config.OLLAMA_HOST).rstrip("/")
        self._timeout = timeout or config.HTTP_TIMEOUT
        self.keep_alive = keep_alive or config.KEEP_ALIVE

    def preload(self, model: str) -> float:
        """Preload model into VRAM. Returns load time (sec)."""
        import time
        t0 = time.monotonic()
        try:
            resp = httpx.post(
                f"{self.host}/api/generate",
                json={"model": model, "keep_alive": self.keep_alive},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(str(exc)) from exc
        return time.monotonic() - t0

    def list_models(self) -> list[str]:
        """List of installed models (GET /api/tags)."""
        try:
            resp = httpx.get(f"{self.host}/api/tags", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(str(exc)) from exc
        return [m["name"] for m in data.get("models", [])]

    def chat_stream(
        self, model: str, messages: list[dict], on_token: Callable[[str], None],
        think: bool = False, on_think: Callable[[str], None] | None = None,
        tools: list[dict] | None = None, fmt: dict | None = None,
        options: dict | None = None,
    ) -> dict:
        """Stream model response; calls on_token(piece).

        Returns {"content": str, "tool_calls": list}. If think=True, thinking tokens
        go to on_think. tools — native function-calls. fmt — JSON
        Schema for structured output (grammar-constrained decoding Ollama,
        like guided_json/XGrammar, main §6.3): guarantees valid JSON and enum.
        """
        payload: dict = {
            "model": model, "messages": messages, "stream": True,
            "keep_alive": self.keep_alive, "think": think,
        }
        if tools:
            payload["tools"] = tools
        if fmt:
            payload["format"] = fmt
        if options:
            payload["options"] = options    # e.g. {"temperature": 0} for classification
        full: list[str] = []
        tool_calls: list[dict] = []
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream("POST", f"{self.host}/api/chat", json=payload) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise OllamaError(chunk["error"])
                        msg = chunk.get("message", {})
                        thinking = msg.get("thinking")
                        if thinking and on_think:
                            on_think(thinking)
                        for tc in msg.get("tool_calls") or []:
                            tool_calls.append(tc)
                        piece = msg.get("content", "")
                        if piece:
                            full.append(piece)
                            on_token(piece)
                        if chunk.get("done"):
                            break
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(str(exc)) from exc
        return {"content": "".join(full), "tool_calls": tool_calls}

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None,
             think: bool = False, fmt: dict | None = None, options: dict | None = None) -> dict:
        """Non-streaming wrapper: collects full response."""
        return self.chat_stream(model, messages, on_token=lambda _p: None,
                                think=think, tools=tools, fmt=fmt, options=options)


class ModelManager:
    """Router LLM calls by role: profile → (backend, model) → chat.

    available() — health checks only (doctor/debug-stands); runtime does NOT branch
    on availability: call() either returns answer or raises LLMUnavailable.
    """

    # role -> (model, optional LoRA adapter) — main §12
    ROLE_MODELS = {
        "intent": (config.BASE_MODEL, None),    # legacy verb-classifier (offline path)
        "router": (config.ROUTER_MODEL, "router"),  # fine-tuned intent router (see training/)
        "arbiter": (config.ARBITER_MODEL, "arbiter"),  # fine-tuned freeform arbiter (decide_resolution)
        "consequence": (config.CONSEQUENCE_MODEL, "consequence"),  # fine-tuned consequence agent
        "narrator": (config.NARRATOR_MODEL, "narrator-persona"),  # fine-tuned narrator (see training/)
        "location_writer": (config.LOCATION_MODEL, "location"),  # separate adapter for location descriptions on 14B (aidnd-location)
        "cognition": (config.BASE_MODEL, "lore"),
        "lore_keeper": (config.BASE_MODEL, "lore"),
        "character_gen": (config.BASE_MODEL, "lore"),
        "persona_gen": (config.BASE_MODEL, "lore"),  # rich persona generator (datasets/persona)
        "tactician": (config.BASE_MODEL, "combat"),
        "reflection": (config.BASE_MODEL, "reflect"),
        "director": (config.BASE_MODEL, None),
        "quest_writer": (config.QUEST_MODEL, "quest"),   # fine-tuned model (see training/)
        "plausibility": (config.BASE_MODEL, "validator"),
        "merchant": (config.BASE_MODEL, "lore"),         # merchant: social outcome of trade (numbers — engine)
        "street_event": (config.BASE_MODEL, "lore"),     # random street event en route (content)
        "event_batch": (config.BASE_MODEL, "lore"),      # pre-generation of event pool in batches (content)
        "quest_merge": (config.BASE_MODEL, "lore"),       # judge for merging similar announcements
        "event_quest": (config.BASE_MODEL, "lore"),       # street scene → hook-announcement
        "map_features": (config.BASE_MODEL, "lore"),      # location description → battle map features
        "faction_gen": (config.BASE_MODEL, "lore"),
        "npc_ref": (config.INTENT_MODEL, None),           # light resolution of present NPC reference
        "agenda": (config.BASE_MODEL, "lore"),            # secret intent/plan of important active NPC
    }

    def __init__(self, client: OllamaClient | None = None) -> None:
        from . import profiles
        self.routing = profiles.routing_for(config.LLM_PROFILE, self.ROLE_MODELS)  # role→(backend,model)
        self.backends = profiles.make_backends(self.routing, client)
        ob = self.backends.get("ollama")
        self.client = ob.client if ob else None          # compat (tests/stream may pull)
        self._available: bool | None = None
        self._trace: list[dict] = []        # debug-trace routing: which roles→models were called per turn
        self.on_call = None                 # callback(role, model) on each LLM call (for generation slider)

    def available(self, recheck: bool = False) -> bool:
        """Is any backend of the active profile available (cached)? ONLY for
        health checks — runtime does not branch on this flag (call() raises LLMUnavailable).
        IMPORTANT: check all backends (no short-circuit) — otherwise Ollama won't populate model list."""
        if not _HAS_HTTPX or not self.backends:
            return False
        if self._available is None or recheck:
            self._available = any([b.available() for b in self.backends.values()])
        return self._available

    def _route(self, role: str):
        backend_name, model = self.routing.get(role) or self.routing["default"]
        backend = self.backends.get(backend_name)
        return backend, (backend.resolve(model) if backend else model)

    def model_for(self, role: str) -> str:
        """Model name for role in active profile (compat-helper; trace/on_call — in call())."""
        return self._route(role)[1]

    def backend_name(self, role: str) -> str | None:
        """Backend name for role in active profile (for selecting backend-specific prompt)."""
        b = self._route(role)[0]
        return b.name if b else None

    def enrich_concurrency(self) -> int:
        """How many enrich gen-calls to run in parallel. Cloud (network-bound) — parallelize;
        local Ollama (model swap on 1 GPU) — sequential. Take min across backends
        of key gen-roles (to not bottleneck local path)."""
        roles = ("persona_gen", "location_writer", "faction_gen", "item_smith")
        caps = [getattr(b, "parallel_enrich", 1)
                for b in (self._route(r)[0] for r in roles) if b is not None]
        return max(1, min(caps)) if caps else 1

    RETRIES = 3          # retries for transport error (network/5xx/timeout), pause 0.5·n sec

    def call(self, role: str, messages: list, *, schema=None, options=None,
             on_token=None, think: bool = False) -> dict:
        """UNIFIED entry point for model call by role: profile → (backend, model) → backend.chat.
        Returns {'content', 'tool_calls'}. Transport error → retries → LLMUnavailable
        (no None-with-fallback: without model engine breaks honestly)."""
        if not _HAS_HTTPX:
            raise LLMUnavailable("httpx не установлен — LLM-бэкенды недоступны")
        backend, model = self._route(role)
        if backend is None:
            raise LLMUnavailable(f"роль «{role}»: нет бэкенда в профиле {config.LLM_PROFILE}")
        self._trace.append({"role": role, "model": model, "t": _perf_counter()})
        if len(self._trace) > 200:
            self._trace = self._trace[-100:]
        if self.on_call is not None:                     # user limit tick — one per logical call
            try:
                self.on_call(role, model)
            except Exception:
                pass
        last: Exception | None = None
        for attempt in range(self.RETRIES):
            try:
                return backend.chat(model, messages, schema=schema, options=options,
                                     on_token=on_token, think=think)
            except Exception as exc:                     # network/server/timeout → retry
                last = exc
                if attempt + 1 < self.RETRIES:
                    time.sleep(0.5 * (attempt + 1))
        raise LLMUnavailable(f"{role} → {model}: {last}") from last

    def trace_take(self) -> list[dict]:
        """Extract accumulated routing trace (role→model + approx. duration ms) and clear.
        Step duration ≈ interval until next model_for call (for debug "where did input go")."""
        tr, self._trace = self._trace, []
        now = _perf_counter()
        out = []
        for i, e in enumerate(tr):
            end = tr[i + 1]["t"] if i + 1 < len(tr) else now
            out.append({"role": e["role"], "model": e["model"], "ms": round((end - e["t"]) * 1000)})
        return out[-40:]
