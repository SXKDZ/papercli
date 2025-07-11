"""
Centralized status message handling with consistent icons and formatting.
"""

from typing import Dict, Optional


class StatusMessages:
    """Centralized status message factory with consistent icons and formatting."""
    
    # Core action icons - keep minimal and consistent
    ICONS = {
        'success': '✓',
        'error': '✗', 
        'warning': '⚠',
        'info': 'ℹ',
        'loading': '⌛',
        'search': '🔍',
        'add': '📄',
        'export': '📤',
        'delete': '🗑',
        'edit': '✏',
        'chat': '💬',
        'help': '📖',
        'select': '🎯',
        'clean': '🧹'
    }
    
    @classmethod
    def format_message(cls, message: str, msg_type: str = 'info', action: Optional[str] = None) -> str:
        """
        Format a status message with appropriate icon.
        
        Args:
            message: The message text
            msg_type: Type of message (success, error, warning, info)
            action: Optional action type for additional context icon
        
        Returns:
            Formatted message string
        """
        # If message already has any icon/emoji at the start, return as-is
        stripped = message.strip()
        if any(stripped.startswith(icon) for icon in cls.ICONS.values()) or \
           any(stripped.startswith(sym) for sym in ['📜', '📖', '📚', '←', '→', '↑', '↓', '🔄', '💻', '🖥️', '📊']):
            return message
            
        # Get primary icon from message type
        icon = cls.ICONS.get(msg_type, cls.ICONS['info'])
        
        # Add action-specific icon if provided
        if action and action in cls.ICONS:
            icon = cls.ICONS[action]
            
        return f"{icon} {message}"
    
    @classmethod
    def success(cls, message: str, action: Optional[str] = None) -> str:
        """Create a success message."""
        return cls.format_message(message, 'success', action)
    
    @classmethod
    def error(cls, message: str, action: Optional[str] = None) -> str:
        """Create an error message."""
        return cls.format_message(message, 'error', action)
    
    @classmethod
    def warning(cls, message: str, action: Optional[str] = None) -> str:
        """Create a warning message."""
        return cls.format_message(message, 'warning', action)
    
    @classmethod
    def info(cls, message: str, action: Optional[str] = None) -> str:
        """Create an info message."""
        return cls.format_message(message, 'info', action)
    
    @classmethod
    def loading(cls, message: str, action: Optional[str] = None) -> str:
        """Create a loading message."""
        return cls.format_message(message, 'loading', action)

    # Common message templates
    @classmethod
    def paper_added(cls, title: str) -> str:
        """Standard message for paper addition."""
        truncated_title = title[:50] + "..." if len(title) > 50 else title
        return cls.format_message(f"Added: {truncated_title}", 'success', 'add')
    
    @classmethod
    def papers_loaded(cls, count: int) -> str:
        """Standard message for papers loaded."""
        return cls.format_message(f"Loaded {count} papers", 'info')
    
    @classmethod
    def no_papers_selected(cls) -> str:
        """Standard message for no papers selected."""
        return cls.format_message("No papers selected or under cursor", 'warning')
    
    @classmethod
    def search_started(cls, query: str) -> str:
        """Standard message for search started."""
        return cls.format_message(f"Searching for '{query}'...", 'loading', 'search')
    
    @classmethod
    def export_started(cls) -> str:
        """Standard message for export started."""
        return cls.format_message("Exporting papers...", 'loading', 'export')
    
    @classmethod
    def selection_mode_entered(cls) -> str:
        """Standard message for entering selection mode."""
        return cls.format_message("Entered multi-selection mode. Use Space to select, ESC to exit.", 'info', 'select')