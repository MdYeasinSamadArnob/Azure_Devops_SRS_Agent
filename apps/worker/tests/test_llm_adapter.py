import socket
from unittest.mock import MagicMock, patch

import pytest
from srs_core.llm.adapter import LLMAdapter, LLMSettings


def test_settings_from_env_reads_config(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "ollama/qwen3.5:4b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.11.200.99:11434")
    monkeypatch.setenv("LLM_THINKING", "true")

    settings = LLMSettings.from_env()

    assert settings is not None
    assert settings.model_name == "ollama/qwen3.5:4b"
    assert settings.api_base == "http://10.11.200.99:11434"
    assert settings.thinking is True


def test_settings_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert LLMSettings.from_env() is None


def test_complete_returns_content_on_success():
    settings = LLMSettings(model_name="ollama/qwen3.5:4b", api_base="http://x:11434", thinking=False)
    adapter = LLMAdapter(settings)

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="  Generated text.  "))]

    with patch("srs_core.llm.adapter.litellm.completion", return_value=fake_response) as mock_completion:
        result = adapter.complete("write something", system="be brief")

    assert result == "Generated text."
    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["model"] == "ollama/qwen3.5:4b"
    assert call_kwargs["api_base"] == "http://x:11434"
    assert call_kwargs["messages"][0] == {"role": "system", "content": "be brief"}


def test_complete_never_raises_on_provider_failure():
    settings = LLMSettings(model_name="ollama/qwen3.5:4b", api_base=None, thinking=False)
    adapter = LLMAdapter(settings)

    with patch("srs_core.llm.adapter.litellm.completion", side_effect=ConnectionError("unreachable")):
        result = adapter.complete("write something")

    assert result is None  # never raises — AI enhancement is always optional


def test_api_base_omitted_for_non_ollama_models():
    settings = LLMSettings(model_name="gpt-4o", api_base="http://should-not-be-used:1234", thinking=False)
    adapter = LLMAdapter(settings)

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="ok"))]

    with patch("srs_core.llm.adapter.litellm.completion", return_value=fake_response) as mock_completion:
        adapter.complete("hi")

    assert "api_base" not in mock_completion.call_args.kwargs


def _ollama_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _ollama_reachable("10.11.200.99", 11434),
    reason="live Ollama instance not reachable from this environment",
)
def test_live_completion_against_real_ollama():
    settings = LLMSettings(model_name="ollama/qwen3.5:4b", api_base="http://10.11.200.99:11434", thinking=False, timeout_seconds=90)
    adapter = LLMAdapter(settings)

    result = adapter.complete("Reply with exactly one word: PONG", max_tokens=20)

    assert result is not None
    assert "PONG" in result.upper()
