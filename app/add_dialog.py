"""
Add dialog for adding new papers with source and path/ID input.
"""

from typing import Callable, Dict, Any

from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, TextArea, RadioList
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition


class AddDialog:
    """A dialog for adding new papers with source and path/ID fields."""

    def __init__(self, callback: Callable):
        self.callback = callback
        self.result = None

        # Available sources
        self.source_options = [
            ("pdf", "PDF File - Add from a local PDF file"),
            ("arxiv", "arXiv - Add from an arXiv ID (e.g., 2307.10635)"),
            ("dblp", "DBLP - Add from a DBLP URL"),
            ("openreview", "OpenReview - Add from an OpenReview ID (e.g., bq1JEgioLr)"),
            ("bib", "BibTeX File - Add papers from a .bib file"),
            ("ris", "RIS File - Add papers from a .ris file"),
            ("manual", "Manual - Add with manual entry"),
        ]

        self._create_layout()
        self._add_key_bindings()

    def _create_layout(self):
        """Creates the dialog layout."""

        # Source selection list
        self.source_list = RadioList(
            values=self.source_options,
            default="pdf",
        )
        self.source_list.show_scrollbar = False

        # Path/ID input field
        self.path_input = TextArea(
            text="",
            multiline=False,
            width=Dimension(min=60, preferred=80),
            height=Dimension(preferred=1, max=1),
            focusable=True,
            style="class:textarea",
        )
        
        # Dynamic label for input field
        def get_input_label():
            source = self.source_list.current_value
            if source == "pdf":
                return "PDF Path:"
            elif source == "arxiv":
                return "arXiv ID:"
            elif source == "dblp":
                return "DBLP URL:"
            elif source == "openreview":
                return "OpenReview ID:"
            elif source == "bib":
                return "BibTeX Path:"
            elif source == "ris":
                return "RIS Path:"
            else:
                return "Path/ID/URL:"
        
        self.input_label_control = FormattedTextControl(get_input_label, focusable=False)

        # Create condition to show path input only when not manual
        def show_path_input():
            return self.source_list.current_value != "manual"

        # Create form layout
        form_content = HSplit(
            [
                # Source selection
                Window(
                    content=FormattedTextControl("Source Type:", focusable=False),
                    height=1,
                    style="class:dialog.label",
                ),
                self.source_list,
                Window(height=1),  # Spacing
                # Path/ID row (conditionally shown)
                ConditionalContainer(
                    content=VSplit(
                        [
                            Window(
                                content=self.input_label_control,
                                width=15,
                                style="class:dialog.label",
                            ),
                            self.path_input,
                        ]
                    ),
                    filter=Condition(show_path_input),
                ),
            ]
        )

        # Create body container that will hold key bindings
        self.body_container = HSplit(
            [
                form_content,
            ]
        )

        # Create dialog with simple buttons
        self.add_button = Button(text="Add", handler=self._handle_add)
        self.cancel_button = Button(text="Cancel", handler=self._handle_cancel)

        # Create button row with proper spacing
        button_row = VSplit(
            [
                self.add_button,
                Window(width=2),  # Two spaces between buttons
                self.cancel_button,
            ]
        )

        self.dialog = Dialog(
            title="Add New Paper",
            body=self.body_container,
            buttons=[button_row],
            with_background=False,
            modal=True,
            width=Dimension(min=80, preferred=100),
        )

    def _handle_add(self):
        """Handles the Add button press."""
        source = self.source_list.current_value
        path_id = self.path_input.text.strip()

        self.result = {"source": source, "path_id": path_id}
        self.callback(self.result)

    def _handle_cancel(self):
        """Handles the Cancel button press."""
        self.callback(None)

    def get_initial_focus(self):
        """Returns the initial focus element."""
        return self.source_list

    def _add_key_bindings(self):
        """Add key bindings for the dialog."""
        kb = KeyBindings()

        @kb.add("c-s")
        def _(event):
            self._handle_add()

        @kb.add("escape")
        def _(event):
            self._handle_cancel()

        @kb.add("tab")
        def _(event):
            app = get_app()
            if app.layout.current_window == self.source_list.window:
                if self.source_list.current_value == "manual":
                    app.layout.focus(self.add_button)
                else:
                    app.layout.focus(self.path_input)
            elif app.layout.current_window == self.path_input.window:
                app.layout.focus(self.add_button)
            elif app.layout.current_window == self.add_button.window:
                app.layout.focus(self.cancel_button)
            else:
                app.layout.focus(self.source_list)

        @kb.add("s-tab")
        def _(event):
            app = get_app()
            if app.layout.current_window == self.cancel_button.window:
                app.layout.focus(self.add_button)
            elif app.layout.current_window == self.add_button.window:
                if self.source_list.current_value == "manual":
                    app.layout.focus(self.source_list)
                else:
                    app.layout.focus(self.path_input)
            elif app.layout.current_window == self.path_input.window:
                app.layout.focus(self.source_list)
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
