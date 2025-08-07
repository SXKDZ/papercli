from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Button, Static
from textual.screen import Screen
from typing import List, Dict, Any

class LogScreen(Screen):
    """A screen to display application logs."""

    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
    ]

    def __init__(self, logs: List[Dict[str, Any]], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logs = logs

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Activity Log", classes="screen-title")
        with VerticalScroll(id="log-content"):
            yield Static("", id="log-text")
        yield Footer()

    def on_mount(self) -> None:
        self.update_log_display()

    def update_log_display(self) -> None:
        if not self.logs:
            log_content = "No activities logged in this session."
        else:
            # Limit to last 500 entries to prevent scrolling issues
            recent_logs = (
                self.logs[-500:] if len(self.logs) > 500 else self.logs
            )

            log_entries = []
            # Show most recent first
            for log in reversed(recent_logs):
                # Limit each log entry to ~500 characters to keep the log readable
                details = log["details"]
                if len(details) > 500:
                    details = details[:500] + "... [truncated]"

                log_entries.append(
                    f"[{log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {log['action']}: {details}"
                )

            # Add header if we're showing limited entries
            if len(self.logs) > 500:
                header = (
                    f"Activity Log (showing last 500 of {len(self.logs)} entries)\n"
                    + "=" * 60
                    + "\n\n"
                )
                log_content = header + "\n".join(log_entries)
            else:
                log_content = (
                    f"Activity Log ({len(self.logs)} entries)\n"
                    + "=" * 40
                    + "\n\n"
                    + "\n".join(log_entries)
                )
        self.query_one("#log-text", Static).update(log_content)

    def action_dismiss(self) -> None:
        self.dismiss()
