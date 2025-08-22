"""
Theme color service for consistent theming across the application.
"""

from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from textual.app import App


class ThemeService:
    """Service for providing theme-appropriate colors across the application."""

    # Light theme color mappings
    LIGHT_THEME_COLORS = {
        "header": "bold blue",
        "text": "black",
        "success": "dark_green",
        "error": "red",
        "warning": "orange",
        "info": "blue",
        "link": "blue underline",
        "dim": "dim grey37",
        "accent": "bold blue",
        "highlight": "bold blue",
        "muted": "grey50",
    }

    # Dark theme color mappings
    DARK_THEME_COLORS = {
        "header": "bold cyan",
        "text": "white",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "info": "cyan",
        "link": "blue underline",
        "dim": "dim white",
        "accent": "bold cyan",
        "highlight": "bold cyan",
        "muted": "dim white",
    }

    @classmethod
    def get_colors(
        cls, app: Optional["App"] = None, theme_name: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Get theme-appropriate colors.

        Args:
            app: The Textual app instance to get theme from
            theme_name: Override theme name (if provided, app is ignored)

        Returns:
            Dictionary of color names to Rich color strings
        """
        # Determine current theme
        if theme_name:
            current_theme = theme_name
        elif app:
            current_theme = getattr(app, "theme", "textual-dark")
        else:
            current_theme = "textual-dark"

        # Return appropriate color mapping
        if current_theme in ["textual-light", "light"]:
            return cls.LIGHT_THEME_COLORS.copy()
        else:
            return cls.DARK_THEME_COLORS.copy()

    @classmethod
    def get_color(
        cls,
        color_name: str,
        app: Optional["App"] = None,
        theme_name: Optional[str] = None,
    ) -> str:
        """
        Get a specific theme color.

        Args:
            color_name: Name of the color to retrieve
            app: The Textual app instance to get theme from
            theme_name: Override theme name (if provided, app is ignored)

        Returns:
            Rich color string for the requested color
        """
        colors = cls.get_colors(app=app, theme_name=theme_name)
        return colors.get(color_name, colors.get("text", "white"))

    @classmethod
    def get_markup_color(
        cls,
        color_name: str,
        app: Optional["App"] = None,
        theme_name: Optional[str] = None,
    ) -> str:
        """
        Get a theme color formatted for Rich markup (e.g., '[red]text[/red]').

        Args:
            color_name: Name of the color to retrieve
            app: The Textual app instance to get theme from
            theme_name: Override theme name (if provided, app is ignored)

        Returns:
            Color name for use in Rich markup (without brackets)
        """
        colors = cls.get_colors(app=app, theme_name=theme_name)
        color_style = colors.get(color_name, colors.get("text", "white"))

        # Extract just the color name for markup (remove modifiers like 'bold', 'dim')
        color_parts = color_style.split()
        if len(color_parts) > 1:
            # Find the actual color name (not modifier)
            for part in color_parts:
                if part not in ["bold", "dim", "italic", "underline"]:
                    return part
        return color_parts[-1] if color_parts else "white"

    @classmethod
    def is_light_theme(
        cls, app: Optional["App"] = None, theme_name: Optional[str] = None
    ) -> bool:
        """
        Check if the current theme is a light theme.

        Args:
            app: The Textual app instance to get theme from
            theme_name: Override theme name (if provided, app is ignored)

        Returns:
            True if light theme, False if dark theme
        """
        if theme_name:
            current_theme = theme_name
        elif app:
            current_theme = getattr(app, "theme", "textual-dark")
        else:
            current_theme = "textual-dark"

        return current_theme in ["textual-light", "light"]
