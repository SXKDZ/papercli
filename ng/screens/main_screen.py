from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual.containers import Container, VerticalScroll
from ng.widgets.paper_list import PaperList
from ng.widgets.status_bar import StatusBar
from ng.widgets.error_panel import ErrorPanel
from ng.widgets.command_input import CommandInput
from typing import List
from ng.db.models import Paper # Import Paper model

class MainScreen(Screen):
    """The main screen for PaperCLI."""

    BINDINGS = [
        ("up", "cursor_up", "Cursor Up"),
        ("down", "cursor_down", "Cursor Down"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("home", "cursor_home", "Cursor Home"),
        ("end", "cursor_end", "Cursor End"),
        ("space", "toggle_selection", "Toggle Selection"),
        ("l", "toggle_log", "Toggle Log"),
        ("enter", "show_details", "Show Details"),
        ("d", "show_details", "Show Details"),
    ]

    CSS = """
    MainScreen {
        margin: 0;
        padding: 0;
    }
    #paper-list-view {
        height: 1fr;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #command-input {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #status-bar {
        height: auto;
        width: 100%;
        background: $panel;
        margin: 0;
        padding: 0;
    }
    #error-panel {
        dock: right;
        width: 50%;
        height: 100%;
        background: $panel;
        border: thick $accent;
        layer: dialog;
    }
    """

    def __init__(self, papers: List[Paper], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.papers = papers

    def compose(self):
        yield Header()
        yield PaperList(self.papers, id="paper-list-view")
        yield CommandInput(app=self.app, placeholder="Enter command...", id="command-input")
        yield StatusBar(id="status-bar")
        yield ErrorPanel(id="error-panel") # Add ErrorPanel
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
        error_panel = self.query_one(ErrorPanel)
        if error_panel.show_panel and error_panel.panel_mode == "log":
            # Close log panel
            error_panel.show_panel = False
            self.app.set_focus(self.query_one(CommandInput))
        else:
            # Open log panel
            error_panel.set_logs(self.app.logs)
            error_panel.show_logs()
            self.app.set_focus(error_panel)

    def action_show_details(self) -> None:
        """Show details dialog for the currently selected paper."""
        paper_list = self.query_one("#paper-list-view")
        current_paper = paper_list.get_current_paper()
        
        if current_paper:
            from ng.dialogs.detail_dialog import DetailDialog
            
            def detail_callback(result):
                if result:
                    try:
                        self.query_one("#status-bar").set_status("Detail dialog closed")
                    except:
                        pass
                else:
                    try:
                        self.query_one("#status-bar").set_status("Detail dialog cancelled")
                    except:
                        pass
            
            self.app.push_screen(DetailDialog(current_paper, detail_callback))
        else:
            try:
                self.query_one("#status-bar").set_warning("No paper selected")
            except:
                pass

    def on_command_input_command_entered(self, message: CommandInput.CommandEntered) -> None:
        self.query_one(StatusBar).set_status(f"Command entered: {message.command}")
        # Here you would typically call a command handler function
        # For now, just update the status bar
    
    def on_paper_list_show_details(self, message: PaperList.ShowDetails) -> None:
        """Handle detail dialog request from paper list."""
        paper = message.paper
        if paper:
            from ng.dialogs.detail_dialog import DetailDialog
            
            def detail_callback(result):
                if result:
                    try:
                        self.query_one("#status-bar").set_status("Detail dialog closed")
                    except:
                        pass
                else:
                    try:
                        self.query_one("#status-bar").set_status("Detail dialog cancelled")
                    except:
                        pass
            
            self.app.push_screen(DetailDialog(paper, detail_callback))

    def update_paper_list(self, papers: List[Paper]) -> None:
        """Updates the paper list with new data."""
        self.query_one("#paper-list-view").set_papers(papers)

    def show_help(self) -> None:
        """Show help dialog."""
        help_text = """
PaperCLI Help
=============

Key Bindings:
-------------
F1 or ?       Show this help
F2           Open selected paper
F3           Show paper details
F4           Chat with paper
F5           Edit paper
F6           Delete paper
F7           Manage collections
F8           Filter papers
F9           Show all papers
F10          Sort papers
F11          Toggle selection mode
F12          Clear selections
↑/↓          Navigate papers
Page Up/Down Scroll by page
Home/End     Go to first/last paper
Space        Toggle selection
L            Toggle log panel
D            Toggle dark mode
Esc          Quit application

Commands:
---------
/add         Add paper from various sources
/filter      Filter papers by criteria
/sort        Sort papers by field
/edit        Edit paper metadata
/delete      Delete selected papers
/export      Export papers
/chat        Chat with papers using AI
/help        Show command help
/all         Show all papers
/select      Enter selection mode
/clear       Clear selections
"""
        # TODO: Implement proper help dialog
        try:
            self.query_one("#status-bar").set_status("Help: F1-Help, F2-Open, F3-Detail, F4-Chat, F5-Edit, F6-Delete, F7-Collections, F8-Filter, F9-All, F10-Sort")
        except:
            pass

    def action_show_add_dialog(self) -> None:
        """Show add paper dialog (F2)."""
        from ng.dialogs.add_dialog import AddDialog
        def add_callback(result):
            if result:
                # Handle the add paper result
                try:
                    self.query_one("#status-bar").set_status(f"Adding paper from {result.get('source', 'unknown source')}")
                except:
                    pass  # Gracefully handle if status bar not available
            else:
                try:
                    self.query_one("#status-bar").set_status("Add paper cancelled")
                except:
                    pass
        
        self.app.push_screen(AddDialog(add_callback))

    def action_show_filter_dialog(self) -> None:
        """Show filter dialog (F3)."""
        from ng.dialogs.filter_dialog import FilterDialog
        from ng.services.collection import CollectionService
        
        def filter_callback(result):
            if result:
                try:
                    self.query_one("#status-bar").set_status(f"Filtering by {result.get('field', 'unknown')}: {result.get('value', '')}")
                except:
                    pass
            else:
                try:
                    self.query_one("#status-bar").set_status("Filter cancelled")
                except:
                    pass
        
        collection_service = CollectionService()
        self.app.push_screen(FilterDialog(filter_callback, collection_service))

    def action_show_sort_dialog(self) -> None:
        """Show sort dialog (F4)."""
        from ng.dialogs.sort_dialog import SortDialog
        
        def sort_callback(result):
            if result:
                try:
                    self.query_one("#status-bar").set_status(f"Sorted by {result.get('field', 'unknown')} ({'desc' if result.get('reverse', False) else 'asc'})")
                except:
                    pass
            else:
                try:
                    self.query_one("#status-bar").set_status("Sort cancelled")
                except:
                    pass
        
        self.app.push_screen(SortDialog(sort_callback))

    def action_refresh_papers(self) -> None:
        """Refresh the paper list (F5)."""
        self.app.load_papers()
        try:
            self.query_one("#status-bar").set_status("Papers refreshed")
        except:
            pass