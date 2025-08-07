from textual.app import ComposeResult
from textual.containers import VerticalScroll, HorizontalScroll, Container
from textual.widgets import Header, Footer, Button, Static, Input, RadioSet, RadioButton
from textual.screen import ModalScreen
from textual.reactive import reactive
from typing import Callable, Dict, Any

class AddDialog(ModalScreen):
    """A modal dialog for adding new papers with source and path/ID fields."""

    DEFAULT_CSS = """
    AddDialog {
        align: center middle;
        layer: dialog;
    }
    AddDialog > Container {
        width: 60;
        height: 25;
        max-width: 70;
        max-height: 30;
        border: thick $accent;
        background: $panel;
    }
    AddDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    AddDialog .dialog-label {
        text-style: bold;
        height: 1;
        margin: 1 0;
    }
    AddDialog #add-dialog-content {
        padding: 1;
        height: 1fr;
    }
    AddDialog #add-dialog-buttons {
        height: 3;
        align: center middle;
        padding: 1;
    }
    AddDialog Button {
        margin: 0 1;
        min-width: 8;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "add_paper", "Add Paper"),
    ]

    source_options = [
        ("arxiv", "arXiv - Add from an arXiv ID (e.g., 2307.10635)"),
        ("dblp", "DBLP - Add from a DBLP URL"),
        ("openreview", "OpenReview - Add from an OpenReview ID (e.g., bq1JEgioLr)"),
        ("doi", "DOI - Add from a DOI (e.g., 10.1000/example)"),
        ("bib", "BibTeX File - Add papers from a .bib file"),
        ("ris", "RIS File - Add papers from a .ris file"),
        ("pdf", "PDF File - Add from a local PDF file"),
        ("manual", "Manual - Add with manual entry"),
    ]

    selected_source = reactive("arxiv")

    def __init__(self, callback: Callable[[Dict[str, Any] | None], None] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Add New Paper", classes="dialog-title")
            with VerticalScroll(id="add-dialog-content"):
                yield Static("Source Type:", classes="dialog-label")
                with RadioSet(id="source-radio-set"):
                    for value, label in self.source_options:
                        yield RadioButton(label, value=value, id=f"source-{value}")

                yield Static("", id="input-label", classes="dialog-label")
                yield Input(placeholder="Enter path, ID, or URL", id="path-input")

            with HorizontalScroll(id="add-dialog-buttons"):
                yield Button("Add", id="add-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        self.query_one("#source-arxiv", RadioButton).value = True
        self.update_input_label()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            # Get the value from the pressed radio button
            self.selected_source = event.pressed.id.replace("source-", "")
            self.update_input_label()

    def watch_selected_source(self, new_source: str) -> None:
        self.update_input_label()
        # Clear input when source changes, unless it's manual
        if new_source != "manual":
            self.query_one("#path-input", Input).value = ""
        else:
            self.query_one("#path-input", Input).value = ""
            self.query_one("#path-input", Input).placeholder = "Enter title for manual entry"

    def update_input_label(self) -> None:
        label_map = {
            "pdf": "PDF Path:",
            "arxiv": "arXiv ID:",
            "dblp": "DBLP URL:",
            "openreview": "OpenReview ID:",
            "doi": "DOI:",
            "bib": "BibTeX Path:",
            "ris": "RIS Path:",
            "manual": "Title (for manual entry):",
        }
        self.query_one("#input-label", Static).update(label_map.get(self.selected_source, "Path/ID/URL:"))

        # Hide/show path input based on manual selection
        path_input = self.query_one("#path-input", Input)
        if self.selected_source == "manual":
            path_input.display = False
        else:
            path_input.display = True

    def action_add_paper(self) -> None:
        source = self.selected_source
        path_id = self.query_one("#path-input", Input).value.strip()

        
        result = {"source": source, "path_id": path_id}
        if self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        if self.callback:
            self.callback(None)
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-button":
            self.action_add_paper()
        elif event.button.id == "cancel-button":
            self.action_cancel()
