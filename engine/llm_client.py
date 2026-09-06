"""
LLM transport for the ATS engine.

Talks to any OpenAI-compatible chat endpoint; defaults to Groq. Discovers which models
the API key can actually reach so a retired model id cannot break the service, caches
that discovery, and bounds the whole attempt sequence with a wall-clock deadline.
"""

import os
import time
import threading
from pathlib import Path
from typing import Optional, List, Tuple

# Load .env from the repository root (this module lives in engine/).
try:
    from dotenv import load_dotenv

    _ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
    if _ENV_FILE.exists():
        load_dotenv(dotenv_path=_ENV_FILE, override=False)
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# Tried in order when model discovery is unavailable.
GROQ_FALLBACK_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma2-9b-it",
]

DEFAULT_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")

# Model ids that are not chat completions endpoints.
_NON_CHAT_MARKERS = ("whisper", "guard", "embed", "tts", "audio", "vision")

# How long a discovered model list stays fresh, and how many models one request may try.
_MODEL_CACHE_TTL_SECONDS = 900
_MAX_MODEL_ATTEMPTS = 4


class _ModelCache:
    """Process-wide cache of the model ids reachable by a given API key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict = {}

    def get(self, key: str) -> Optional[List[str]]:
        with self._lock:
            entry = self._entries.get(key)
        if not entry:
            return None
        models, fetched_at = entry
        if time.monotonic() - fetched_at > _MODEL_CACHE_TTL_SECONDS:
            return None
        return models

    def set(self, key: str, models: List[str]) -> None:
        with self._lock:
            self._entries[key] = (models, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_MODEL_CACHE = _ModelCache()


class LLMUnavailable(RuntimeError):
    """Raised when no model could serve the request."""


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("401", "403", "invalid api key", "authentication"))


def _is_missing_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("404", "does not exist", "model_not_found", "decommissioned"))


class BackendLLMClient:
    """
    Chat client with model discovery, caching and a bounded retry budget.

    `timeout` is the per-request timeout; `total_deadline` caps the whole call_chat
    attempt sequence so a series of slow failures cannot stall an HTTP handler.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        total_deadline: float = 75.0,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        self.api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url or DEFAULT_BASE_URL
        self.timeout = timeout
        self.total_deadline = total_deadline

        if self.api_key and OpenAI:
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
        else:
            self.client = None

    def get_account_models(self, refresh: bool = False) -> List[str]:
        """
        Model ids this key can reach, newest discovery cached for 15 minutes.

        Returns an empty list if discovery fails; callers fall back to the static pool.
        """
        if not self.client:
            return []

        cache_key = self.api_key[-12:] or "anonymous"
        if not refresh:
            cached = _MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached

        try:
            response = self.client.models.list()
            models = [
                m.id for m in response.data
                if not any(marker in m.id.lower() for marker in _NON_CHAT_MARKERS)
            ]
        except Exception:
            return []

        _MODEL_CACHE.set(cache_key, models)
        return models

    def _candidate_models(self) -> List[str]:
        """Preferred model first, then whatever discovery found, then the static pool."""
        available = self.get_account_models()
        candidates: List[str] = []

        if self.model and (not available or self.model in available):
            candidates.append(self.model)
        for m in available:
            if m not in candidates:
                candidates.append(m)
        for m in GROQ_FALLBACK_MODELS:
            if m not in candidates:
                candidates.append(m)

        return candidates[:_MAX_MODEL_ATTEMPTS]

    def call_chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """
        Run one chat completion, trying candidate models until one answers.

        Stops immediately on an authentication error (no other model will fare better)
        and gives up once `total_deadline` has elapsed.

        Raises LLMUnavailable if every attempt failed.
        """
        if not self.client or not self.api_key:
            raise LLMUnavailable("No API key configured.")

        started = time.monotonic()
        last_error: Optional[Exception] = None

        for model_id in self._candidate_models():
            remaining = self.total_deadline - (time.monotonic() - started)
            if remaining <= 1.0:
                break

            try:
                response = self.client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=2500,
                    timeout=min(self.timeout, remaining),
                )
            except Exception as exc:  # noqa: BLE001 - retried across models, reported below
                last_error = exc
                if _is_auth_error(exc):
                    raise LLMUnavailable(f"Authentication failed for the configured API key: {exc}") from exc
                if _is_missing_model_error(exc):
                    # Discovery is stale; drop it so the next request re-queries.
                    _MODEL_CACHE.clear()
                continue

            self.model = model_id  # remember what worked
            return response.choices[0].message.content or ""

        raise LLMUnavailable(f"All model attempts failed. Last error: {last_error}")

    def describe(self) -> Tuple[str, str]:
        """(base_url, model) — useful for logs and health output."""
        return self.base_url, self.model


UnifiedLLMClient = BackendLLMClient
