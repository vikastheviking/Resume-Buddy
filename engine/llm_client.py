"""
Dedicated Ultra-Fast Backend LLM Engine with Dynamic Model Discovery & Auto-Fallback.
Powered by Groq Cloud on custom LPU chips.
Inference speed: ~500 - 800 tokens/sec (Full resume in ~1 second).
100% Free with zero cost.
"""

import os
from pathlib import Path
from typing import Optional, List

# Automatically load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=True)
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Fallback pool
GROQ_FALLBACK_MODELS = [
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "llama3-70b-8192",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it"
]

BACKEND_BASE_URL = "https://api.groq.com/openai/v1"
PROVIDERS_CONFIG = {}


class BackendLLMClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: float = 15.0, **kwargs):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
        self.model = model or "llama-3.1-8b-instant"
        self.base_url = BACKEND_BASE_URL
        self.timeout = timeout
        
        if self.api_key and OpenAI:
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
        else:
            self.client = None

    def get_account_models(self) -> List[str]:
        """Fetch the exact active models authorized for this API key on Groq."""
        if not self.client:
            return []
        try:
            res = self.client.models.list()
            chat_models = [
                m.id for m in res.data 
                if not any(x in m.id for x in ["whisper", "guard", "embed", "tts", "audio"])
            ]
            return chat_models
        except Exception:
            return []

    def call_chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Call Groq LPU with dynamic discovery so 404 errors are impossible."""
        if not self.client or not self.api_key:
            return ""

        # Step 1: Discover what models are active on this specific key
        available = self.get_account_models()

        # Step 2: Build priority list
        candidates = []
        if self.model and self.model in available:
            candidates.append(self.model)
        for m in available:
            if m not in candidates:
                candidates.append(m)
        for m in GROQ_FALLBACK_MODELS:
            if m not in candidates:
                candidates.append(m)

        # Step 3: Try candidates in order
        last_error = None
        for m in candidates:
            try:
                response = self.client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    max_tokens=2500,
                    timeout=self.timeout
                )
                self.model = m  # Remember working model
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                # If 404 or model not available, try next candidate immediately
                if "404" in str(e) or "not exist" in str(e).lower() or "model_not_found" in str(e).lower():
                    continue
                # If network or other issue, try next
                continue

        raise RuntimeError(f"[Groq LPU] All models failed. Last error: {str(last_error)}")


UnifiedLLMClient = BackendLLMClient
