from typing import Any, Callable, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, HorizontalScroll, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, RadioButton, RadioSet, Select, Static


class FilterDialog(ModalScreen):
    """A modal dialog for filtering papers by various criteria."""

    DEFAULT_CSS = """
    FilterDialog {
        align: center middle;
        layer: dialog;
    }
    FilterDialog > Container {
        width: 80;
        height: 30;
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
    FilterDialog #value-input-container {
        height: 3;
        width: 1fr;
    }
    FilterDialog #value-input {
        height: 3;
        width: 1fr;
    }
    FilterDialog #value-select {
        height: 3;
        width: 1fr;
    }
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "apply_filter", "Apply Filter"),
    ]

    filter_fields = [
        ("all", "All Fields (search across title, author, venue, abstract)"),
        ("title", "Title"),
        ("abstract", "Abstract"),
        ("notes", "Notes"),
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
        self.paper_types = [
            "conference",
            "journal",
            "workshop",
            "preprint",
            "website",
            "other",
        ]
        self.collections = []  # Will be loaded in on_mount

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("Filter Papers", classes="dialog-title")
            with VerticalScroll(id="filter-dialog-content"):
                yield Static("Filter Field:", classes="dialog-label")
                with RadioSet(id="field-radio-set"):
                    for value, label in self.filter_fields:
                        yield RadioButton(label, value=value, id=f"field-{value}")

                yield Static("Filter Value:", classes="dialog-label")

                # Content switcher - show input or select based on selected field
                with Container(id="value-input-container"):
                    yield Input(placeholder="Enter filter value", id="value-input")
                    yield Select(options=[], id="value-select", classes="hidden")

            with HorizontalScroll(id="filter-dialog-buttons"):
                yield Button("Apply", id="apply-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        self.query_one("#field-all", RadioButton).value = True
        # Set initial focus to the radio set instead of the input
        self.query_one("#field-radio-set", RadioSet).focus()

        # Load collections from the app's database
        self._load_collections()

    def _load_collections(self) -> None:
        """Load available collections from the database."""
        try:
            from ng.services import CollectionService

            collection_service = CollectionService()
            collections = collection_service.get_all_collections()
            self.collections = [col.name for col in collections]
        except Exception as e:
            # If there's an error, use empty list
            self.collections = []

    def _update_value_widget(self, field: str) -> None:
        """Show appropriate widget (input or select) based on selected field."""
        value_input = self.query_one("#value-input", Input)
        value_select = self.query_one("#value-select", Select)

        if field == "type":
            # Show select widget for paper types
            value_input.add_class("hidden")
            value_select.remove_class("hidden")
            # Update options for paper types
            type_options = [(ptype.title(), ptype) for ptype in self.paper_types]
            value_select.set_options(type_options)
            value_select.focus()

        elif field == "collection":
            if self.collections:
                # Show select widget for collections if collections exist
                value_input.add_class("hidden")
                value_select.remove_class("hidden")
                # Update options for collections
                collection_options = [(coll, coll) for coll in self.collections]
                value_select.set_options(collection_options)
                value_select.focus()
            else:
                # Fall back to input field if no collections are available
                value_select.add_class("hidden")
                value_input.remove_class("hidden")
                value_input.placeholder = (
                    "Enter collection name (no collections in database)"
                )
                value_input.focus()

        else:
            # Show input widget for other fields
            value_select.add_class("hidden")
            value_input.remove_class("hidden")
            value_input.placeholder = "Enter filter value"
            value_input.focus()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            # Extract the value from the pressed radio button ID
            self.selected_field = event.pressed.id.replace("field-", "")
            # Update the value widget based on selected field
            self._update_value_widget(self.selected_field)

    def action_apply_filter(self) -> None:
        field = self.selected_field

        # Get value from appropriate widget
        if field == "type":
            # Paper type always uses select widget
            value_select = self.query_one("#value-select", Select)
            value = str(value_select.value) if value_select.value is not None else ""
        elif field == "collection":
            # Collection uses select if collections exist, otherwise input
            value_select = self.query_one("#value-select", Select)
            value_input = self.query_one("#value-input", Input)
            if not value_select.has_class("hidden"):
                # Using select widget
                value = (
                    str(value_select.value) if value_select.value is not None else ""
                )
            else:
                # Using input widget (fallback when no collections)
                value = value_input.value.strip()
        else:
            # Get value from input widget
            value = self.query_one("#value-input", Input).value.strip()

        if not value:
            if hasattr(self.app, "notify"):
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle ENTER key pressed in the input field."""
        if event.input.id == "value-input":
            self.action_apply_filter()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-button":
            self.action_apply_filter()
        elif event.button.id == "cancel-button":
            self.action_cancel()
