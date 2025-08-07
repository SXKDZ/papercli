from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Button, Static
from textual.screen import ModalScreen

class DoctorDialog(ModalScreen):
    """A modal dialog for displaying the doctor report."""

    def __init__(self, report_text: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.report_text = report_text

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Database Doctor Report", classes="dialog-title")
        with VerticalScroll(id="report-content"):
            yield Static(self.report_text, id="report-text")
        yield Button("OK", id="doctor-ok", classes="--warning")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "doctor-ok":
            self.dismiss()

    def on_mount(self) -> None:
        self.query_one("#report-text").update(self.report_text)