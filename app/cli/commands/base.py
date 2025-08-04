"""Base command handler class."""

from typing import TYPE_CHECKING
from typing import List

if TYPE_CHECKING:
    from ...db.models import Paper
    from ..main import PaperCLI


class BaseCommandHandler:
    """Base class for command handlers."""

    def __init__(self, cli: "PaperCLI"):
        self.cli = cli

    def _get_target_papers(self) -> List["Paper"]:
        """Get papers to operate on (selected or current)."""
        return self.cli._get_target_papers()

    def _add_log(self, action: str, details: str):
        """Add entry to activity log."""
        self.cli._add_log(action, details)

    def load_papers(self):
        """Reload papers from database."""
        self.cli.load_papers()

    def show_error_panel_with_message(self, title: str, message: str):
        """Show error panel with message."""
        self.cli.show_error_panel_with_message(title, message)
