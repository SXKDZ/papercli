from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static


class MessageDialog(ModalScreen):
    """A generic modal dialog for displaying messages."""

    DEFAULT_CSS = """
    MessageDialog {
        align: center middle;
    }

    #message-container {
        width: 50%;
        height: 30;
        border: solid $accent;
        background: $panel;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }

    #message-content {
        padding: 1;
        height: 1fr;
    }

    #message-buttons {
        height: 5;
        align: center middle;
        padding: 0;
    }

    #message-ok {
        margin: 0 1;
        height: 3;
        min-width: 10;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, title: str, message: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_text = title
        self.message_text = message

    def compose(self) -> ComposeResult:
        with Vertical(id="message-container"):
            yield Static(self.title_text, id="dialog-title")
            with VerticalScroll(id="message-content"):
                yield Markdown(self.message_text, id="message-text")
            with Container(id="message-buttons"):
                yield Button("OK", id="message-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "message-ok":
            self.dismiss()

    def on_mount(self) -> None:
        self.query_one("#message-text", Markdown).update(self.message_text)
        # Focus OK by default so Enter immediately closes the dialog
        try:
            self.query_one("#message-ok", Button).focus()
        except Exception:
            pass
