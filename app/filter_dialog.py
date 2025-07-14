"""
Filter dialog for filtering papers by various criteria.
"""

from typing import Callable

from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, RadioList, TextArea
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.application import get_app


class FilterDialog:
    """A dialog for filtering papers by various criteria."""

    def __init__(self, callback: Callable):
        self.callback = callback
        self.result = None

        # Available fields for filtering
        self.filter_fields = [
            ("all", "All Fields (search across title, author, venue, abstract)"),
            ("year", "Year"),
            ("author", "Author"),
            ("venue", "Venue"),
            ("type", "Paper Type"),
            ("collection", "Collection"),
        ]

        self._create_layout()
        self._add_key_bindings()

    def _create_layout(self):
        """Creates the dialog layout."""

        # Field selection list
        self.field_list = RadioList(values=self.filter_fields, default="all")

        # Value input field
        self.value_input = TextArea(
            text="",
            multiline=False,
            width=Dimension(min=40, preferred=60),
            height=Dimension(preferred=1, max=1),
            focusable=True,
            style="class:textarea",
        )

        # Layout with field selection and value input
        main_content = HSplit(
            [
                # Field selection
                Window(
                    content=FormattedTextControl("Filter Field:", focusable=False),
                    height=1,
                    style="class:dialog.label",
                ),
                self.field_list,
                Window(height=1),  # Spacing
                # Value input
                VSplit(
                    [
                        Window(
                            content=FormattedTextControl(
                                "Filter Value:", focusable=False
                            ),
                            width=15,
                            style="class:dialog.label",
                        ),
                        self.value_input,
                    ]
                ),
            ]
        )

        # Body with content and help text
        self.body_container = HSplit(
            [
                main_content,
            ]
        )

        # Create dialog with buttons
        self.apply_button = Button(text="Apply", handler=self._handle_apply)
        self.cancel_button = Button(text="Cancel", handler=self._handle_cancel)
        button_row = VSplit(
            [
                self.apply_button,
                Window(width=2),  # Two spaces between buttons
                self.cancel_button,
            ]
        )

        self.dialog = Dialog(
            title="Filter Papers",
            body=self.body_container,
            buttons=[button_row],
            with_background=False,
            modal=True,
            width=Dimension(min=70, preferred=90),
        )

    def _handle_apply(self):
        """Handles the Apply Filter button press."""
        field = self.field_list.current_value
        value = self.value_input.text.strip()

        if not value:
            # TODO: Show validation error
            return

        self.result = {"field": field, "value": value}
        self.callback(self.result)

    def _handle_cancel(self):
        """Handles the Cancel button press."""
        self.callback(None)

    def get_initial_focus(self):
        """Returns the initial focus element."""
        return self.field_list

    def _add_key_bindings(self):
        """Add key bindings for the dialog."""
        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            self._handle_apply()

        @kb.add("escape")
        def _(event):
            self._handle_cancel()

        @kb.add("tab")
        def _(event):
            app = get_app()
            if app.layout.current_window == self.field_list.window:
                app.layout.focus(self.value_input)
            elif app.layout.current_window == self.value_input.window:
                app.layout.focus(self.apply_button)
            elif app.layout.current_window == self.apply_button.window:
                app.layout.focus(self.cancel_button)
            else:
                app.layout.focus(self.field_list)

        @kb.add("s-tab")
        def _(event):
            app = get_app()
            if app.layout.current_window == self.cancel_button.window:
                app.layout.focus(self.apply_button)
            elif app.layout.current_window == self.apply_button.window:
                app.layout.focus(self.value_input)
            elif app.layout.current_window == self.value_input.window:
                app.layout.focus(self.field_list)
            else:
                app.layout.focus(self.cancel_button)

        # Add backspace and delete handling for text input
        @kb.add("backspace")
        def _(event):
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.delete_before_cursor()

        @kb.add("delete")
        def _(event):
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.delete()

        @kb.add("<any>")
        def _(event):
            # Handle all character input to prevent it from reaching main app
            if event.data and len(event.data) == 1 and event.data.isprintable():
                current_control = event.app.layout.current_control
                if hasattr(current_control, "buffer"):
                    current_control.buffer.insert_text(event.data)

        # Apply key bindings to the body container
        self.body_container.key_bindings = merge_key_bindings(
            [
                self.body_container.key_bindings or KeyBindings(),
                kb,
            ]
        )

    def __pt_container__(self):
        return self.dialog
