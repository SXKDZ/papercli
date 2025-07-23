"""
Sort dialog for selecting field and sort order.
"""

from typing import Callable

from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Dialog, RadioList


class SortDialog:
    """A dialog for selecting sort field and order."""

    def __init__(self, callback: Callable):
        self.callback = callback
        self.result = None

        # Available fields for sorting
        self.sort_fields = [
            ("title", "Title"),
            ("authors", "Authors"),
            ("venue", "Venue"),
            ("year", "Year"),
            ("paper_type", "Type"),
            ("added_date", "Date Added"),
            ("modified_date", "Date Modified"),
        ]

        # Sort order options
        self.sort_orders = [
            ("asc", "Ascending"),
            ("desc", "Descending"),
        ]

        self._create_layout()
        self._add_key_bindings()

    def _create_layout(self):
        """Creates the dialog layout."""

        # Field selection list
        self.field_list = RadioList(
            values=self.sort_fields,
            default="title",
        )
        self.field_list.show_scrollbar = False

        # Sort order selection list
        self.order_list = RadioList(
            values=self.sort_orders,
            default="asc",
        )
        self.order_list.show_scrollbar = False

        # Add custom key bindings to override RadioList defaults
        kb_override = KeyBindings()

        @kb_override.add("enter")
        def _(event):
            self._handle_ok()

        # Apply to both RadioList controls
        self.field_list.control.key_bindings = merge_key_bindings(
            [self.field_list.control.key_bindings or KeyBindings(), kb_override]
        )
        self.order_list.control.key_bindings = merge_key_bindings(
            [self.order_list.control.key_bindings or KeyBindings(), kb_override]
        )

        # Labels and lists in columns
        field_column = HSplit(
            [
                Window(
                    content=FormattedTextControl("Sort Field:", focusable=False),
                    height=1,
                    style="class:dialog.label",
                ),
                self.field_list,
            ]
        )

        order_column = HSplit(
            [
                Window(
                    content=FormattedTextControl("Sort Order:", focusable=False),
                    height=1,
                    style="class:dialog.label",
                ),
                self.order_list,
            ]
        )

        # Two-column layout
        main_content = VSplit(
            [
                field_column,
                Window(width=3),  # Spacing between columns
                order_column,
            ]
        )

        # Body with content
        self.body_container = HSplit(
            [
                main_content,
            ]
        )

        # Create dialog with custom button row
        ok_button = Button(text="OK", handler=self._handle_ok)
        cancel_button = Button(text="Cancel", handler=self._handle_cancel)
        button_row = VSplit(
            [
                ok_button,
                Window(width=2),  # Two spaces between buttons
                cancel_button,
            ]
        )

        self.dialog = Dialog(
            title="Sort Papers",
            body=self.body_container,
            buttons=[button_row],
            with_background=False,
            modal=True,
            width=Dimension(min=60, preferred=80),
        )

    def _handle_ok(self):
        """Handles the OK button press."""
        field = self.field_list.current_value
        order = self.order_list.current_value
        self.result = (field, order)
        self.callback(self.result)

    def _handle_cancel(self):
        """Handles the Cancel button press."""
        self.callback(None)

    def get_initial_focus(self):
        """Returns the initial focus element."""
        return self.field_list

    def _add_key_bindings(self):
        """Key bindings are now handled in _create_layout after dialog creation."""
        pass

    def __pt_container__(self):
        return self.dialog
