from typing import Callable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen):
    """A confirmation dialog with Yes/No buttons."""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
        layer: dialog;
    }
    
    ConfirmDialog > Container {
        width: 70%;
        height: auto;
        min-height: 15;
        border: solid $accent;
        background: $panel;
    }
    
    ConfirmDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    
    ConfirmDialog #message-content {
        height: auto;
        margin: 1;
        padding: 1;
    }
    
    ConfirmDialog #button-container {
        height: 5;
        align: center middle;
        margin: 0;
    }
    
    ConfirmDialog #button-container Button {
        height: 3;
        content-align: center middle;
        text-align: center;
        margin: 0 5;
        min-width: 10;
    }
    """

    def __init__(
        self,
        title: str,
        message: str,
        callback: Callable[[bool], None],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.title_text = title
        self.message_text = message
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(self.title_text, classes="dialog-title")
            with Container(id="message-content"):
                yield Static(self.message_text, id="message-text")
            with Horizontal(id="button-container"):
                yield Button("Yes", id="confirm-yes", variant="error")
                yield Button("No", id="confirm-no", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        elif event.button.id == "confirm-no":
            self.dismiss(False)

    def on_mount(self) -> None:
        self.query_one("#message-text").update(self.message_text)
        # Focus on the "No" button by default for safety
        self.query_one("#confirm-no").focus()

    def on_key(self, event: Key) -> None:
        """Handle keyboard shortcuts for the confirmation dialog."""
        if event.key == "escape":
            # ESC to exit (No)
            self.dismiss(False)
            event.prevent_default()
        elif event.key == "space" or event.key == "enter":
            # Space or Enter to activate the currently focused button
            focused = self.focused
            if focused and focused.id == "confirm-yes":
                self.dismiss(True)
            elif focused and focused.id == "confirm-no":
                self.dismiss(False)
            event.prevent_default()
        elif event.key == "y":
            # Y for Yes (explicit)
            self.dismiss(True)
            event.prevent_default()
        elif event.key == "n":
            # N for No (explicit)
            self.dismiss(False)
            event.prevent_default()

    def dismiss(self, result=None) -> None:
        """Override dismiss to call callback immediately."""
        if self.callback:
            confirmed = result if result is not None else False
            self.callback(confirmed)
        super().dismiss(result)
