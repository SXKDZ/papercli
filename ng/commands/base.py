from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CommandHandler:
    """Base class for command handlers."""

    def __init__(self, app: PaperCLIApp):
        self.app = app

    def _get_target_papers(self) -> List:
        """Return selected papers from the main paper list, or an empty list."""
        try:
            paper_list = self.app.screen.query_one("#paper-list-view")
            return paper_list.get_selected_papers()
        except Exception:
            return []

    def _find_paper_list_view(self):
        """Find the paper list view widget if present."""
        try:
            return self.app.screen.query_one("#paper-list-view")
        except Exception:
            if hasattr(self.app, "main_screen") and self.app.main_screen:
                try:
                    return self.app.main_screen.query_one("#paper-list-view")
                except Exception:
                    return None
            return None
