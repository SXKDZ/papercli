"""
LLM Utilities for OpenAI model parameter detection and management.
Centralized location for model capabilities and parameter requirements.
"""

import os
from typing import Dict, Any


class LLMModelUtils:
    """Utility class for determining OpenAI model capabilities and parameters."""
    
    # Comprehensive list of reasoning models that use max_completion_tokens
    REASONING_MODELS = {
        # o1 series
        "o1", "o1-mini", "o1-preview",
        # o3 series  
        "o3", "o3-mini", "o3-pro",
        # o4 series
        "o4", "o4-mini", 
        # GPT-5 series
        "gpt-5", "gpt-5-mini", "gpt-5-nano",
        # Codex models (if they follow reasoning pattern)
        "codex-mini",
    }
    
    
    @classmethod
    def is_reasoning_model(cls, model_name: str) -> bool:
        """
        Check if a model uses reasoning parameters (max_completion_tokens).
        
        Args:
            model_name: The OpenAI model name
            
        Returns:
            bool: True if model uses max_completion_tokens, False if max_tokens
        """
        model_lower = model_name.lower()
        
        # Check exact matches first
        if model_lower in cls.REASONING_MODELS:
            return True
            
        # Check prefixes for model families
        for reasoning_model in cls.REASONING_MODELS:
            if model_lower.startswith(reasoning_model + "-") or model_lower.startswith(reasoning_model):
                return True
                
        return False
    
    
    @classmethod
    def get_model_parameters(cls, model_name: str, max_tokens: int = None, temperature: float = None) -> Dict[str, Any]:
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
            max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        if temperature is None:
            temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))
        
        # Set token parameter based on model type
        if cls.is_reasoning_model(model_name):
            # Reasoning models use max_completion_tokens and don't support temperature
            params["max_completion_tokens"] = max_tokens
        else:
            # Standard models use max_tokens and support temperature
            params["max_tokens"] = max_tokens
            params["temperature"] = temperature
            
        return params
    
    @classmethod
    def get_model_info(cls, model_name: str) -> Dict[str, Any]:
        """
        Get comprehensive information about a model.
        
        Args:
            model_name: The OpenAI model name
            
        Returns:
            dict: Model information including capabilities
        """
        return {
            "name": model_name,
            "is_reasoning": cls.is_reasoning_model(model_name),
            "token_parameter": "max_completion_tokens" if cls.is_reasoning_model(model_name) else "max_tokens",
            "model_family": cls._get_model_family(model_name)
        }
    
    @classmethod
    def _get_model_family(cls, model_name: str) -> str:
        """Get the model family (o1, gpt-4, etc.)"""
        model_lower = model_name.lower()
        
        if model_lower.startswith("gpt-5"):
            return "gpt-5"
        elif model_lower.startswith("gpt-4"):
            return "gpt-4"
        elif model_lower.startswith("gpt-3.5"):
            return "gpt-3.5"
        elif model_lower.startswith("o1"):
            return "o1"
        elif model_lower.startswith("o3"):
            return "o3"
        elif model_lower.startswith("o4"):
            return "o4"
        elif model_lower.startswith("codex"):
            return "codex"
        else:
            return "other"


# Direct access functions
def is_reasoning_model(model_name: str) -> bool:
    """Check if a model uses reasoning parameters."""
    return LLMModelUtils.is_reasoning_model(model_name)


def get_model_parameters(model_name: str, max_tokens: int = None, temperature: float = None) -> Dict[str, Any]:
    """Get appropriate parameters for a model."""
    return LLMModelUtils.get_model_parameters(model_name, max_tokens, temperature)