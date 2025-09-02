from typing import List

from textual.events import Key
from textual.screen import Screen
from textual.widgets import Footer, Input

from ng.db.models import Paper
from ng.dialogs import AddDialog, DetailDialog, FilterDialog, MessageDialog, SortDialog
from ng.services import CollectionService
from ng.widgets.command_input import CommandInput
from ng.widgets.custom_header import CustomHeader
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
        height: 1fr;
        margin: 0;
        padding: 0;
        content-align: left top;
        border: solid $primary;
    }
    #command-input {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #command-input Input {
        border: solid $primary;
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
        border: solid $primary;
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
        custom_header = CustomHeader(app_ref=self.app, id="custom-header")
        yield custom_header
        yield PaperList(self.papers, id="paper-list-view")
        yield CommandInput(
            app=self.app, placeholder="❯ Enter command...", id="command-input"
        )
        log_panel = LogPanel(id="log-panel")  # Add LogPanel
        log_panel.set_app_reference(self.app)  # Set app reference for auto-refresh
        yield log_panel
        yield Footer()

    def on_mount(self) -> None:
        """Initialize header stats when screen is mounted."""
        self.call_later(self.update_header_stats)

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

    def on_paper_list_stats_changed(self, message: PaperList.StatsChanged) -> None:
        """Handle stats change from paper list."""
        self.update_header_stats()

    def update_paper_list(self, papers: List[Paper]) -> None:
        """Updates the paper list with new data."""
        paper_list_widget = self.query_one("#paper-list-view")
        paper_list_widget.set_papers(papers)
        # Update header stats
        self.update_header_stats()

    def update_header_stats(self) -> None:
        """Update the header with current paper statistics."""
        try:
            header = self.query_one("#custom-header")
            paper_list = self.query_one("#paper-list-view")

            total_papers = len(paper_list.papers)
            current_position = paper_list.cursor_row + 1 if paper_list.papers else 0

            if paper_list.in_select_mode:
                # In select mode: show actual selected count
                selected_count = len(paper_list.selected_paper_ids)
            else:
                # Not in select mode: always show 0 since no papers are selected
                selected_count = 0

            header.update_stats(total_papers, current_position, selected_count)
        except Exception:
            pass  # Widgets might not be ready yet

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
        """Show filter dialog (F8)."""

        def filter_callback(result):
            if result:
                field = result["field"]
                value = result["value"]
                # Apply the filter using the search commands
                if hasattr(self.app, "search_commands"):
                    self.app.search_commands._apply_filter(field, value)

        self.app.push_screen(FilterDialog(filter_callback))

    def action_show_sort_dialog(self) -> None:
        """Show sort dialog (F4)."""

        def sort_callback(result):
            if result:
                field = result.get("field", "title")
                reverse = result.get("reverse", False)
                # Apply the sort using the search commands
                if hasattr(self.app, "search_commands"):
                    self.app.search_commands._apply_sort(field, reverse)

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

            # Handle printable characters, with special priority for "/" (command starter)
            # Note: "/" key can be reported as either "/" or "slash"
            is_command_char = event.key == "/" or event.key == "slash"
            is_printable_char = (
                event.key
                and len(event.key) == 1
                and event.key.isprintable()
                and not event.key.isspace()  # Don't intercept space (used for selection toggle)
                and event.key != "?"  # Don't intercept help key
            )

            if is_command_char or is_printable_char:
                # Focus the input and append the character directly
                # The CustomInput widget will handle preventing text selection
                self.app.set_focus(actual_input)

                # Directly append the character to avoid selection issues
                # Convert "slash" key name to actual "/" character
                char_to_add = "/" if event.key == "slash" else event.key
                current_text = actual_input.value or ""
                new_value = current_text + char_to_add
                actual_input.value = new_value

                # Position cursor at end
                actual_input.cursor_position = len(new_value)

                # Preserve cursor and selection styling with a small delay
                def preserve_cursor_and_selection():
                    try:
                        paper_list = self.query_one("#paper-list-view")

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

                            except Exception:
                                pass

                    except Exception:
                        pass

                # Preserve cursor and selection styling with a small delay
                self.app.call_later(0.05, preserve_cursor_and_selection)

                # Prevent the event from being processed further
                event.prevent_default()

        except Exception:
            # If we can't redirect to input, let the event pass through
            pass
