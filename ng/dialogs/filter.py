from typing import Callable, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, HorizontalScroll, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Static


class FilterDialog(ModalScreen):
    """A modal dialog for filtering papers by various criteria."""

    DEFAULT_CSS = """
    FilterDialog {
        align: center middle;
        layer: dialog;
    }
    FilterDialog > Container {
        width: 80;
        height: 26;
        max-width: 90;
        max-height: 28;
        border: solid $accent;
        background: $panel;
    }
    FilterDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    FilterDialog .dialog-label {
        text-style: bold;
        height: 1;
        margin: 1 1;
    }
    FilterDialog #filter-dialog-content {
        padding: 0;
        height: 1fr;
    }
    FilterDialog #filter-dialog-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }
    FilterDialog Button {
        margin: 0 5;
        min-width: 10;
        content-align: center middle;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "apply_filter", "Apply Filter"),
    ]

    filter_fields = [
        ("all", "All Fields (search across title, author, venue, abstract)"),
        ("year", "Year"),
        ("author", "Author"),
        ("venue", "Venue"),
        ("type", "Paper Type"),
        ("collection", "Collection"),
    ]

    selected_field = reactive("all")

    def __init__(
        self,
        callback: Callable[[Dict[str, Any] | None], None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("Filter Papers", classes="dialog-title")
            with VerticalScroll(id="filter-dialog-content"):
                yield Static("Filter Field:", classes="dialog-label")
                with RadioSet(id="field-radio-set"):
                    for value, label in self.filter_fields:
                        yield RadioButton(label, value=value, id=f"field-{value}")

                yield Static("Filter Value:", classes="dialog-label")
                yield Input(placeholder="Enter filter value", id="value-input")

            with HorizontalScroll(id="filter-dialog-buttons"):
                yield Button("Apply", id="apply-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        self.query_one("#field-all", RadioButton).value = True

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            # Extract the value from the pressed radio button ID
            self.selected_field = event.pressed.id.replace("field-", "")

    def action_apply_filter(self) -> None:
        field = self.selected_field
        value = self.query_one("#value-input", Input).value.strip()

        if not value:
            if hasattr(self.app, 'notify'):
                self.app.notify("Filter value cannot be empty", severity="warning")
            return

        result = {"field": field, "value": value}
        if hasattr(self, "callback") and self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        if hasattr(self, "callback") and self.callback:
            self.callback(None)
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-button":
            self.action_apply_filter()
        elif event.button.id == "cancel-button":
            self.action_cancel()
