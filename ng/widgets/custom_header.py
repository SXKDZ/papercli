from typing import TYPE_CHECKING, Optional

from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static

from ng.version import get_version

if TYPE_CHECKING:
    from ng.app import PaperCLIApp


class CustomHeader(Static):
    """Custom header showing app title and paper statistics."""

    total_papers = reactive(0)
    current_position = reactive(1)
    selected_count = reactive(0)

    DEFAULT_CSS = """
    CustomHeader {
        dock: top;
        width: 100%;
        height: 1;
        background: $panel;
        color: $foreground;
        text-style: bold;
        content-align: left middle;
    }

    CustomHeader Horizontal {
        width: 100%;
        height: 1;
        align: left middle;
    }

    .header-left {
        width: auto;
        text-align: left;
        content-align: left middle;
        padding-left: 1;
    }

    .header-center {
        width: 1fr;
        text-align: left;
        content-align: left middle;
    }

    .header-right {
        width: auto;
        text-align: right;
        content-align: right middle;
        padding-right: 1;
    }
    """

    def __init__(self, app_ref: Optional["PaperCLIApp"] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._app_ref = app_ref

    def compose(self):
        version = get_version()
        with Horizontal():
            yield Static(f"✦ PaperCLI v{version} ✦", classes="header-left")
            yield Static("", classes="header-center")
            yield Static("", classes="header-right", id="status-display")

    def watch_total_papers(self, total: int) -> None:
        """Update display when total papers changes."""
        self._update_status_display()

    def watch_current_position(self, position: int) -> None:
        """Update display when current position changes."""
        self._update_status_display()

    def watch_selected_count(self, count: int) -> None:
        """Update display when selected count changes."""
        self._update_status_display()

    def _update_status_display(self) -> None:
        """Update the status display text."""
        status_display = self.query_one("#status-display")
        status_text = f"Total: {self.total_papers}  Current: {self.current_position}  Selected: {self.selected_count}"
        status_display.update(status_text)

    def update_stats(self, total: int, current: int, selected: int) -> None:
        """Update all statistics at once."""
        self.total_papers = total
        self.current_position = current
        self.selected_count = selected
