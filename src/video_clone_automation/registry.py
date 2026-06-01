from __future__ import annotations

from importlib import import_module
from typing import Any

from video_clone_automation.providers.mock import (
    MockImageProvider,
    MockLLMProvider,
    MockVideoProvider,
)
from video_clone_automation.providers.images import OpenAICompatibleImageProvider
from video_clone_automation.providers.openrouter import (
    OpenAICompatibleChatProvider,
    OpenRouterChatProvider,
    YunwuGeminiGenerateContentProvider,
)
from video_clone_automation.providers.videos import OpenAICompatibleVideoProvider


def build_provider(provider_config: dict[str, Any]) -> Any:
    provider_type = provider_config.get("type")
    options = provider_config.get("options", {})

    if provider_type == "mock_llm":
        return MockLLMProvider(**options)
    if provider_type == "mock_image":
        return MockImageProvider(**options)
    if provider_type == "mock_video":
        return MockVideoProvider(**options)
    if provider_type == "openai_compatible_image":
        return OpenAICompatibleImageProvider(**options)
    if provider_type == "openai_compatible_video":
        return OpenAICompatibleVideoProvider(**options)
    if provider_type == "openai_compatible_chat":
        return OpenAICompatibleChatProvider(**options)
    if provider_type == "openrouter_chat":
        return OpenRouterChatProvider(**options)
    if provider_type == "yunwu_gemini_generate_content":
        return YunwuGeminiGenerateContentProvider(**options)

    import_path = provider_config.get("import")
    if import_path:
        module_name, attr_name = import_path.split(":")
        module = import_module(module_name)
        factory = getattr(module, attr_name)
        return factory(**options)

    raise ValueError(f"Unsupported provider type: {provider_type}")
