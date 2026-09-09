"""
LLM transport for the ATS engine.

Dual-provider architecture:
1. Primary provider: Google Gemini via OpenAI-compatible endpoint.
2. Fallback provider: Groq via OpenAI-compatible endpoint.

First attempts Gemini models (e.g. gemini-3.6-flash, gemini-flash-latest, gemini-3.5-flash-lite).
If Gemini hits rate limits (429 / quota exceeded / resource exhausted) or errors,
it automatically falls back to Groq (llama-3.3-70b-versatile, llama-3.1-8b-instant, etc.)
to complete the task seamlessly.
"""

import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional, List, Tuple, Any

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

logger = logging.getLogger("ats-llm")

# ---------------------------------------------------------------------------
# Provider Defaults & Fallback Models
# ---------------------------------------------------------------------------

# Google Gemini (Primary)
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_FALLBACK_MODELS = [
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

# Groq (Fallback)
DEFAULT_GROQ_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
DEFAULT_GROQ_MODEL = os.environ.get("LLM_MODEL", "groq/compound")
GROQ_FALLBACK_MODELS = [
    "groq/compound",
    "groq/compound-mini",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
]

    # Non-chat markers for model discovery filtering
_NON_CHAT_MARKERS = ("whisper", "guard", "embed", "tts", "audio", "vision")
_MODEL_CACHE_TTL_SECONDS = 900
_MAX_MODEL_ATTEMPTS = 4

# The optimizer's response schema is a full structured resume (contact, summary, skills,
# every experience bullet, education, certifications) plus audit metadata — 2000 tokens
# truncates that mid-object on anything but a short resume, which is what was producing
# broken/garbage output. 8000 gives real resumes room without unbounded cost.
_MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "8000"))


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
    """Raised when no model or provider could serve the request."""


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "429",
            "rate_limit",
            "quota",
            "resource_exhausted",
            "too many requests",
            "limit exceeded",
            "overloaded",
        )
    )


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("401", "403", "invalid api key", "authentication"))


def _is_missing_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("404", "does not exist", "model_not_found", "decommissioned", "no longer available"))


