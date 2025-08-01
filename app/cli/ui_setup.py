"""UI setup utilities for PaperCLI."""

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings import scroll
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.layout import HSplit, Layout, Window, WindowAlign
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    ScrollOffsets,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Dialog, Frame

from ..version import get_version


class UISetupMixin:
    """Mixin class containing UI setup methods for PaperCLI."""
    
    def setup_key_bindings(self):
        """Setup key bindings."""
        self.kb = KeyBindings()

        # Navigation
        @self.kb.add(
            "up",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_up(event):
            # If completion menu is open, navigate it
            if self.input_buffer.complete_state:
                self.input_buffer.complete_previous()
            else:
                # Otherwise, navigate the paper list
                self.paper_list_control.move_up()
                self._scroll_to_selected()
                event.app.invalidate()

        @self.kb.add(
            "down",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_down(event):
            # If completion menu is open, navigate it
            if self.input_buffer.complete_state:
                self.input_buffer.complete_next()
            else:
                # Otherwise, navigate the paper list
                self.paper_list_control.move_down()
                self._scroll_to_selected()
                event.app.invalidate()

        # Page navigation keys
        @self.kb.add(
            "pageup",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_page_up(event):
            self.paper_list_control.move_page_up()
            self._scroll_to_selected()
            event.app.invalidate()

        @self.kb.add(
            "pagedown",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_page_down(event):
            self.paper_list_control.move_page_down()
            self._scroll_to_selected()
            event.app.invalidate()

        @self.kb.add(
            "home",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_to_top(event):
            self.paper_list_control.move_to_top()
            self._scroll_to_selected()
            event.app.invalidate()

        @self.kb.add(
            "end",
            filter=~has_focus(self.help_control)
            & ~has_focus(self.details_control)
            & Condition(
                lambda: self.edit_dialog is None
                or not (
                    hasattr(get_app().layout.current_control, "buffer")
                    and get_app().layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                )
            ),
        )
        def move_to_bottom(event):
            self.paper_list_control.move_to_bottom()
            self._scroll_to_selected()
            event.app.invalidate()

        # Selection (in select mode) - smart space key handling
        @self.kb.add(
            "space",
            filter=~(
                Condition(
                    lambda: self.add_dialog is not None
                    or self.filter_dialog is not None
                    or self.sort_dialog is not None
                )
            ),
        )
        def toggle_selection(event):
            # If edit dialog is open and a TextArea is focused, insert space into it.
            if self.edit_dialog and hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                if current_buffer in [
                    f.buffer for f in self.edit_dialog.input_fields.values()
                ]:
                    current_buffer.insert_text(" ")
                    return  # Consume the event

            # Check if user is actively typing a command in the main input buffer
            current_text = self.input_buffer.text
            cursor_pos = self.input_buffer.cursor_position

            # If user is typing (has text or cursor not at start), allow normal space
            if len(current_text) > 0 or cursor_pos > 0:
                self.input_buffer.insert_text(" ")
            elif self.in_select_mode:
                # Only toggle selection if input is truly empty and we're in select mode
                self.paper_list_control.toggle_selection()
                selected_count = len(self.paper_list_control.selected_paper_ids)
                self.status_bar.set_status(
                    f"Toggled selection. Selected: {selected_count} papers", "success"
                )
                event.app.invalidate()  # Force refresh of UI
            else:
                # Default behavior - add space to main input buffer
                self.input_buffer.insert_text(" ")

        # Command input
        @self.kb.add("enter")
        def handle_enter(event):
            # If completion menu is open and a completion is selected, accept it
            if (
                self.input_buffer.complete_state
                and self.input_buffer.complete_state.current_completion
            ):
                self.input_buffer.apply_completion(
                    self.input_buffer.complete_state.current_completion
                )
                event.app.invalidate()
                return

            if self.input_buffer.text.strip():
                command = self.input_buffer.text.strip()
                self.input_buffer.text = ""
                self.handle_command(command)
                # Force UI refresh after command execution
                event.app.invalidate()
            elif self.in_select_mode:
                # If in selection mode with no command, exit selection mode but preserve selection
                self.in_select_mode = False
                self.paper_list_control.in_select_mode = False
                # Don't clear selected papers - preserve selection for future operations
                selected_count = len(self.paper_list_control.selected_paper_ids)
                if selected_count > 0:
                    self.status_bar.set_status(
                        f"Exited selection mode ({selected_count} papers remain selected)",
                        "info",
                    )
                else:
                    self.status_bar.set_status("Exited selection mode", "info")
                event.app.invalidate()

        # Function key bindings
        @self.kb.add("f1")
        def add_paper(event):
            self.show_add_dialog()

        @self.kb.add("f2")
        def open_paper(event):
            self.paper_commands.handle_open_command()

        @self.kb.add("f3")
        def show_detail(event):
            self.paper_commands.handle_detail_command()

        @self.kb.add("f4")
        def chat_paper(event):
            self.export_commands.handle_chat_command()

        @self.kb.add("f5")
        def edit_paper(event):
            self.paper_commands.handle_edit_command()

        @self.kb.add("f6")
        def delete_paper(event):
            self.paper_commands.handle_delete_command()

        @self.kb.add("f7")
        def manage_collections(event):
            self.collection_commands.handle_collect_command([])

        @self.kb.add("f8")
        def filter_papers(event):
            self.show_filter_dialog()

        @self.kb.add("f9")
        def show_all_papers(event):
            self.search_commands.handle_all_command()

        @self.kb.add("f10")
        def sort_papers(event):
            self.show_sort_dialog()

        @self.kb.add("f11")
        def toggle_select_mode(event):
            self.search_commands.handle_select_command()

        @self.kb.add("f12")
        def clear_selection(event):
            self.search_commands.handle_clear_command()

        # Exit selection mode
        @self.kb.add("escape")
        def handle_escape(event):
            # Priority order: completion menu, error panel, help panel, details panel, selection mode, clear input
            if self.input_buffer.complete_state:
                self.input_buffer.cancel_completion()
                event.app.invalidate()
                return
            elif self.show_error_panel:
                self.show_error_panel = False
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed error panel", "close")
                event.app.invalidate()
                return
            elif self.show_help:
                self.show_help = False
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed help panel", "close")
                event.app.invalidate()
                return
            elif self.show_details_panel:
                self.show_details_panel = False
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed details panel", "close")
                event.app.invalidate()
                return
            elif self.edit_dialog is not None:
                self.app.layout.container.floats.remove(self.edit_float)
                self.edit_dialog = None
                self.edit_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed edit dialog", "close")
                event.app.invalidate()
                return
            elif self.add_dialog is not None:
                self.app.layout.container.floats.remove(self.add_float)
                self.add_dialog = None
                self.add_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed add dialog", "close")
                event.app.invalidate()
                return
            elif self.filter_dialog is not None:
                self.app.layout.container.floats.remove(self.filter_float)
                self.filter_dialog = None
                self.filter_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed filter dialog", "close")
                event.app.invalidate()
                return
            elif self.sort_dialog is not None:
                self.app.layout.container.floats.remove(self.sort_float)
                self.sort_dialog = None
                self.sort_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("Closed sort dialog", "close")
                event.app.invalidate()
                return
            elif self.in_select_mode:
                self.in_select_mode = False
                self.paper_list_control.in_select_mode = False
                selected_count = len(self.paper_list_control.selected_paper_ids)
                if selected_count > 0:
                    self.status_bar.set_status(
                        f"Exited selection mode ({selected_count} papers remain selected)",
                        "info",
                    )
                else:
                    self.status_bar.set_status("Exited selection mode", "info")
                event.app.invalidate()
                return
            else:
                self.input_buffer.text = ""
                self.status_bar.set_status("Input cleared", "clear")

        # Auto-completion - Tab key
        @self.kb.add("tab")
        def complete(event):
            # If the current focused control has a buffer, let it handle the tab.
            # This allows TextArea to handle its own tab behavior (e.g., inserting tab character).
            if hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                # If it's a TextArea, let it handle the tab
                if (
                    isinstance(event.app.layout.current_control, BufferControl)
                    and current_buffer.multiline()
                ):
                    current_buffer.insert_text(
                        "    "
                    )  # Insert 4 spaces for tab in TextArea
                    return

            # Otherwise, if focused on the input buffer, trigger completion
            if event.app.current_buffer != self.input_buffer:
                event.app.layout.focus(self.input_buffer)
                return

            buffer = self.input_buffer
            if buffer.complete_state:
                buffer.complete_next()
            else:
                buffer.start_completion(select_first=True)

        # Shift+Tab for previous completion
        @self.kb.add("s-tab")
        def complete_previous(event):
            # If a dialog is open, let the dialog handle the shift-tab key.
            if (
                self.add_dialog
                or self.filter_dialog
                or self.sort_dialog
                or self.edit_dialog
                or self.collect_dialog
            ):
                return

            # If the current focused control has a buffer, let it handle the shift-tab.
            # For TextArea, we might want to do nothing or move cursor.
            if hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                if (
                    isinstance(event.app.layout.current_control, BufferControl)
                    and current_buffer.multiline()
                ):
                    # For TextArea, s-tab might move cursor or do nothing. Let default handle.
                    return

            if event.app.current_buffer == self.input_buffer:
                buffer = self.input_buffer
                if buffer.complete_state:
                    buffer.complete_previous()

        # Handle backspace
        @self.kb.add("backspace")
        def handle_backspace(event):
            # If the current focused control has a buffer, let it handle the backspace.
            if hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                # If it's a TextArea or the main input buffer, let it handle backspace
                if current_buffer == self.input_buffer or (
                    self.edit_dialog
                    and current_buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                ):
                    current_buffer.delete_before_cursor()
                    # Force completion refresh after deletion if it's the input buffer
                    if (
                        current_buffer == self.input_buffer
                        and current_buffer.text.startswith("/")
                    ):
                        event.app.invalidate()
                        if current_buffer.complete_state:
                            current_buffer.cancel_completion()

                        def restart_completion():
                            if current_buffer.text.startswith("/"):
                                current_buffer.start_completion(select_first=False)

                        event.app.loop.call_soon(restart_completion)
                    return  # Consume the event

            # Fallback for other cases (shouldn't be reached if focused buffer handles it)
            if event.app.current_buffer == self.input_buffer:
                self.input_buffer.delete_before_cursor()

        # Handle delete key
        @self.kb.add("delete")
        def handle_delete(event):
            # If the current focused control has a buffer, let it handle the delete.
            if hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                # If it's a TextArea or the main input buffer, let it handle delete
                if current_buffer == self.input_buffer or (
                    self.edit_dialog
                    and current_buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                ):
                    current_buffer.delete()
                    return  # Consume the event

            # Fallback for other cases
            if event.app.current_buffer == self.input_buffer:
                self.input_buffer.delete()

        # Handle normal character input
        @self.kb.add("<any>")
        def handle_any_key(event):
            # If the current focused control has a buffer, let it handle the key.
            # This allows TextArea to handle its own input.
            if hasattr(event.app.layout.current_control, "buffer"):
                # Check if the current buffer is the input buffer or part of an edit dialog
                if event.app.layout.current_control.buffer == self.input_buffer or (
                    self.edit_dialog
                    and event.app.layout.current_control.buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                ):
                    # Let the buffer handle the key if it's a printable character (except space which has its own handler)
                    if hasattr(event, "data") and event.data and len(event.data) == 1:
                        char = event.data
                        if char.isprintable() and char != " ":
                            event.app.layout.current_control.buffer.insert_text(char)
                            return  # Consume the event

            # If not handled by a focused buffer, and it's a printable character, fall back to input buffer
            if hasattr(event, "data") and event.data and len(event.data) == 1:
                char = event.data
                if char.isprintable() and char != " ":
                    # If no specific buffer handled it, and it's a printable char, direct to input buffer
                    if event.app.current_buffer != self.input_buffer:
                        event.app.layout.focus(self.input_buffer)
                    self.input_buffer.insert_text(char)

        # Exit application
        @self.kb.add("c-c")
        def exit_app(event):
            event.app.exit()

    def setup_layout(self):
        """Setup application layout."""
        # Input buffer with completion enabled
        self.input_buffer = Buffer(
            completer=self.smart_completer,
            complete_while_typing=True,
            accept_handler=None,  # We handle enter key explicitly
            enable_history_search=True,
            validate_while_typing=False,  # Ensure completion isn't blocked by validation
            multiline=False,
        )

        # Paper list header (fixed)
        self.paper_list_header = Window(
            content=FormattedTextControl(
                text=lambda: self.paper_list_control.get_header_text()
            ),
            height=1,
            wrap_lines=False,
        )

        # Paper list content (scrollable)
        self.paper_list_control_widget = FormattedTextControl(
            text=lambda: self.paper_list_control.get_content_text(),
            focusable=True,
            show_cursor=False,
            get_cursor_position=lambda: Point(
                0, self.paper_list_control.selected_index
            ),
        )
        self.paper_list_content = Window(
            content=self.paper_list_control_widget,
            scroll_offsets=ScrollOffsets(top=1, bottom=1),
            wrap_lines=False,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )

        # Combined paper list window
        self.paper_list_window = HSplit(
            [
                self.paper_list_header,
                self.paper_list_content,
            ]
        )

        # Input window with prompt
        input_window = Window(
            content=BufferControl(
                buffer=self.input_buffer,
                include_default_input_processors=True,
                input_processors=[BeforeInput("> ", style="class:prompt")],
            ),
            height=1,
        )

        # Status window
        status_window = Window(
            content=FormattedTextControl(
                text=lambda: self.status_bar.get_formatted_text()
            ),
            height=1,
            align=WindowAlign.LEFT,
        )

        # Help Dialog (as a float)
        self.help_buffer = Buffer(
            document=Document(self.HELP_TEXT, 0),
            read_only=True,
            multiline=True,
        )
        self.help_control = BufferControl(
            buffer=self.help_buffer,
            focusable=True,
            key_bindings=self._get_help_key_bindings(),
        )
        self.help_dialog = Dialog(
            title="PaperCLI Help",
            body=Window(
                content=self.help_control,
                wrap_lines=True,
                dont_extend_height=False,
                always_hide_cursor=True,
                scroll_offsets=ScrollOffsets(top=1, bottom=1),
                right_margins=[ScrollbarMargin(display_arrows=True)],
            ),
            with_background=False,
            modal=True,
        )

        # Details Dialog (as a float)
        self.details_buffer = Buffer(read_only=True, multiline=True)
        self.details_control = BufferControl(
            buffer=self.details_buffer,
            focusable=True,
            key_bindings=self._get_details_key_bindings(),
        )
        self.details_dialog = Dialog(
            title="Paper Details",
            body=Window(
                content=self.details_control,
                wrap_lines=True,
                dont_extend_height=False,
                always_hide_cursor=True,
            ),
            with_background=False,
            modal=True,
        )

        # Error panel
        self.error_buffer = Buffer(read_only=True, multiline=True)
        self.error_control = BufferControl(
            buffer=self.error_buffer,
            focusable=True,
            key_bindings=self._get_error_key_bindings(),
        )
        error_panel = ConditionalContainer(
            content=Frame(
                Window(
                    content=self.error_control,
                    wrap_lines=True,
                ),
                title="Error Details",
            ),
            filter=Condition(lambda: self.show_error_panel),
        )

        # Main layout with floating completion menu
        main_container = HSplit(
            [
                # Header
                Window(
                    content=FormattedTextControl(text=lambda: self.get_header_text()),
                    height=1,
                ),
                # Paper list
                Frame(body=self.paper_list_window),
                # Shortkey bar
                Window(
                    content=FormattedTextControl(
                        text=lambda: self.get_shortkey_bar_text()
                    ),
                    height=1,
                    style="class:shortkey_bar",
                ),
                # Input
                Frame(body=input_window),
                # Status
                status_window,
                # Error panel overlay
                error_panel,
            ]
        )

        # Wrap in FloatContainer to support completion menu and help dialog
        self.layout = Layout(
            FloatContainer(
                content=main_container,
                floats=[
                    Float(
                        content=CompletionsMenu(max_height=16, scroll_offset=1),
                        bottom=3,  # Position above status bar
                        left=2,
                        transparent=True,
                    ),
                    # Help Dialog Float
                    Float(
                        content=ConditionalContainer(
                            content=self.help_dialog,
                            filter=Condition(lambda: self.show_help),
                        ),
                        top=2,
                        bottom=2,
                        left=10,
                        right=10,
                    ),
                    # Details Dialog Float
                    Float(
                        content=ConditionalContainer(
                            content=self.details_dialog,
                            filter=Condition(lambda: self.show_details_panel),
                        ),
                        top=2,
                        bottom=2,
                        left=5,
                        right=5,
                    ),
                ],
            )
        )

    def setup_application(self):
        """Setup the main application."""
        # Define a modern, cohesive style
        style = Style(
            [
                # UI Components
                ("header_content", "#f8f8f2 bg:#282a36"),
                ("header_help_text", "italic #f8f8f2 bg:#282a36"),
                ("mode_select", "bold #ff5555 bg:#282a36"),
                ("mode_list", "bold #ffffff bg:#6272a4"),
                ("mode_filtered", "bold #f1fa8c bg:#282a36"),
                # Paper list
                ("selected", "bold #f8f8f2 bg:#44475a"),  # Current paper row
                (
                    "selected-bg",
                    "bold #f8f8f2 bg:#888888",
                ),  # Selected item with much lighter gray background
                (
                    "editing",
                    "bold #ffffff bg:#bd93f9",
                ),  # Edit mode with white text on purple background
                ("empty", "#6272a4 italic"),
                # Input & Prompt
                ("prompt", "bold #50fa7b"),
                ("input", "#f8f8f2 bg:#1e1f29"),
                # Status bar
                ("status", "#f8f8f2 bg:#282a36"),
                ("status-info", "#f8f8f2 bg:#282a36"),
                ("status-success", "bold #50fa7b bg:#282a36"),
                ("status-error", "bold #ff5555 bg:#282a36"),
                ("status-warning", "bold #f1fa8c bg:#282a36"),
                ("progress", "#f8f8f2 bg:#44475a"),
                # Dialogs & Panels
                ("textarea", "bg:#222222 #f8f8f2"),
                ("textarea.readonly", "bg:#333333 #888888"),
                ("error_header", "bold #f8f8f2 bg:#ff5555"),
                ("error_title", "bold #ff5555"),
                ("error_message", "#ffb8b8"),
                ("error_details", "#6272a4 italic"),
                ("help_header", "bold #f8f8f2 bg:#8be9fd"),
                ("help_footer", "bold #f1fa8c"),
                # Shortkey bar
                ("shortkey_bar", "italic #f8f8f2 bg:#44475a"),
                # Frame styles for CollectDialog
                ("frame.focused", "bold #8be9fd"),  # Blue border for focused frame
                ("frame.unfocused", "#6272a4"),  # Grey border for unfocused frame
                # Styling for pending changes
                ("italic", "italic #f8f8f2"),  # Italic text for pending changes
            ]
        )

        # Merge our key bindings with default ones
        default_bindings = load_key_bindings()
        all_bindings = merge_key_bindings([default_bindings, self.kb])

        self.app = Application(
            layout=self.layout,
            key_bindings=all_bindings,
            style=style,
            full_screen=True,
            mouse_support=False,
            editing_mode="emacs",
            include_default_pygments_style=False,
        )

    def _get_help_key_bindings(self):
        """Key bindings for the help dialog for intuitive scrolling."""
        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            # Direct buffer manipulation for reliable scrolling
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_up()

        @kb.add("down")
        def _(event):
            # Direct buffer manipulation for reliable scrolling
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_down()

        @kb.add("pageup")
        def _(event):
            # Move cursor up by ~10 lines (page-like scrolling)
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                for _ in range(10):
                    buffer.cursor_up()

        @kb.add("pagedown")
        def _(event):
            # Move cursor down by ~10 lines (page-like scrolling)
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                for _ in range(10):
                    buffer.cursor_down()

        @kb.add("home")
        def _(event):
            # Jump to the beginning of the document
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_position = 0

        @kb.add("end")
        def _(event):
            # Jump to the end of the document
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_position = len(buffer.text)

        @kb.add("<any>")
        def _(event):
            # Swallow any other key presses to prevent them from reaching the input buffer.
            pass

        return kb

    def _get_details_key_bindings(self):
        """Key bindings for the details dialog for intuitive scrolling."""
        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_up()

        @kb.add("down")
        def _(event):
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_down()

        @kb.add("pageup")
        def _(event):
            scroll.scroll_page_up(event)

        @kb.add("pagedown")
        def _(event):
            scroll.scroll_page_down(event)

        @kb.add("<any>")
        def _(event):
            # Swallow any other key presses to prevent them from reaching the input buffer.
            pass

        return kb

    def _get_error_key_bindings(self):
        """Key bindings for the error dialog for intuitive scrolling."""
        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_up()

        @kb.add("down")
        def _(event):
            if hasattr(event.app.layout, "current_control") and hasattr(
                event.app.layout.current_control, "buffer"
            ):
                buffer = event.app.layout.current_control.buffer
                buffer.cursor_down()

        @kb.add("pageup")
        def _(event):
            scroll.scroll_page_up(event)

        @kb.add("pagedown")
        def _(event):
            scroll.scroll_page_down(event)

        @kb.add("<any>")
        def _(event):
            # Swallow any other key presses to prevent them from reaching the input buffer.
            pass

        return kb

    def get_header_text(self) -> FormattedText:
        """Get header text."""
        try:
            width = get_app().output.get_size().columns
        except Exception:
            width = 120  # Fallback

        if self.in_select_mode:
            mode = "SELECT"
        elif self.is_filtered_view:
            mode = "FILTERED"
        else:
            mode = f"✦ PaperCLI v{get_version()} ✦"
        selected_count = len(self.paper_list_control.selected_paper_ids)

        # Left side of the header (just mode)
        left_parts = []
        if self.in_select_mode:
            left_parts.append(("class:mode_select", f" {mode} "))
        elif self.is_filtered_view:
            left_parts.append(("class:mode_filtered", f" {mode} "))
        else:
            left_parts.append(("class:mode_list", f" {mode} "))

        # Right side of the header (status info)
        right_parts = []
        right_parts.append(("class:header_content", "Total: "))
        right_parts.append(("class:header_content", str(len(self.current_papers))))

        right_parts.append(("class:header_content", "  Current: "))
        right_parts.append(
            ("class:header_content", str(self.paper_list_control.selected_index + 1))
        )

        right_parts.append(("class:header_content", "  Selected: "))
        right_parts.append(("class:header_content", str(selected_count)))
        right_parts.append(("class:header_content", " "))

        # Calculate lengths
        left_len = sum(len(p[1]) for p in left_parts)
        right_len = sum(len(p[1]) for p in right_parts)

        # Calculate padding
        padding_len = width - left_len - right_len
        if padding_len < 1:
            padding_len = 1

        padding = [("class:header_content", " " * padding_len)]

        # Combine all parts
        final_parts = left_parts + padding + right_parts

        # Truncate if the line overflows (should be rare)
        total_len = sum(len(p[1]) for p in final_parts)
        if total_len > width:
            full_text = "".join(p[1] for p in final_parts)
            truncated_text = full_text[: width - 3] + "..."
            return FormattedText([("class:header_content", truncated_text)])

        return FormattedText(final_parts)

    def get_shortkey_bar_text(self) -> FormattedText:
        """Get shortkey bar text with function key shortcuts."""

        try:
            width = get_app().output.get_size().columns
        except Exception:
            width = 120  # Fallback

        # Function key shortcuts with configurable spacing
        shortkey_spacing = "    "  # Adjust this to control spacing between shortcuts
        shortcuts = [
            "F1: Add",
            "F2: Open",
            "F3: Detail",
            "F4: Chat",
            "F5: Edit",
            "F6: Delete",
            "F7: Collect",
            "F8: Filter",
            "F9: All",
            "F10: Sort",
            "F11: Toggle Select",
            "F12: Clear",
            "↑↓: Nav",
        ]
        help_text = shortkey_spacing.join(shortcuts)

        # Create formatted text parts with shortkey bar style
        parts = [("class:shortkey_bar", help_text)]

        # Calculate padding to center the text
        text_len = len(help_text)
        if text_len < width:
            padding_len = (width - text_len) // 2
            left_padding = [("class:shortkey_bar", " " * padding_len)]
            right_padding = [
                ("class:shortkey_bar", " " * (width - text_len - padding_len))
            ]
            final_parts = left_padding + parts + right_padding
        else:
            # If text is too long, truncate
            truncated_text = (
                help_text[: width - 3] + "..." if width > 3 else help_text[:width]
            )
            final_parts = [("class:shortkey_bar", truncated_text)]

        return FormattedText(final_parts)