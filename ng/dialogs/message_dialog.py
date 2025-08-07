from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Static
from textual.screen import ModalScreen

class MessageDialog(ModalScreen):
    """A generic modal dialog for displaying messages."""

    DEFAULT_CSS = """
    MessageDialog {
        align: center middle;
    }
    
    #dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
        margin-bottom: 1;
    }
    
    #message-content {
        width: 80%;
        height: 60%;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }
    
    #message-ok {
        margin: 1;
    }
    """

    def __init__(self, title: str, message: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_text = title
        self.message_text = message

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, id="dialog-title")
        with VerticalScroll(id="message-content"):
            yield Static(self.message_text, id="message-text")
        yield Button("OK", id="message-ok", classes="--warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "message-ok":
            self.dismiss()

    def on_mount(self) -> None:
        self.query_one("#message-text").update(self.message_text)