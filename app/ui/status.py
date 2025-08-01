"""
Centralized status message handling with consistent icons and formatting.
"""

from typing import Optional


class StatusMessages:
    """Centralized status message factory with consistent icons and formatting."""

    # Core action icons - keep minimal and consistent
    ICONS = {
        "success": "✓",
        "error": "✗",
        "warning": "⚠",
        "info": "ℹ",
        "loading": "⌛",
        "search": "🔍",
        "add": "📄",
        "export": "📤",
        "delete": "🗑",
        "edit": "✏",
        "chat": "💬",
        "help": "📖",
        "select": "🎯",
        "clean": "🧹",
        "llm": "🤖",
        "papers": "📚",
        "log": "📜",
        "diagnose": "🔍",
        "fetch": "📡",
        "process": "📄",
        "bibtex": "📚",
        "filter": "🔽",
        "sort": "🔄",
        "close": "←",
        "clear": "🧹",
        "open": "📖",
    }

    @classmethod
    def format_message(cls, message: str, action: Optional[str] = None) -> str:
        """
        Format a status message with appropriate icon.

        Args:
            message: The message text
            action: Action type for icon (success, error, warning, info, loading, etc.)

        Returns:
            Formatted message string
        """
        # If message already has any icon/emoji at the start, return as-is
        stripped = message.strip()
        if any(stripped.startswith(icon) for icon in cls.ICONS.values()):
            return message

        # Get icon from action type, default to info
        icon = cls.ICONS.get(action, cls.ICONS["info"])

        return f"{icon} {message}"
