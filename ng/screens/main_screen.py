from typing import List

from textual.events import Key
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from ng.db.models import Paper
from ng.dialogs import AddDialog, DetailDialog, FilterDialog, MessageDialog
from ng.services import CollectionService
from ng.widgets.command_input import CommandInput
from ng.widgets.log_panel import LogPanel
from ng.widgets.paper_list import PaperList


class MainScreen(Screen):
    """The main screen for PaperCLI."""

    CSS = """
    MainScreen {
        margin: 0;
        padding: 0;
    }
    #paper-list-view {
        width: 100%;
        margin: 0;
        padding: 0;
        content-align: left top;
    }
    #command-input {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #log-panel {
        dock: right;
        width: 50%;
        height: 100%;
        background: $panel;
        border: thick $accent;
        layer: dialog;
    }
    .autocomplete-dropdown {
        height: 8;
        max-height: 8;
        min-height: 8;
        width: auto;
        max-width: 18;
        layer: notification;
        background: $surface;
        scrollbar-size-vertical: 1;
        padding: 0;
        margin: 0;
        overflow-y: auto;
    }

    .autocomplete-dropdown > OptionList {
        height: 8;
        width: 100%;
        max-height: 8;
        min-height: 8;
        scrollbar-size-vertical: 1;
        overflow-y: auto;
        padding: 0;
    }
    """

    def __init__(self, papers: List[Paper], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.papers = papers

    def compose(self):
        yield Header()
        yield PaperList(self.papers, id="paper-list-view")
        yield CommandInput(
            app=self.app, placeholder="Enter command...", id="command-input"
        )
        log_panel = LogPanel(id="log-panel")  # Add LogPanel
        log_panel.set_app_reference(self.app)  # Set app reference for auto-refresh
        yield log_panel
        yield Footer()

    def action_cursor_up(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_up()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_cursor_down(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_down()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_page_up(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_page_up()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_page_down(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_page_down()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_cursor_home(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_to_top()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_cursor_end(self) -> None:
        paper_list = self.query_one("#paper-list-view")
        paper_list.move_to_bottom()
        self.app.set_focus(paper_list)  # Maintain focus

    def action_toggle_selection(self) -> None:
        self.query_one("#paper-list-view").toggle_selection()

    def action_toggle_log(self) -> None:
        """Toggle the visibility of the log panel."""
        log_panel = self.query_one(LogPanel)
        if log_panel.show_panel and log_panel.panel_mode == "log":
            # Close log panel
            log_panel.show_panel = False
            self.app.set_focus(self.query_one(CommandInput))
        else:
            # Open log panel (auto-refresh will handle getting latest logs)
            log_panel.show_logs()
            self.app.set_focus(log_panel)

    def _show_detail_dialog(self, paper) -> None:
        """Show details dialog for a paper."""
        if paper:
            self.app.push_screen(DetailDialog(paper, None))
        else:
            self.notify("No paper selected", severity="warning")

    def action_show_details(self) -> None:
        """Show details dialog for the currently selected paper."""
        paper_list = self.query_one("#paper-list-view")
        current_paper = paper_list.get_current_paper()
        self._show_detail_dialog(current_paper)

    def on_paper_list_show_details(self, message: PaperList.ShowDetails) -> None:
        """Handle detail dialog request from paper list."""
        self._show_detail_dialog(message.paper)

    def update_paper_list(self, papers: List[Paper]) -> None:
        """Updates the paper list with new data."""
        self.app._add_log(
            "update_paper_list",
            f"MainScreen updating paper list with {len(papers)} papers",
        )
        paper_list_widget = self.query_one("#paper-list-view")
        self.app._add_log(
            "update_paper_list_widget",
            f"Found paper list widget: {type(paper_list_widget).__name__}",
        )
        paper_list_widget.set_papers(papers)
        self.app._add_log("update_paper_list_done", "set_papers completed")

    def show_help(self) -> None:
        """Show help dialog."""
        help_text = """## Key Bindings

### Navigation
- **↑/↓** - Navigate papers
- **Page Up/Down** - Scroll by page
- **Home/End** - Go to first/last paper

### Function Keys
- **F1** - Add papers
- **F2** - Open selected paper in default PDF viewer
- **F3** - Show paper details
- **F4** - Chat with paper
- **F5** - Edit paper
- **F6** - Delete paper
- **F7** - Manage collections
- **F8** - Filter papers
- **F9** - Show all papers
- **F10** - Sort papers
- **F11** - Toggle selection mode
- **F12** - Clear selections

## Commands

### Paper Management
- **/add** - Add paper from various sources
- **/edit** - Edit paper metadata
- **/delete** - Delete selected papers
- **/export** - Export papers

### Search & Organization
- **/filter** - Filter papers by criteria
- **/sort** - Sort papers by field
- **/all** - Show all papers
- **/select** - Enter selection mode
- **/clear** - Clear selections

### AI & Chat
- **/chat** - Chat with papers using AI

### System
- **/help** - Show command help
- **/log** - Open log panel *(ESC to close)*
- **/config** - Manage configuration *(e.g. /config theme <theme>)*
- **/sync** - Synchronize with remote storage
- **/exit** - Exit the application"""

        self.app.push_screen(MessageDialog("Help", help_text))

    def action_show_add_dialog(self) -> None:
        """Show add paper dialog (F1)."""

        def add_callback(result):
            if result:
                # Handle the add paper result by calling the command handler directly
                source = result.get("source", "").strip()
                path_id = result.get("path_id", "").strip()

                # Show immediate notification that download/addition has started
                if source == "manual":
                    self.app.notify(
                        "Adding manual paper entry...", severity="information"
                    )
                else:
                    self.app.notify(
                        f"Adding paper from {source}...", severity="information"
                    )

                # Create command args as if it came from /add command
                # The handler expects: handle_add_command([source, path_id])
                command_args = [source]
                if path_id:
                    command_args.append(path_id)

                # Create async wrapper to handle completion and refresh
                async def add_paper_and_refresh():
                    # The command handler will handle all notifications and refresh
                    await self.app.paper_commands.handle_add_command(command_args)

                # Call the paper command handler in background worker thread
                self.app.run_worker(add_paper_and_refresh(), exclusive=False)

        self.app.push_screen(AddDialog(add_callback, app=self.app))

    def action_show_filter_dialog(self) -> None:
        """Show filter dialog (F3)."""

        def filter_callback(result):
            if result:
                self.notify(
                    f"Filtering by {result.get('field', 'unknown')}: {result.get('value', '')}"
                )

        collection_service = CollectionService()
        self.app.push_screen(FilterDialog(filter_callback, collection_service))

    def action_show_sort_dialog(self) -> None:
        """Show sort dialog (F4)."""
        from ng.dialogs import SortDialog

        def sort_callback(result):
            if result:
                self.notify(
                    f"Sorted by {result.get('field', 'unknown')} ({'desc' if result.get('reverse', False) else 'asc'})"
                )

        self.app.push_screen(SortDialog(sort_callback))

    def action_refresh_papers(self) -> None:
        """Refresh the paper list (F5)."""
        self.app.load_papers()
        self.notify("Papers refreshed", severity="information")

    def on_key(self, event: Key) -> None:
        """Handle global keyboard input to redirect typing to command input while preserving selection."""
        try:
            # Get the current focus and command input widget
            current_focus = self.app.focused
            command_input_container = self.query_one(CommandInput)
            actual_input = command_input_container.query_one(Input)

            # If input is already focused, don't intercept - let normal input handling work
            if current_focus == actual_input:
                return

            # Only handle printable characters that aren't already bound to actions
            if (
                event.key
                and len(event.key) == 1
                and event.key.isprintable()
                and not event.key.isspace()  # Don't intercept space (used for selection toggle)
                and event.key != "?"  # Don't intercept help key
            ):
                # Add the typed character to the input
                current_text = actual_input.value
                actual_input.value = current_text + event.key

                # Move cursor to end of input
                actual_input.cursor_position = len(actual_input.value)

                # Focus the input with a small delay; also keep the paper list cursor on current row
                def focus_input_and_preserve_cursor():
                    try:
                        paper_list = self.query_one("#paper-list-view")
                        if hasattr(self.app, "_add_log"):
                            self.app._add_log(
                                "focus_switch_pre",
                                f"cursor_row={paper_list.cursor_row}, "
                                f"selected_ids={list(paper_list.selected_paper_ids)}",
                            )
                        # Store current cursor position before focus changes
                        current_cursor_row = paper_list.cursor_row
                        paper_list._stored_cursor_row = current_cursor_row

                        # Re-apply cursor row to keep highlight even when focus changes
                        if 0 <= paper_list.cursor_row < len(paper_list.papers):
                            paper_list.move_cursor(row=paper_list.cursor_row)

                        # Always add retain-cursor to preserve cursor highlight
                        try:
                            paper_list.add_class("retain-cursor")
                        except Exception:
                            pass

                        # Maintain selection styling if papers are selected
                        if paper_list.selected_paper_ids and paper_list.in_select_mode:
                            try:
                                paper_list.add_class("retain-selection")
                                if hasattr(self.app, "_add_log"):
                                    self.app._add_log(
                                        "keyboard_focus_switch_selection",
                                        f"added retain-selection class, stored_cursor={current_cursor_row}, classes={paper_list.classes}",
                                    )
                            except Exception:
                                pass
                        else:
                            # Even in non-select mode, log cursor preservation
                            if hasattr(self.app, "_add_log"):
                                self.app._add_log(
                                    "keyboard_focus_switch_cursor",
                                    f"stored cursor position={current_cursor_row} for non-select mode",
                                )
                        if hasattr(self.app, "_add_log"):
                            self.app._add_log(
                                "focus_switch_post_cursor",
                                f"cursor_row={paper_list.cursor_row}",
                            )
                    except Exception:
                        pass
                    try:
                        self.app.set_focus(actual_input)
                        if hasattr(self.app, "_add_log"):
                            self.app._add_log(
                                "focus_set_input", "Focus moved to command input"
                            )
                    except Exception:
                        pass

                self.app.call_later(0.05, focus_input_and_preserve_cursor)

                # Prevent the event from being processed further
                event.prevent_default()

        except Exception:
            # If we can't redirect to input, let the event pass through
            pass
