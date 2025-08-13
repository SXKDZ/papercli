from typing import Callable, Dict, Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, HorizontalScroll, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, RadioButton, RadioSet, Static


class SortDialog(ModalScreen):
    """A modal dialog for selecting sort field and order."""

    DEFAULT_CSS = """
    SortDialog {
        align: center middle;
        layer: dialog;
    }
    SortDialog > Container {
        width: 80;
        height: 20;
        max-width: 90;
        max-height: 25;
        border: solid $accent;
        background: $panel;
    }
    SortDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    SortDialog .dialog-label {
        text-style: bold;
        height: 1;
        margin: 1 1;
    }
    SortDialog #sort-dialog-content {
        padding: 0;
        height: 1fr;
    }
    SortDialog #sort-dialog-content > Vertical {
        width: 1fr;
        margin: 0 1;
    }
    SortDialog #sort-dialog-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }
    SortDialog Button {
        margin: 0 5;
        min-width: 10;
        content-align: center middle;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "apply_sort", "Apply Sort"),
    ]

    sort_fields = [
        ("title", "Title"),
        ("authors", "Authors"),
        ("venue", "Venue"),
        ("year", "Year"),
        ("paper_type", "Type"),
        ("added_date", "Date Added"),
        ("modified_date", "Date Modified"),
    ]

    sort_orders = [
        ("asc", "Ascending"),
        ("desc", "Descending"),
    ]

    selected_field = reactive("title")
    selected_order = reactive("asc")

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
            yield Static("Sort Papers", classes="dialog-title")
            with Horizontal(id="sort-dialog-content"):
                # Left column - Sort Field
                with Vertical():
                    yield Static("Sort Field:", classes="dialog-label")
                    with RadioSet(id="field-radio-set"):
                        for value, label in self.sort_fields:
                            yield RadioButton(
                                label, value=value, id=f"sort-field-{value}"
                            )

                # Right column - Sort Order
                with Vertical():
                    yield Static("Sort Order:", classes="dialog-label")
                    with RadioSet(id="order-radio-set"):
                        for value, label in self.sort_orders:
                            yield RadioButton(
                                label, value=value, id=f"sort-order-{value}"
                            )

            with HorizontalScroll(id="sort-dialog-buttons"):
                yield Button("OK", id="ok-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        self.query_one("#sort-field-title", RadioButton).value = True
        self.query_one("#sort-order-asc", RadioButton).value = True

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed and event.radio_set.id == "field-radio-set":
            # Extract the value from the pressed radio button ID
            self.selected_field = event.pressed.id.replace("sort-field-", "")
        elif event.pressed and event.radio_set.id == "order-radio-set":
            self.selected_order = event.pressed.id.replace("sort-order-", "")

    def action_apply_sort(self) -> None:
        field = self.selected_field
        reverse = self.selected_order == "desc"
        result = {"field": field, "reverse": reverse}
        if hasattr(self, "callback") and self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        if hasattr(self, "callback") and self.callback:
            self.callback(None)
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-button":
            self.action_apply_sort()
        elif event.button.id == "cancel-button":
            self.action_cancel()
