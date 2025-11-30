"""
Centralized constants for the PaperCLI application.
All default values for environment variables and configuration should be defined here.
"""

# ============================================================================
# OpenAI API Configuration
# ============================================================================

# Default models for different tasks
DEFAULT_CHAT_MODEL = "gpt-4o"  # For chat, summarization, and complex reasoning tasks
DEFAULT_EXTRACTION_MODEL = "gpt-4o-mini"  # For metadata extraction and simple parsing tasks

# API parameters
DEFAULT_MAX_TOKENS = 4000  # Maximum tokens in response
DEFAULT_TEMPERATURE = 0.7  # Temperature for non-reasoning models (0.0-2.0)
DEFAULT_REASONING_EFFORT = "medium"  # Reasoning effort for o1/o3 models (low/medium/high)
DEFAULT_SHOW_THINKING = False  # Whether to show reasoning model's thinking process


# ============================================================================
# PDF and HTML Processing
# ============================================================================

DEFAULT_PDF_SUMMARY_PAGES = 10  # Number of pages to extract for paper summarization
DEFAULT_PDF_METADATA_PAGES = 2  # Number of pages to extract for metadata extraction
DEFAULT_HTML_MAX_CHARS = 20000  # Maximum characters to extract from HTML for summarization


# ============================================================================
# Sync Configuration
# ============================================================================

DEFAULT_AUTO_SYNC = False  # Whether auto-sync is enabled
DEFAULT_AUTO_SYNC_INTERVAL = 5  # Auto-sync interval in seconds


# ============================================================================
# UI Configuration
# ============================================================================

DEFAULT_THEME = "textual-dark"  # Default UI theme
