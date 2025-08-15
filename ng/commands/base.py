from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CommandHandler:
    """Base class for command handlers."""

    def __init__(self, app: PaperCLIApp):
        self.app = app
