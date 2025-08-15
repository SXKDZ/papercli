from typing import TYPE_CHECKING, Any, Callable, Dict

from textual.app import ComposeResult
from textual.containers import Container, HorizontalScroll, VerticalScroll
from textual.events import Key
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from ng.services.validation import ValidationService

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class AddDialog(ModalScreen):
    """A modal dialog for adding new papers with source and path/ID fields."""

    DEFAULT_CSS = """
    AddDialog {
        align: center middle;
        layer: dialog;
    }
    AddDialog > Container {
        width: 80;
        height: 28;
        max-width: 90;
        max-height: 30;
        border: solid $accent;
        background: $panel;
    }
    AddDialog > Container.compact {
        height: 22;
        max-height: 24;
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
        margin: 1 1;
    }
    AddDialog #add-dialog-content {
        padding: 0;
        height: 1fr;
    }
    AddDialog #add-dialog-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }
    AddDialog Button {
        margin: 0 5;
        min-width: 10;
        content-align: center middle;
        text-align: center;
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

    def __init__(
        self,
        callback: Callable[[Dict[str, Any] | None], None] = None,
        app: "PaperCLIApp" = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.callback = callback
        self.parent_app = app  # Renamed to avoid conflict with Textual's app property

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
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
        # Clear input when source changes
        self.query_one("#path-input", Input).value = ""

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

        placeholder_map = {
            "pdf": "Enter path to PDF file",
            "arxiv": "Enter arXiv ID (e.g., 2301.12345)",
            "dblp": "Enter DBLP URL",
            "openreview": "Enter OpenReview ID",
            "doi": "Enter DOI (e.g., 10.1000/182)",
            "bib": "Enter path to BibTeX file",
            "ris": "Enter path to RIS file",
            "manual": "Enter title for manual entry",
        }

        self.query_one("#input-label", Static).update(
            label_map.get(self.selected_source, "Path/ID/URL:")
        )

        # Update placeholder based on selected source
        self.query_one("#path-input", Input).placeholder = placeholder_map.get(
            self.selected_source, "Enter path, ID, or URL"
        )

        # Hide/show path input based on manual selection
        path_input = self.query_one("#path-input", Input)
        path_label = self.query_one("#input-label", Static)
        container = self.query_one("#dialog-container")
        if self.selected_source == "manual":
            path_input.display = False
            path_label.display = False
            container.set_class(True, "compact")
        else:
            path_input.display = True
            path_label.display = True
            container.set_class(False, "compact")

        self.refresh(layout=True)

    def action_add_paper(self) -> None:
        source = self.selected_source
        path_id = self.query_one("#path-input", Input).value.strip()

        # Validate input based on source type
        is_valid, error_message = ValidationService.validate_input(source, path_id)

        if not is_valid:
            # Show validation error as toast
            if self.parent_app:
                self.parent_app.notify(
                    f"Validation Error: {error_message}", severity="error"
                )
            return  # Don't proceed with invalid input

        result = {"source": source, "path_id": path_id}
        if self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-button":
            self.action_add_paper()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Pressing Enter in the input should trigger Add
        self.action_add_paper()

    def on_key(self, event: Key) -> None:
        # Ensure Enter anywhere in dialog activates Add, except when typing in other inputs
        if event.key == "enter":
            focused = self.focused
            try:
                if focused and focused.id == "path-input":
                    return  # let Input.Submitted handler fire
            except Exception:
                pass
            self.action_add_paper()
            event.prevent_default()
