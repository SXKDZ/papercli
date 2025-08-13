from textual.app import ComposeResult
from textual.containers import VerticalScroll, Container, Vertical
from textual.widgets import Button, Static, Markdown
from textual.screen import ModalScreen


class DoctorDialog(ModalScreen):
    """A modal dialog for displaying the doctor report."""

    DEFAULT_CSS = """
    DoctorDialog {
        align: center middle;
    }

    #doctor-container {
        width: 90;
        height: 35;
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

    #report-content {
        padding: 1;
        height: 1fr;
    }

    #doctor-buttons {
        height: 5;
        align: center middle;
        padding: 0;
    }

    #doctor-ok {
        margin: 0 1;
        height: 3;
        min-width: 8;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, report_text: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_text = report_text

    def compose(self) -> ComposeResult:
        with Vertical(id="doctor-container"):
            yield Static("Database Doctor Report", id="dialog-title")
            with VerticalScroll(id="report-content"):
                yield Markdown(self.report_text, id="report-text")
            with Container(id="doctor-buttons"):
                yield Button("OK", id="doctor-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "doctor-ok":
            self.dismiss()

    def on_mount(self) -> None:
        self.query_one("#report-text", Markdown).update(self.report_text)
        # Focus OK by default so Enter immediately closes the dialog
        try:
            self.query_one("#doctor-ok", Button).focus()
        except Exception:
            pass
