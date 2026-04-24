"""HardwareProfile + LLMProviderKind + create_llm_provider — Part 8 Stage 3-2½."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from application.agent_factory import (
    HardwareProfile,
    LLMProviderKind,
    SystemConfig,
    apply_hardware_profile,
    create_llm_provider,
)


def test_default_config_uses_macmini_profile() -> None:
    config = SystemConfig()
    assert config.hardware_profile is HardwareProfile.MACMINI_16GB
    assert config.llm_provider is LLMProviderKind.OLLAMA


def test_apply_desktop_profile_cascades_models_and_concurrency() -> None:
    config = SystemConfig()
    apply_hardware_profile(config, HardwareProfile.DESKTOP_RTX)
    assert config.hardware_profile is HardwareProfile.DESKTOP_RTX
    assert config.cto_model == "qwen3:14b"
    assert config.slm_model == "qwen3:8b"
    assert config.mlops_model == "llama3.2:3b"
    assert config.llm_concurrency_slm == 2
    assert config.llm_concurrency_total == 3


def test_apply_server_profile_selects_largest_models() -> None:
    config = SystemConfig()
    apply_hardware_profile(config, HardwareProfile.SERVER_GPU)
    assert config.cto_model == "qwen3.5:35b"
    assert config.llm_concurrency_total == 6


def test_apply_custom_profile_is_noop() -> None:
    config = SystemConfig(cto_model="my-custom-model", llm_concurrency_total=99, slm_model="my-slm")
    apply_hardware_profile(config, HardwareProfile.CUSTOM)
    # Only hardware_profile field is set; other values preserved.
    assert config.hardware_profile is HardwareProfile.CUSTOM
    assert config.cto_model == "my-custom-model"
    assert config.slm_model == "my-slm"
    assert config.llm_concurrency_total == 99


async def test_create_llm_provider_ollama_default() -> None:
    config = SystemConfig()
    with patch("adapters.ollama_provider.OllamaProvider") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = "ollama-instance"
        async with create_llm_provider(config) as provider:
            assert provider == "ollama-instance"
    mock_cls.assert_called_once_with(base_url="http://localhost:11434")


async def test_create_llm_provider_anthropic() -> None:
    config = SystemConfig(llm_provider=LLMProviderKind.ANTHROPIC)
    with patch("adapters.anthropic_provider.AnthropicProvider") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = "anthropic-instance"
        async with create_llm_provider(config) as provider:
            assert provider == "anthropic-instance"
    mock_cls.assert_called_once_with()


async def test_create_llm_provider_openai() -> None:
    config = SystemConfig(llm_provider=LLMProviderKind.OPENAI)
    with patch("adapters.openai_provider.OpenAIProvider") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = "openai-instance"
        async with create_llm_provider(config) as provider:
            assert provider == "openai-instance"


async def test_create_llm_provider_gemini() -> None:
    config = SystemConfig(llm_provider=LLMProviderKind.GEMINI)
    with patch("adapters.gemini_provider.GeminiProvider") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = "gemini-instance"
        async with create_llm_provider(config) as provider:
            assert provider == "gemini-instance"


def test_config_mutation_hardware_profile_cascades() -> None:
    """PATCHing hardware_profile via apply_mutation cascades preset values."""
    from interfaces.dashboard_api.config_mutation import apply_mutation

    config = SystemConfig()
    apply_mutation(
        config,
        field_name="hardware_profile",
        new_value="desktop_rtx",
    )
    assert config.hardware_profile is HardwareProfile.DESKTOP_RTX
    assert config.cto_model == "qwen3:14b"
    assert config.llm_concurrency_total == 3


def test_config_mutation_llm_provider_accepts_enum_value() -> None:
    """PATCHing llm_provider accepts the string enum value."""
    from interfaces.dashboard_api.config_mutation import apply_mutation

    config = SystemConfig()
    apply_mutation(
        config,
        field_name="llm_provider",
        new_value="anthropic",
    )
    assert config.llm_provider is LLMProviderKind.ANTHROPIC
    # llm_provider change should NOT cascade models (only hardware_profile does).
    assert config.cto_model == "qwen3:8b"


@pytest.mark.parametrize(
    "profile,expected_cto",
    [
        (HardwareProfile.MACMINI_16GB, "qwen3:8b"),
        (HardwareProfile.DESKTOP_RTX, "qwen3:14b"),
        (HardwareProfile.SERVER_GPU, "qwen3.5:35b"),
    ],
)
def test_all_profiles_have_coherent_cto_model(profile: HardwareProfile, expected_cto: str) -> None:
    config = SystemConfig()
    apply_hardware_profile(config, profile)
    assert config.cto_model == expected_cto
