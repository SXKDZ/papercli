import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from textual.app import App

from ng.commands import (
    CollectionCommandHandler,
    ExportCommandHandler,
    PaperCommandHandler,
    SearchCommandHandler,
    SystemCommandHandler,
)
from ng.db.database import init_database
from ng.screens.main_screen import MainScreen
from ng.services import (
    BackgroundOperationService,
    MetadataExtractor,
    PaperService,
    PDFManager,
    PDFService,
    SystemService,
)
from ng.widgets.command_input import CommandInput
from ng.widgets.log_panel import LogPanel


class PaperCLIApp(App):
    """PaperCLI Textual application."""

    # Enable mouse support
    ENABLE_COMMAND_PALETTE = False  # Disable command palette to avoid conflicts

    BINDINGS = [
        # Navigation
        ("up", "cursor_up", "Cursor Up"),
        ("down", "cursor_down", "Cursor Down"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("home", "cursor_home", "Cursor Home"),
        ("end", "cursor_end", "Cursor End"),
        # System
        ("question_mark", "show_help", "Help"),
        # Function keys
        ("f1", "show_add_dialog", "Add"),
        ("f2", "open_paper", "PDF"),
        ("f3", "show_details", "Details"),
        ("f4", "chat_paper", "Chat"),
        ("f5", "edit_paper", "Edit"),
        ("f6", "delete_paper", "Delete"),
        ("f7", "manage_collections", "Collections"),
        ("f8", "show_filter_dialog", "Filter"),
        ("f9", "show_all_papers", "Show All"),
        ("f10", "show_sort_dialog", "Sort"),
        ("f11", "toggle_select_mode", "Toggle Select"),
        ("f12", "clear_selection", "Clear Selection"),
    ]

    def __init__(self, db_path: str = "./papercli.db", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_path = db_path  # Database path
        self.logs = []  # List to store log entries
        self.paper_service = PaperService()  # Initialize PaperService
        self.current_papers = []  # Initialize current_papers
        self.main_screen = None  # Reference to the main screen

    def on_mount(self) -> None:
        # Initialize database
        init_database(self.db_path)

        # Load theme from environment
        saved_theme = os.getenv("PAPERCLI_THEME", "textual-dark")
        self.theme = saved_theme

        # Load papers from the database
        self.load_papers()

        # Push MainScreen with initial papers and store reference
        self.main_screen = MainScreen(papers=self.current_papers)
        self.push_screen(self.main_screen)

        # Initialize core services
        self.background_service = BackgroundOperationService(app=self)
        self.pdf_manager = PDFManager(app=self)
        self.pdf_service = PDFService(app=self)
        self.metadata_extractor = MetadataExtractor(
            pdf_manager=self.pdf_manager, app=self
        )
        self.system_service = SystemService(pdf_manager=self.pdf_manager, app=self)

        # Initialize CommandHandlers after MainScreen is pushed
        self.system_commands = SystemCommandHandler(self)
        self.search_commands = SearchCommandHandler(self)
        self.paper_commands = PaperCommandHandler(self)
        self.collection_commands = CollectionCommandHandler(self)
        self.export_commands = ExportCommandHandler(self)

    def _add_log(self, action: str, details: str):
        """Add a log entry and update log panel if visible."""
        self.logs.append(
            {"timestamp": datetime.now(), "action": action, "details": details}
        )

        # Directly update log panel if it's visible
        try:
            if self.main_screen:
                log_panel = self.main_screen.query_one(LogPanel)
                log_panel.refresh_if_visible()
        except Exception:
            # Ignore errors if log panel doesn't exist or isn't available
            pass

    def load_papers(self):
        """Load papers from database and update the PaperList widget."""
        try:
            papers = self.paper_service.get_all_papers()
            self.current_papers = papers
            self._add_log("load_papers", f"Loaded {len(papers)} papers from database.")
            # Update the PaperList widget - try stored reference first, then find it
            main_screen_to_update = self.main_screen

            if not main_screen_to_update:
                # If stored reference is None, try to find MainScreen in screen stack
                from ng.screens.main_screen import MainScreen

                for screen in reversed(self._screen_stack):
                    if isinstance(screen, MainScreen):
                        main_screen_to_update = screen
                        self.main_screen = screen  # Update the reference
                        self._add_log(
                            "load_papers_found_screen",
                            f"Found MainScreen in stack, updating reference",
                        )
                        break

            if main_screen_to_update:
                self._add_log(
                    "load_papers_calling_update",
                    f"About to call update_paper_list with {len(papers)} papers",
                )
                main_screen_to_update.update_paper_list(papers)
                self._add_log(
                    "load_papers_called_update", "update_paper_list completed"
                )
            else:
                self._add_log(
                    "load_papers_no_main_screen",
                    f"No MainScreen found, current screen: {type(self.screen).__name__}, stack: {[type(s).__name__ for s in self._screen_stack]}",
                )
        except Exception as e:
            self._add_log("load_papers_error", f"Error loading papers: {e}")
            # Error will be logged but not displayed during startup

    def action_cursor_up(self) -> None:
        """Move cursor up in paper list."""
        if hasattr(self.screen, "action_cursor_up"):
            self.screen.action_cursor_up()

    def action_cursor_down(self) -> None:
        """Move cursor down in paper list."""
        if hasattr(self.screen, "action_cursor_down"):
            self.screen.action_cursor_down()

    def action_page_up(self) -> None:
        """Move page up in paper list."""
        if hasattr(self.screen, "action_page_up"):
            self.screen.action_page_up()

    def action_page_down(self) -> None:
        """Move page down in paper list."""
        if hasattr(self.screen, "action_page_down"):
            self.screen.action_page_down()

    def action_cursor_home(self) -> None:
        """Move to top of paper list."""
        if hasattr(self.screen, "action_cursor_home"):
            self.screen.action_cursor_home()

    def action_cursor_end(self) -> None:
        """Move to bottom of paper list."""
        if hasattr(self.screen, "action_cursor_end"):
            self.screen.action_cursor_end()

    def action_toggle_selection(self) -> None:
        """Toggle selection in paper list."""
        if hasattr(self.screen, "action_toggle_selection"):
            self.screen.action_toggle_selection()

    def action_show_details(self) -> None:
        """Show paper details."""
        if hasattr(self.screen, "action_show_details"):
            self.screen.action_show_details()

    def action_quit(self) -> None:
        """An action to quit the application."""
        self.exit()

    async def on_command_input_command_entered(
        self, message: CommandInput.CommandEntered
    ) -> None:
        command = message.command.strip()
        if not command.startswith("/"):
            self.notify(
                "Invalid input. All commands must start with '/'.", severity="error"
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
            await self.export_commands.handle_chat_command(
                parts[1:] if len(parts) > 1 else None
            )
        elif cmd == "/copy-prompt":
            await self.export_commands.handle_copy_prompt_command()
        else:
            self.notify(f"Unknown command: {cmd}", severity="error")

    def action_show_help(self) -> None:
        """Show help (F1 or ?)."""
        if hasattr(self.screen, "show_help"):
            self.screen.show_help()

    def action_show_add_dialog(self) -> None:
        """Show add dialog (F1)."""
        if hasattr(self.screen, "action_show_add_dialog"):
            self.screen.action_show_add_dialog()

    def action_open_paper(self) -> None:
        """Open paper (F2)."""
        self.run_worker(self.paper_commands.handle_open_command(), exclusive=False)

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
        self.run_worker(
            self.collection_commands.handle_collect_command([]), exclusive=False
        )

    def action_show_filter_dialog(self) -> None:
        """Show filter dialog (F8)."""
        if hasattr(self.screen, "action_show_filter_dialog"):
            self.screen.action_show_filter_dialog()

    def action_show_all_papers(self) -> None:
        """Show all papers (F9)."""
        self.search_commands.handle_all_command()

    def action_show_sort_dialog(self) -> None:
        """Show sort dialog (F10)."""
        if hasattr(self.screen, "action_show_sort_dialog"):
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
        self.notify("Papers refreshed", severity="information")


def setup_environment():
    """Set up environment variables and data directory."""
    # Get data directory from environment or use default
    data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
    if data_dir_env:
        data_dir = Path(data_dir_env).expanduser().resolve()
    else:
        data_dir = Path.home() / ".papercli"

    # Ensure data directory exists
    data_dir.mkdir(exist_ok=True, parents=True)

    # Skip OpenAI setup if API key is already set via environment
    if os.getenv("OPENAI_API_KEY"):
        return data_dir

    # Try to load from .env files in order of preference
    env_locations = [Path.cwd() / ".env", data_dir / ".env"]

    for env_file in env_locations:
        if env_file.exists():
            load_dotenv(env_file)
            break

    # If still no API key, prompt user
    if not os.getenv("OPENAI_API_KEY"):
        current_dir = Path.cwd()
        print(
            f"""
🔧 Configuration Setup Required

PaperCLI requires OpenAI API configuration. You can set it up in two ways:

1. Using environment variables:
   export OPENAI_API_KEY=your_openai_api_key_here
   export OPENAI_MODEL=gpt-4o  # optional, defaults to gpt-4o
   export PAPERCLI_DATA_DIR=/path/to/data  # optional, defaults to ~/.papercli

2. Using a .env file in either location:
   - Current directory: {current_dir}
   - Data directory: {data_dir}

You can get an API key from: https://platform.openai.com/api-keys
"""
        )

        try:
            response = input(
                "Would you like to continue without OpenAI configuration? (y/N): "
            )
            if response.lower() not in ["y", "yes"]:
                print("Please set up OpenAI configuration and run papercli again.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)

    return data_dir


if __name__ == "__main__":
    # Set up environment and get data directory
    data_dir = setup_environment()

    # Default database path - use existing papers.db with all user's papers
    db_path = data_dir / "papers.db"
    app = PaperCLIApp(db_path=str(db_path))
    app.run()