class BackendLLMClient:
    """
    Multi-provider LLM client with Gemini primary and Groq fallback.

    - First tries Gemini models if GEMINI_API_KEY is configured.
    - If Gemini hits quota, rate limits (429), or failures, automatically
      falls back to Groq models if GROQ_API_KEY is configured.
    - Preserves model discovery, caching, and bounded deadlines.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 65.0,
        total_deadline: float = 115.0,
        base_url: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        groq_model: Optional[str] = None,
        **kwargs,
    ):
        self.timeout = timeout
        self.total_deadline = total_deadline

        # Environment or explicit keys
        if gemini_api_key is not None:
            self.gemini_api_key = gemini_api_key.strip()
        else:
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()

        if groq_api_key is not None:
            self.groq_api_key = groq_api_key.strip()
        else:
            self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()

        # Handle legacy single `api_key` param
        self._legacy_api_key = (api_key or "").strip()
        if self._legacy_api_key:
            # Detect key type if not already populated
            if not self.gemini_api_key and (self._legacy_api_key.startswith("AIza") or self._legacy_api_key.startswith("AQ.")):
                self.gemini_api_key = self._legacy_api_key
            elif not self.groq_api_key:
                self.groq_api_key = self._legacy_api_key

        self.gemini_base_url = GEMINI_BASE_URL
        self.gemini_model = gemini_model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

        self.groq_base_url = base_url or DEFAULT_GROQ_BASE_URL
        self.groq_model = model or os.environ.get("LLM_MODEL", DEFAULT_GROQ_MODEL)

        # Clients
        self.gemini_client = None
        if self.gemini_api_key and OpenAI:
            self.gemini_client = OpenAI(
                base_url=self.gemini_base_url,
                api_key=self.gemini_api_key,
                timeout=self.timeout,
            )

        self.groq_client = None
        if self.groq_api_key and OpenAI:
            self.groq_client = OpenAI(
                base_url=self.groq_base_url,
                api_key=self.groq_api_key,
                timeout=self.timeout,
            )

        # Last successful provider and model used
        self.last_provider: Optional[str] = None
        self.last_model: Optional[str] = None

    @property
    def api_key(self) -> str:
        """Returns the primary active key or fallback key, for backward compatibility."""
        return self.gemini_api_key or self.groq_api_key or self._legacy_api_key or ""

    @property
    def model(self) -> str:
        """Returns the current or last used model."""
        return self.last_model or (self.gemini_model if self.gemini_api_key else self.groq_model)

    @model.setter
    def model(self, value: str) -> None:
        self.last_model = value

    @property
    def provider_summary(self) -> str:
        """Returns provider and model, e.g. 'gemini:gemini-3.6-flash' or 'groq:llama-3.3-70b-versatile'."""
        if self.last_provider and self.last_model:
            return f"{self.last_provider}:{self.last_model}"
        return self.model

    def _get_account_models(self, client: Any, api_key: str) -> List[str]:
        """Discovers models reachable by a given client, cached for 15 minutes."""
        if not client or not api_key:
            return []
        cache_key = api_key[-12:] or "anonymous"
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            response = client.models.list()
            models = [
                m.id.replace("models/", "")
                for m in response.data
                if not any(marker in m.id.lower() for marker in _NON_CHAT_MARKERS)
            ]
        except Exception:
            return []

        _MODEL_CACHE.set(cache_key, models)
        return models

    def _candidate_gemini_models(self) -> List[str]:
        candidates: List[str] = []
        if self.gemini_model:
            candidates.append(self.gemini_model)
        for m in GEMINI_FALLBACK_MODELS:
            if m not in candidates:
                candidates.append(m)
        return candidates[:_MAX_MODEL_ATTEMPTS]

    def _candidate_groq_models(self) -> List[str]:
        candidates: List[str] = []
        if self.groq_model:
            candidates.append(self.groq_model)
        for m in GROQ_FALLBACK_MODELS:
            if m not in candidates:
                candidates.append(m)

        available = self._get_account_models(self.groq_client, self.groq_api_key)
        for m in available:
            if m not in candidates and any(k in m.lower() for k in ("llama", "gemma", "mixtral", "qwen")):
                candidates.append(m)

        return candidates[:_MAX_MODEL_ATTEMPTS]

    def _try_provider(
        self,
        provider_name: str,
        client: Any,
        candidate_models: List[str],
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        started: float,
    ) -> str:
        """Runs chat completion against candidate models of a given provider."""
        last_error: Optional[Exception] = None

        for model_id in candidate_models:
            remaining = self.total_deadline - (time.monotonic() - started)
            if remaining <= 1.0:
                break

            try:
                response = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=_MAX_OUTPUT_TOKENS,
                    timeout=min(self.timeout, remaining),
                )
                content = response.choices[0].message.content or ""
                self.last_provider = provider_name
                self.last_model = model_id
                return content
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Provider %s model %s attempt failed: %s",
                    provider_name,
                    model_id,
                    exc,
                )
                if _is_auth_error(exc):
                    # A bad/expired key fails identically on every model this provider
                    # offers — stop burning attempts and let the caller fail over to the
                    # other provider (or raise) immediately.
                    break
                if _is_missing_model_error(exc):
                    _MODEL_CACHE.clear()
                continue

        raise RuntimeError(f"{provider_name} failed across candidate models: {last_error}") from last_error

    def call_chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """
        Run one chat completion:
        1. First tries Gemini models if GEMINI_API_KEY is available.
        2. If Gemini hits rate limits (429), quota limits, or errors, falls back to Groq.
        3. If Gemini is not configured, directly uses Groq.
        4. If both fail or no key is configured, raises LLMUnavailable.
        """
        if not self.gemini_client and not self.groq_client:
            raise LLMUnavailable("No Gemini or Groq API key configured.")

        started = time.monotonic()
        gemini_error: Optional[Exception] = None

        # 1. Primary: Gemini
        if self.gemini_client:
            try:
                return self._try_provider(
                    provider_name="gemini",
                    client=self.gemini_client,
                    candidate_models=self._candidate_gemini_models(),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    started=started,
                )
            except Exception as exc:
                gemini_error = exc
                is_rate_limit = _is_rate_limit_error(exc)
                logger.warning(
                    "Gemini API %s (%s). Falling back to Groq API...",
                    "rate limit/quota exceeded" if is_rate_limit else "error",
                    exc,
                )

        # 2. Fallback: Groq
        if self.groq_client:
            try:
                return self._try_provider(
                    provider_name="groq",
                    client=self.groq_client,
                    candidate_models=self._candidate_groq_models(),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    started=started,
                )
            except Exception as groq_exc:
                err_msg = f"All provider attempts failed. Gemini error: {gemini_error}; Groq error: {groq_exc}"
                logger.error(err_msg)
                raise LLMUnavailable(err_msg) from groq_exc

        raise LLMUnavailable(
            f"Gemini failed and no Groq fallback API key configured. Last error: {gemini_error}"
        )

    def describe(self) -> Tuple[str, str]:
        """(provider_endpoint, model) — useful for logs and health output."""
        if self.last_provider == "gemini":
            return self.gemini_base_url, self.last_model or self.gemini_model
        return self.groq_base_url, self.last_model or self.groq_model


UnifiedLLMClient = BackendLLMClient
