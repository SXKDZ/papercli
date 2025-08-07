from textual.widgets import Static
from textual.containers import VerticalScroll
from textual.reactive import reactive
from datetime import datetime

class ErrorPanel(Static):
    """A widget to display detailed error messages and logs."""

    error_messages = reactive([])
    show_panel = reactive(False)
    panel_mode = reactive("error")  # "error" or "log"
    logs = reactive([])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.styles.border = ("solid", "red")
        self.styles.background = "#220000"
        self.styles.display = "none"

    def watch_show_panel(self, show: bool) -> None:
        self.styles.display = "block" if show else "none"

    def watch_error_messages(self, messages: list) -> None:
        if self.panel_mode == "error":
            self.update_content()

    def watch_logs(self, logs: list) -> None:
        if self.panel_mode == "log":
            self.update_content()

    def watch_panel_mode(self, mode: str) -> None:
        if mode == "log":
            self.styles.border = ("solid", "blue")
            self.styles.background = "#002020"
        else:
            self.styles.border = ("solid", "red")
            self.styles.background = "#220000"
        self.update_content()

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

    def set_logs(self, logs: list):
        """Set logs for display."""
        self.logs = logs
        if self.panel_mode == "log":
            self.update_content()

    def show_logs(self):
        """Switch to log mode and show the panel."""
        self.panel_mode = "log"
        self.show_panel = True

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
        if not self.error_messages:
            self.update("")
            return

        text_lines = []
        for i, error in enumerate(self.error_messages[-5:], 1):  # Show last 5 errors
            timestamp = error["timestamp"].strftime("%H:%M:%S")
            text_lines.append(f"[red][{timestamp}] {error['title']}[/red]")
            text_lines.append(f"[white]{error['message']}[/white]")
            if i < len(self.error_messages[-5:]):
                text_lines.append("")

        text_lines.append("")
        text_lines.append("[yellow]Press ESC to close this panel[/yellow]")

        self.update("\n".join(text_lines))

    def update_log_content(self):
        if not self.logs:
            self.update("[yellow]No activities logged in this session.[/yellow]\n\n[yellow]Press ESC to close this panel[/yellow]")
            return

        text_lines = []
        text_lines.append(f"[blue]Activity Log ({len(self.logs)} entries)[/blue]")
        text_lines.append("=" * 40)
        text_lines.append("")

        # Show last 10 log entries
        recent_logs = self.logs[-10:] if len(self.logs) > 10 else self.logs
        for log in reversed(recent_logs):
            timestamp = log["timestamp"].strftime("%H:%M:%S")
            action = log["action"]
            details = log["details"]
            
            # Limit details length for display
            if len(details) > 100:
                details = details[:97] + "..."
            
            text_lines.append(f"[cyan][{timestamp}] {action}:[/cyan]")
            text_lines.append(f"[white]{details}[/white]")
            text_lines.append("")

        if len(self.logs) > 10:
            text_lines.append(f"[dim](showing last 10 of {len(self.logs)} entries)[/dim]")
            text_lines.append("")

        text_lines.append("[yellow]Press ESC to close this panel[/yellow]")

        self.update("\n".join(text_lines))
