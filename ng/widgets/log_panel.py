from textual.widgets import Markdown
from textual.reactive import reactive
from textual.events import Key
from textual.containers import Vertical
from textual.app import ComposeResult
from datetime import datetime

from ng.services import ThemeService


class LogPanel(Vertical):
    """A widget to display detailed error messages and logs."""

    DEFAULT_CSS = """
    LogPanel {
        scrollbar-size: 1 1;
        scrollbar-size-horizontal: 0;
        scrollbar-size-vertical: 1;
    }
    
    LogPanel Markdown {
        height: 1fr;
        width: 100%;
        text-wrap: wrap;
    }
    """

    error_messages = reactive([])
    show_panel = reactive(False)
    panel_mode = reactive("error")  # "error" or "log"
    logs = reactive([])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Use theme-aware colors for initial setup (will be updated in watch_panel_mode)
        self._update_theme_colors("error")
        self.styles.display = "none"
        self.can_focus = True  # Enable focus to receive key events
        self._app_ref = None  # Reference to app for direct updates
        self._markdown_widget = None  # Reference to the markdown widget

    def compose(self) -> ComposeResult:
        """Compose the log panel with markdown content and word wrapping."""
        self._markdown_widget = Markdown("", id="log-content")
        yield self._markdown_widget


    def watch_show_panel(self, show: bool) -> None:
        self.styles.display = "block" if show else "none"

    def watch_error_messages(self, messages: list) -> None:
        if self.panel_mode == "error":
            self.update_content()

    def watch_logs(self, logs: list) -> None:
        if self.panel_mode == "log":
            self.update_content()

    def watch_panel_mode(self, mode: str) -> None:
        self._update_theme_colors(mode)
        self.update_content()
        
    def _update_theme_colors(self, mode: str) -> None:
        """Update theme colors based on mode and current theme."""
        is_light = ThemeService.is_light_theme(app=self.app)
        
        if mode == "log":
            if is_light:
                self.styles.border = ("solid", "blue")
                self.styles.background = "#e6f3ff"  # Light blue background
            else:
                self.styles.border = ("solid", "blue")
                self.styles.background = "#002020"  # Dark blue background
        else:  # error mode
            if is_light:
                self.styles.border = ("solid", "red")
                self.styles.background = "#ffe6e6"  # Light red background
            else:
                self.styles.border = ("solid", "red")
                self.styles.background = "#220000"  # Dark red background

    def add_error(self, title: str, message: str):
        """Add an error message to the panel."""
        self.error_messages = self.error_messages + [
            {
                "title": title,
                "message": message,
                "timestamp": datetime.now(),
            }
        ]
        if self.panel_mode == "error":
            self.show_panel = True

    def set_app_reference(self, app):
        """Set reference to the app for auto-refresh."""
        self._app_ref = app

    def set_logs(self, logs: list):
        """Set logs for display."""
        self.logs = logs
        if self.panel_mode == "log":
            self.update_content()

    def show_logs(self):
        """Switch to log mode and show the panel."""
        self.panel_mode = "log"
        self.show_panel = True
        # Load current logs when showing
        if self._app_ref and hasattr(self._app_ref, 'logs'):
            self.logs = self._app_ref.logs

    def refresh_if_visible(self):
        """Refresh logs if panel is visible and in log mode. Called directly by app."""
        if (self.show_panel and 
            self.panel_mode == "log" and 
            self._app_ref and 
            hasattr(self._app_ref, 'logs')):
            self.logs = self._app_ref.logs
            self.update_content()


    def show_errors(self):
        """Switch to error mode."""
        self.panel_mode = "error"
        if self.error_messages:
            self.show_panel = True

    def clear_errors(self):
        """Clear all error messages."""
        self.error_messages = []
        if self.panel_mode == "error":
            self.show_panel = False

    def update_content(self):
        if self.panel_mode == "log":
            self.update_log_content()
        else:
            self.update_error_content()

    def update_error_content(self):
        if not self._markdown_widget:
            return
            
        if not self.error_messages:
            self._markdown_widget.update("")
            return

        text_lines = []
        text_lines.append("# Error Log")
        text_lines.append("")

        for i, error in enumerate(self.error_messages[-5:], 1):  # Show last 5 errors
            timestamp = error["timestamp"].strftime("%H:%M:%S")
            text_lines.append(f"## [{timestamp}] {error['title']}")
            text_lines.append(f"{error['message']}")
            if i < len(self.error_messages[-5:]):
                text_lines.append("")

        markdown_content = "\n".join(text_lines)
        self._markdown_widget.update(markdown_content)

    def update_log_content(self):
        if not self._markdown_widget:
            return
            
        if not self.logs:
            markdown_content = "# Activity Log\n\n*No activities logged in this session.*"
            self._markdown_widget.update(markdown_content)
            return

        text_lines = []
        text_lines.append("# Activity Log")
        text_lines.append(f"**Total entries:** {len(self.logs)} | **Session active**")
        text_lines.append("")
        text_lines.append("---")
        text_lines.append("")

        # Show all logs (newest first)
        all_logs_reversed = list(reversed(self.logs))
        for log in all_logs_reversed:
            timestamp = log["timestamp"].strftime("%H:%M:%S")
            action = log["action"]
            details = log["details"]

            # Use Markdown list formatting for better structure
            text_lines.append(f"- **[{timestamp}]** `{action}`: {details}")
            text_lines.append("")

        text_lines.append("---")
        text_lines.append(f"*Showing all {len(self.logs)} entries*")

        markdown_content = "\n".join(text_lines)
        self._markdown_widget.update(markdown_content)


    def on_key(self, event: Key) -> None:
        """Handle key events for log panel interactions."""
        if not self.show_panel:
            return
            
        if event.key == "escape":
            self.show_panel = False
            # Return focus to command input
            try:
                command_input = self.screen.query_one("#command-input")
                self.app.set_focus(command_input)
            except Exception:
                pass
            event.prevent_default()
