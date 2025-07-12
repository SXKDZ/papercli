"""
Filter dialog for filtering papers by various criteria.
"""

from typing import Callable, Optional, Dict, Any

from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
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
        self.field_list = RadioList(
            values=self.filter_fields,
            default="all"
        )
        
        # Value input field
        self.value_input = TextArea(
            text="",
            multiline=False,
            width=Dimension(min=40, preferred=60),
            height=Dimension(preferred=1, max=1),
            focusable=True,
            style="class:textarea"
        )
        
        # Layout with field selection and value input
        main_content = HSplit([
            # Field selection
            Window(
                content=FormattedTextControl("Filter Field:", focusable=False),
                height=1,
                style="class:dialog.label"
            ),
            self.field_list,
            
            Window(height=1),  # Spacing
            
            # Value input
            VSplit([
                Window(
                    content=FormattedTextControl("Filter Value:", focusable=False),
                    width=15,
                    style="class:dialog.label"
                ),
                self.value_input
            ]),
        ])
        
        # Help text
        help_text_window = Window(
            content=FormattedTextControl("Enter: Apply Filter  ESC: Cancel", style="class:header_help_text"),
            height=1,
            align=WindowAlign.RIGHT
        )
        
        # Body with content and help text
        self.body_container = HSplit([
            main_content,
            Window(height=1),  # Spacing
            help_text_window,
        ])
        
        # Create dialog with buttons
        apply_button = Button(text="Apply Filter", handler=self._handle_apply)
        cancel_button = Button(text="Cancel", handler=self._handle_cancel)
        
        self.dialog = Dialog(
            title="Filter Papers",
            body=self.body_container,
            buttons=[apply_button, cancel_button],
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
            
        self.result = {
            "field": field,
            "value": value
        }
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

        # Apply key bindings like EditDialog does
        self.body_container.key_bindings = merge_key_bindings([self.body_container.key_bindings or KeyBindings(), kb])

    def __pt_container__(self):
        return self.dialog