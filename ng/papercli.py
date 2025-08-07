from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Static
from textual.containers import Container, VerticalScroll
from ng.screens.main_screen import MainScreen
from ng.commands.system import SystemCommandHandler
from ng.commands.search import SearchCommandHandler
from ng.commands.paper import PaperCommandHandler
from ng.commands.collection import CollectionCommandHandler
from ng.commands.export import ExportCommandHandler
from ng.widgets.command_input import CommandInput
from ng.db.database import init_database # Import database initialization
from ng.services.paper import PaperService # Import PaperService
from ng.services.background import BackgroundOperationService # Import BackgroundOperationService
from ng.services.metadata import MetadataExtractor # Import MetadataExtractor
from ng.services.system import SystemService # Import SystemService
from ng.services.pdf import PDFManager # Import PDFManager
from datetime import datetime
import os

class PaperCLIApp(App):
    """PaperCLI Textual application."""
    
    # Enable mouse support
    ENABLE_COMMAND_PALETTE = False  # Disable command palette to avoid conflicts
    
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("escape", "quit", "Quit"),
        ("f1", "show_add_dialog", "Add Paper"),
        ("f2", "open_paper", "Open Paper"),
        ("f3", "show_detail", "Paper Details"),
        ("f4", "chat_paper", "Chat"),
        ("f5", "edit_paper", "Edit Paper"),
        ("f6", "delete_paper", "Delete Paper"),
        ("f7", "manage_collections", "Collections"),
        ("f8", "show_filter_dialog", "Filter"),
        ("f9", "show_all_papers", "Show All"),
        ("f10", "show_sort_dialog", "Sort"),
        ("f11", "toggle_select_mode", "Toggle Select"),
        ("f12", "clear_selection", "Clear Selection"),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(self, db_path: str = "./papercli.db", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_path = db_path # Database path
        self.logs = [] # List to store log entries
        self.paper_service = PaperService() # Initialize PaperService
        self.current_papers = [] # Initialize current_papers

    def on_mount(self) -> None:
        # Initialize database
        init_database(self.db_path)

        # Load papers from the database
        self.load_papers()

        # Push MainScreen with initial papers
        self.push_screen(MainScreen(papers=self.current_papers))

        # Initialize core services
        self.background_service = BackgroundOperationService(app=self, log_callback=self._add_log)
        self.pdf_manager = PDFManager(pdf_dir=os.path.join(os.path.dirname(self.db_path), "pdfs"))
        self.metadata_extractor = MetadataExtractor(pdf_manager=self.pdf_manager, log_callback=self._add_log)
        self.system_service = SystemService(pdf_manager=self.pdf_manager)

        # Initialize CommandHandlers after MainScreen is pushed
        self.system_commands = SystemCommandHandler(self)
        self.search_commands = SearchCommandHandler(self)
        self.paper_commands = PaperCommandHandler(self)
        self.collection_commands = CollectionCommandHandler(self)
        self.export_commands = ExportCommandHandler(self)

    def _add_log(self, action: str, details: str):
        """Add a log entry."""
        self.logs.append(
            {"timestamp": datetime.now(), "action": action, "details": details}
        )

    def load_papers(self):
        """Load papers from database and update the PaperList widget."""
        try:
            papers = self.paper_service.get_all_papers()
            self.current_papers = papers
            self._add_log("load_papers", f"Loaded {len(papers)} papers from database.")
            # Update the PaperList widget if MainScreen is already mounted
            if self.is_mounted and isinstance(self.screen, MainScreen):
                self.screen.update_paper_list(papers)
        except Exception as e:
            self._add_log("load_papers_error", f"Error loading papers: {e}")
            # self.query_one("#status-bar").set_error(f"Error loading papers: {e}") # Cannot query before mount

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.theme = "textual-light" if getattr(self, 'theme', 'textual-dark') == 'textual-dark' else "textual-dark"

    def action_quit(self) -> None:
        """An action to quit the application."""
        self.exit()

    async def on_command_input_command_entered(self, message: CommandInput.CommandEntered) -> None:
        command = message.command.strip()
        if not command.startswith("/"):
            self.query_one("#status-bar").set_error(
                f"Invalid input. All commands must start with '/'."
            )
            return

        parts = command.split()
        cmd = parts[0].lower()

        if cmd == "/exit":
            self.system_commands.handle_exit_command()
        elif cmd == "/version":
            self.system_commands.handle_version_command(parts[1:])
        elif cmd == "/config":
            self.system_commands.handle_config_command(parts[1:])
        elif cmd == "/doctor":
            self.system_commands.handle_doctor_command(parts[1:])
        elif cmd == "/log":
            self.system_commands.handle_log_command()
        elif cmd == "/sync":
            self.system_commands.handle_sync_command(parts[1:])
        elif cmd == "/all":
            self.search_commands.handle_all_command()
        elif cmd == "/clear":
            self.search_commands.handle_clear_command()
        elif cmd == "/filter":
            await self.search_commands.handle_filter_command(parts[1:])
        elif cmd == "/sort":
            await self.search_commands.handle_sort_command(parts[1:])
        elif cmd == "/select":
            self.search_commands.handle_select_command()
        elif cmd == "/add":
            await self.paper_commands.handle_add_command(parts[1:])
        elif cmd == "/edit":
            await self.paper_commands.handle_edit_command(parts[1:])
        elif cmd == "/delete":
            await self.paper_commands.handle_delete_command()
        elif cmd == "/open":
            await self.paper_commands.handle_open_command()
        elif cmd == "/detail":
            await self.paper_commands.handle_detail_command()
        elif cmd == "/collect":
            await self.collection_commands.handle_collect_command(parts[1:])
        elif cmd == "/add-to":
            await self.collection_commands.handle_add_to_command(parts[1:])
        elif cmd == "/remove-from":
            await self.collection_commands.handle_remove_from_command(parts[1:])
        elif cmd == "/export":
            await self.export_commands.handle_export_command(parts[1:])
        elif cmd == "/chat":
            await self.export_commands.handle_chat_command(parts[1:] if len(parts) > 1 else None)
        elif cmd == "/copy-prompt":
            await self.export_commands.handle_copy_prompt_command()
        else:
            self.query_one("#status-bar").set_error(f"Unknown command: {cmd}")

    def action_show_help(self) -> None:
        """Show help (F1 or ?)."""
        if hasattr(self.screen, 'show_help'):
            self.screen.show_help()

    def action_show_add_dialog(self) -> None:
        """Show add dialog (F1)."""
        if hasattr(self.screen, 'action_show_add_dialog'):
            self.screen.action_show_add_dialog()

    def action_open_paper(self) -> None:
        """Open paper (F2)."""
        self.run_worker(self.paper_commands.handle_open_command(), exclusive=False)

    def action_show_detail(self) -> None:
        """Show paper details (F3)."""
        self.run_worker(self.paper_commands.handle_detail_command(), exclusive=False)

    def action_chat_paper(self) -> None:
        """Chat with paper (F4)."""
        self.run_worker(self.export_commands.handle_chat_command(), exclusive=False)

    def action_edit_paper(self) -> None:
        """Edit paper (F5)."""
        self.run_worker(self.paper_commands.handle_edit_command([]), exclusive=False)

    def action_delete_paper(self) -> None:
        """Delete paper (F6)."""
        self.run_worker(self.paper_commands.handle_delete_command(), exclusive=False)

    def action_manage_collections(self) -> None:
        """Manage collections (F7)."""
        self.run_worker(self.collection_commands.handle_collect_command([]), exclusive=False)

    def action_show_filter_dialog(self) -> None:
        """Show filter dialog (F8)."""
        if hasattr(self.screen, 'action_show_filter_dialog'):
            self.screen.action_show_filter_dialog()

    def action_show_all_papers(self) -> None:
        """Show all papers (F9)."""
        self.search_commands.handle_all_command()

    def action_show_sort_dialog(self) -> None:
        """Show sort dialog (F10)."""
        if hasattr(self.screen, 'action_show_sort_dialog'):
            self.screen.action_show_sort_dialog()

    def action_toggle_select_mode(self) -> None:
        """Toggle selection mode (F11)."""
        self.search_commands.handle_select_command()

    def action_clear_selection(self) -> None:
        """Clear selection (F12)."""
        self.search_commands.handle_clear_command()

    def action_refresh_papers(self) -> None:
        """Refresh papers (F5)."""
        self.load_papers()
        if hasattr(self.screen, 'query_one'):
            self.screen.query_one("#status-bar").set_status("Papers refreshed")

if __name__ == "__main__":
    # Default database path - use existing papers.db with all user's papers
    db_path = os.path.join(os.path.expanduser("~/.papercli"), "papers.db")
    app = PaperCLIApp(db_path=db_path)
    app.run()
