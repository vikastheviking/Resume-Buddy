"""
Tests for dual-provider BackendLLMClient:
- Gemini primary
- Groq fallback on rate limit / quota exhaustion / errors
- Fallback behavior and error handling
"""

import pytest
from unittest.mock import MagicMock, patch
from engine.llm_client import BackendLLMClient, LLMUnavailable


class DummyChoice:
    def __init__(self, content):
        self.message = MagicMock(content=content)


class DummyResponse:
    def __init__(self, content):
        self.choices = [DummyChoice(content)]


class TestDualProviderLLMClient:
    def test_gemini_primary_success(self):
        with patch("engine.llm_client.OpenAI") as mock_openai_cls:
            mock_gemini = MagicMock()
            mock_gemini.chat.completions.create.return_value = DummyResponse("Gemini response")
            mock_openai_cls.return_value = mock_gemini

            client = BackendLLMClient(
                gemini_api_key="gemini-key-123",
                groq_api_key="groq-key-456",
            )
            client.gemini_client = mock_gemini
            mock_groq = MagicMock()
            client.groq_client = mock_groq

            result = client.call_chat("system prompt", "user prompt")

            assert result == "Gemini response"
            assert client.last_provider == "gemini"
            assert "gemini" in client.provider_summary
            mock_gemini.chat.completions.create.assert_called_once()
            mock_groq.chat.completions.create.assert_not_called()

    def test_gemini_rate_limit_falls_back_to_groq(self):
        with patch("engine.llm_client.OpenAI"):
            mock_gemini = MagicMock()
            # Simulate 429 Rate Limit error from Gemini
            mock_gemini.chat.completions.create.side_effect = Exception("429 Resource has been exhausted (e.g. check quota)")

            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = DummyResponse("Groq fallback response")

            client = BackendLLMClient(
                gemini_api_key="gemini-key-123",
                groq_api_key="groq-key-456",
            )
            client.gemini_client = mock_gemini
            client.groq_client = mock_groq

            result = client.call_chat("system prompt", "user prompt")

            assert result == "Groq fallback response"
            assert client.last_provider == "groq"
            assert "groq" in client.provider_summary
            assert mock_gemini.chat.completions.create.call_count >= 1
            mock_groq.chat.completions.create.assert_called_once()

    def test_gemini_generic_failure_falls_back_to_groq(self):
        with patch("engine.llm_client.OpenAI"):
            mock_gemini = MagicMock()
            mock_gemini.chat.completions.create.side_effect = RuntimeError("Connection dropped")

            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = DummyResponse("Groq rescued")

            client = BackendLLMClient(
                gemini_api_key="gemini-key-123",
                groq_api_key="groq-key-456",
            )
            client.gemini_client = mock_gemini
            client.groq_client = mock_groq

            result = client.call_chat("system", "user")

            assert result == "Groq rescued"
            assert client.last_provider == "groq"

    def test_groq_only_when_gemini_key_absent(self):
        with patch("engine.llm_client.OpenAI") as mock_openai_cls:
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.return_value = DummyResponse("Direct groq")
            mock_openai_cls.return_value = mock_groq

            client = BackendLLMClient(
                gemini_api_key="",
                groq_api_key="groq-only-key",
            )
            client.groq_client = mock_groq

            result = client.call_chat("system", "user")

            assert result == "Direct groq"
            assert client.last_provider == "groq"
            assert client.gemini_client is None

    def test_both_failing_raises_llm_unavailable(self):
        with patch("engine.llm_client.OpenAI"):
            mock_gemini = MagicMock()
            mock_gemini.chat.completions.create.side_effect = Exception("429 Gemini quota exhausted")

            mock_groq = MagicMock()
            mock_groq.chat.completions.create.side_effect = Exception("Groq 503 service unavailable")

            client = BackendLLMClient(
                gemini_api_key="gemini-key",
                groq_api_key="groq-key",
            )
            client.gemini_client = mock_gemini
            client.groq_client = mock_groq

            with pytest.raises(LLMUnavailable) as exc_info:
                client.call_chat("system", "user")

            assert "Gemini error" in str(exc_info.value)
            assert "Groq error" in str(exc_info.value)

    def test_no_keys_raises_llm_unavailable(self):
        client = BackendLLMClient(
            gemini_api_key="",
            groq_api_key="",
            api_key="",
        )
        with pytest.raises(LLMUnavailable) as exc_info:
            client.call_chat("system", "user")

        assert "No Gemini or Groq API key configured" in str(exc_info.value)
