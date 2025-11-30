"""
LLM Utilities for OpenAI model parameter detection and management.
Centralized location for model capabilities and parameter requirements.
"""

import os
from typing import Any, Dict

from . import constants

# Comprehensive list of reasoning models that use max_completion_tokens
REASONING_MODELS = {
    # o1 series
    "o1",
    "o1-mini",
    "o1-preview",
    # o3 series
    "o3",
    "o3-mini",
    "o3-pro",
    # o4 series
    "o4",
    "o4-mini",
    # GPT-5 series
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    # Codex models (if they follow reasoning pattern)
    "codex-mini",
}


def is_reasoning_model(model_name: str) -> bool:
    """
    Check if a model uses reasoning parameters (max_completion_tokens).

    Args:
        model_name: The OpenAI model name

    Returns:
        bool: True if model uses max_completion_tokens, False if max_tokens
    """
    model_lower = model_name.lower()

    # Check exact matches first
    if model_lower in REASONING_MODELS:
        return True

    # Check prefixes for model families
    for reasoning_model in REASONING_MODELS:
        if model_lower.startswith(reasoning_model + "-") or model_lower.startswith(
            reasoning_model
        ):
            return True

    return False


def get_model_parameters(
    model_name: str, max_tokens: int = None, temperature: float = None
) -> Dict[str, Any]:
    """
    Get the appropriate parameters for an OpenAI model.

    Args:
        model_name: The OpenAI model name
        max_tokens: Default max tokens value (from config)
        temperature: Default temperature value (from config)

    Returns:
        dict: Parameters dict with correct keys for the model
    """
    params = {"model": model_name}

    # Use environment defaults if not provided
    if max_tokens is None:
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", str(constants.DEFAULT_MAX_TOKENS)))
    if temperature is None:
        temperature = float(os.getenv("OPENAI_TEMPERATURE", str(constants.DEFAULT_TEMPERATURE)))

    # Set token parameter based on model type
    if is_reasoning_model(model_name):
        # Reasoning models use max_completion_tokens and don't support temperature
        params["max_completion_tokens"] = max_tokens
    else:
        # Standard models use max_tokens and support temperature
        params["max_tokens"] = max_tokens
        params["temperature"] = temperature

    return params
