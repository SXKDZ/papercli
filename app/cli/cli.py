"""Main CLI coordinator module."""

import traceback
from datetime import datetime
from typing import List
from typing import Optional

from prompt_toolkit.document import Document
from prompt_toolkit.layout.containers import Float

from ..db.models import Paper
from ..dialogs import AddDialog
from ..dialogs import FilterDialog
from ..dialogs import SortDialog
from ..services import AddPaperService
from ..services import AuthorService
from ..services import BackgroundOperationService
from ..services import ChatService
from ..services import CollectionService
from ..services import DatabaseHealthService
from ..services import ExportService
from ..services import MetadataExtractor
from ..services import PaperService
from ..services import SearchService
from ..services import SystemService
from ..services.auto_sync import trigger_auto_sync
from ..ui import ErrorPanel
from ..ui import PaperListControl
from ..ui import StatusBar
from ..version import get_version
from .commands import CollectionCommandHandler
from .commands import ExportCommandHandler
from .commands import PaperCommandHandler
from .commands import SearchCommandHandler
from .commands import SystemCommandHandler
from .completer import SmartCompleter
from .ui_setup import UISetupMixin


class PaperCLI(UISetupMixin):
    """Main CLI application class."""

    HELP_TEXT = """
PaperCLI Help
=============

Core Commands:
--------------
/add           Open add dialog or add paper directly (e.g., /add arxiv 2307.10635)
/filter        Filter papers by criteria or search all fields (e.g., /filter all keyword)
/sort          Open sort dialog or sort directly (e.g., /sort title asc)
/all           Show all papers in the database
/select        Enter multi-selection mode to act on multiple papers
/clear         Clear all selected papers
/help          Show this help panel
/log           Show the error log panel
/config        Manage configuration (model, API key) - /config show for details
/sync          Synchronize with remote storage (if configured)
/exit          Exit the application (or press Ctrl+C)

Paper Operations (work on the paper under the cursor ► or selected papers ✓):
-----------------------------------------------------------------------------
/chat             Open chat window with ChatGPT (local interface)
/chat [provider]  Copy prompt to clipboard and open LLM in browser
  claude          Copy prompt to clipboard and open Claude AI in browser
  chatgpt         Copy prompt to clipboard and open ChatGPT in browser  
  gemini          Copy prompt to clipboard and open Google Gemini in browser
/copy-prompt      Copy paper prompt to clipboard for use with any LLM
/edit             Open edit dialog or edit field directly (e.g., /edit title ...)
/open             Open the PDF for the paper(s)
/detail           Show detailed metadata for the paper(s)
/export           Export paper(s) to a file or clipboard (BibTeX, Markdown, etc.)
/delete           Delete the paper(s) from the library

Collection Management:
---------------------
/collect          Manage collections
/collect purge    Delete all empty collections
/add-to           Add selected paper(s) to one or more collections
/remove-from      Remove selected paper(s) from one or more collections

System Commands:
---------------
/doctor           Diagnose and fix database/system issues
  diagnose        Run full diagnostic check (default)
  clean           Clean orphaned database records and PDF files
  help            Show doctor command help
/version          Show version info and check for updates
  check           Check for available updates
  update          Update to latest version (if possible)
  info            Show detailed version information
/config           Manage configuration settings
/sync             Synchronize local data with remote storage
  show            Show all current configuration
  model           Set OpenAI model (gpt-4o, gpt-3.5-turbo, etc.)
  openai_api_key  Set OpenAI API key
  help            Show configuration command help

Navigation & Interaction:
-------------------------
↑/↓               Navigate the paper list or scroll panels
PageUp/↓          Scroll panels by a full page
Space             Toggle selection for a paper (only in /select mode)
Enter             Execute a command from the input bar
ESC               Close panels (Help, Error), exit selection mode, or clear input
Tab               Trigger and cycle through auto-completions

Chat Interface Shortcuts (when using /chat):
--------------------------------------------
Enter             Send message
Ctrl+J            Insert newline in message
Ctrl+S            Send message (alternative)
↑/↓               Navigate input history (when focused on input)
↑/↓               Scroll chat display by page
PageUp/↓          Scroll chat display by page
ESC               Close chat interface

Indicators (in the first column):
---------------------------------
►                 Indicates the current line (cursor).
  ✓               Indicates a selected paper.
  □               Indicates an unselected paper (in /select mode).
► ✓               Indicates that the current line is also selected.
► □               Indicates the current line is not selected (in /select mode).
"""

    def __init__(self, db_path: str):
        self.db_path = db_path

        self.paper_service = PaperService()
        self.search_service = SearchService()
        self.author_service = AuthorService()
        self.collection_service = CollectionService()
        self.metadata_extractor = MetadataExtractor(self._add_log)
        self.export_service = ExportService()
        self.chat_service = ChatService(self._add_log)
        self.system_service = SystemService()
        self.db_health_service = DatabaseHealthService(log_callback=self._add_log)
        self.add_paper_service = AddPaperService(
            self.paper_service, self.metadata_extractor, self.system_service
        )

        self.background_service = None
        self.smart_completer = SmartCompleter(cli=self)
        self.current_papers: List[Paper] = []
        self.paper_list_control = PaperListControl([])
        self.status_bar = StatusBar()
        self.error_panel = ErrorPanel(log_callback=self._add_log)
        self.in_select_mode = False
        self.show_help = False
        self.show_error_panel = False
        self.show_details_panel = False
        self.is_filtered_view = False
        self.is_syncing = False
        self.edit_dialog = None
        self.edit_float = None
        self.add_dialog = None
        self.add_float = None
        self.sync_dialog = None
        self.sync_float = None
        self.filter_dialog = None
        self.filter_float = None
        self.sort_dialog = None
        self.sort_float = None
        self.collect_dialog = None
        self.collect_float = None
        self.chat_dialog = None
        self.chat_float = None
        self.logs = []

        self.system_commands = SystemCommandHandler(self)
        self.paper_commands = PaperCommandHandler(self)
        self.search_commands = SearchCommandHandler(self)
        self.collection_commands = CollectionCommandHandler(self)
        self.export_commands = ExportCommandHandler(self)

        self.load_papers()

        self.setup_layout()
        self.setup_key_bindings()
        self.setup_application()

        self.background_service = BackgroundOperationService(
            status_bar=self.status_bar, log_callback=self._add_log
        )

    def _add_log(self, action: str, details: str):
        """Add a log entry."""
        self.logs.append(
            {"timestamp": datetime.now(), "action": action, "details": details}
        )

    def load_papers(self):
        """Load papers from database."""
        try:
            old_selected_index = getattr(self.paper_list_control, "selected_index", 0)
            old_selected_paper_ids = getattr(
                self.paper_list_control, "selected_paper_ids", set()
            ).copy()
            old_in_select_mode = getattr(
                self.paper_list_control, "in_select_mode", False
            )

            self.current_papers = self.paper_service.get_all_papers()
            self.paper_list_control = PaperListControl(self.current_papers)

            # Restore selection state
            self.paper_list_control.selected_index = (
                min(old_selected_index, len(self.current_papers) - 1)
                if self.current_papers
                else 0
            )
            self.paper_list_control.selected_paper_ids = old_selected_paper_ids
            self.paper_list_control.in_select_mode = old_in_select_mode
            self.is_filtered_view = False

            self.status_bar.set_status(
                f"Loaded {len(self.current_papers)} papers", "papers"
            )
        except Exception as e:
            self.status_bar.set_error(f"Error loading papers: {e}")

    def _get_target_papers(self) -> Optional[List[Paper]]:
        """
        Get the papers to act on, based on selection or cursor position.
        Shows a warning and returns None if no papers are targeted.
        """
        target_papers = self.paper_list_control.get_selected_papers()
        if not target_papers:
            current_paper = self.paper_list_control.get_current_paper()
            if current_paper:
                target_papers = [current_paper]

        if not target_papers:
            self.status_bar.set_warning("No papers selected or under cursor")
            return None

        return target_papers

    def _scroll_to_selected(self):
        """Scroll to the first selected paper."""
        if self.paper_list_control.selected_paper_ids:
            first_selected_id = next(iter(self.paper_list_control.selected_paper_ids))
            for i, paper in enumerate(self.current_papers):
                if paper.id == first_selected_id:
                    self.paper_list_control.current_line = i
                    break

    def handle_command(self, command: str):
        """Handle user commands."""
        try:
            if not command.strip().startswith("/"):
                self.status_bar.set_error(
                    f"Invalid input. All commands must start with '/'."
                )
                return

            parts = command.split()
            cmd = parts[0].lower()

            if cmd in self.smart_completer.commands:
                if cmd == "/help":
                    self.show_help_dialog(self.HELP_TEXT, "PaperCLI Help")
                elif cmd == "/log":
                    self.system_commands.handle_log_command()
                elif cmd == "/doctor":
                    self.system_commands.handle_doctor_command(parts[1:])
                elif cmd == "/version":
                    self.system_commands.handle_version_command(parts[1:])
                elif cmd == "/config":
                    self.system_commands.handle_config_command(parts[1:])
                elif cmd == "/sync":
                    self.system_commands.handle_sync_command(parts[1:])
                elif cmd == "/exit":
                    self.system_commands.handle_exit_command()

                # Paper commands
                elif cmd == "/add":
                    self.paper_commands.handle_add_command(parts[1:])
                elif cmd == "/edit":
                    self.paper_commands.handle_edit_command(parts[1:])
                elif cmd == "/delete":
                    self.paper_commands.handle_delete_command()
                elif cmd == "/open":
                    self.paper_commands.handle_open_command()
                elif cmd == "/detail":
                    self.paper_commands.handle_detail_command()

                # Search commands
                elif cmd == "/filter":
                    self.search_commands.handle_filter_command(parts[1:])
                elif cmd == "/select":
                    self.search_commands.handle_select_command()
                elif cmd == "/all":
                    self.search_commands.handle_all_command()
                elif cmd == "/clear":
                    self.search_commands.handle_clear_command()
                elif cmd == "/sort":
                    self.search_commands.handle_sort_command(parts[1:])

                # Collection commands
                elif cmd == "/add-to":
                    self.collection_commands.handle_add_to_command(parts[1:])
                elif cmd == "/remove-from":
                    self.collection_commands.handle_remove_from_command(parts[1:])
                elif cmd == "/collect":
                    self.collection_commands.handle_collect_command(parts[1:])

                # Export commands
                elif cmd == "/export":
                    self.export_commands.handle_export_command(parts[1:])
                elif cmd == "/chat":
                    provider = parts[1] if len(parts) > 1 else None
                    self.export_commands.handle_chat_command(provider)
                elif cmd == "/copy-prompt":
                    self.export_commands.handle_copy_prompt_command()
            else:
                self.status_bar.set_error(f"Unknown command: {cmd}")

        except Exception as e:
            # Show detailed error in error panel instead of just status bar
            self.show_error_panel_with_message(
                "Command Error",
                f"Failed to execute command: {command}\n\n{traceback.format_exc()}",
            )

    def show_add_dialog(self):
        """Show the add paper dialog."""

        def callback(result):
            if self.add_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.add_float)
            self.add_dialog = None
            self.add_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                try:
                    source = result.get("source", "").strip()
                    path_id = result.get("path_id", "").strip()

                    if not source:
                        self.status_bar.set_error("Source is required")
                        return

                    # Determine the type of source and call appropriate add command
                    if source.lower() in [
                        "pdf",
                        "arxiv",
                        "dblp",
                        "openreview",
                        "doi",
                        "bib",
                        "ris",
                        "manual",
                    ]:
                        # Handle subcommand-style addition
                        if path_id:
                            self.paper_commands.handle_add_command([source, path_id])
                        else:
                            self.paper_commands.handle_add_command([source])
                    else:
                        # Treat as manual entry with source as title
                        self.paper_commands.handle_add_command(["manual", source])

                except Exception as e:
                    self.status_bar.set_error(f"Error adding paper: {e}")
            else:
                # Dialog was cancelled
                self.status_bar.set_status("Closed add dialog", "close")

            self.app.invalidate()

        self.add_dialog = AddDialog(callback)
        self.add_float = Float(self.add_dialog)
        self.app.layout.container.floats.append(self.add_float)
        self.app.layout.focus(self.add_dialog.get_initial_focus() or self.add_dialog)
        self.app.invalidate()

    def show_filter_dialog(self):
        """Show the filter dialog."""

        def callback(result):
            if self.filter_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.filter_float)
            self.filter_dialog = None
            self.filter_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                # Apply filters
                field = result["field"]
                value = result["value"]
                self.search_commands.handle_filter_command([field, value])
            else:
                self.status_bar.set_status("Filter cancelled.")

            self.app.invalidate()

        try:
            self.filter_dialog = FilterDialog(callback, self.collection_service)
            self.filter_float = Float(self.filter_dialog)
            self.app.layout.container.floats.append(self.filter_float)
            self.app.layout.focus(
                self.filter_dialog.get_initial_focus() or self.filter_dialog
            )
            self.app.invalidate()

        except Exception as e:
            self.show_error_panel_with_message(
                "Filter Dialog Error",
                f"Could not open the filter dialog.\n\n{traceback.format_exc()}",
            )

    def show_sort_dialog(self):
        """Show the sort dialog."""

        def callback(result):
            if self.sort_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.sort_float)
            self.sort_dialog = None
            self.sort_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                # Preserve selection state
                old_selected_paper_ids = (
                    self.paper_list_control.selected_paper_ids.copy()
                )
                old_in_select_mode = self.paper_list_control.in_select_mode

                # Sort papers
                field = result["field"]
                reverse = result["reverse"]

                if field == "title":
                    self.current_papers.sort(
                        key=lambda p: p.title.lower(), reverse=reverse
                    )
                elif field == "authors":
                    self.current_papers.sort(
                        key=lambda p: p.author_names.lower(), reverse=reverse
                    )
                elif field == "venue":
                    self.current_papers.sort(
                        key=lambda p: p.venue_display.lower(), reverse=reverse
                    )
                elif field == "year":
                    self.current_papers.sort(key=lambda p: p.year or 0, reverse=reverse)
                elif field == "added_date":
                    self.current_papers.sort(
                        key=lambda p: p.added_date or datetime.min, reverse=reverse
                    )
                elif field == "modified_date":
                    self.current_papers.sort(
                        key=lambda p: p.modified_date or datetime.min, reverse=reverse
                    )
                elif field == "paper_type":
                    self.current_papers.sort(
                        key=lambda p: p.paper_type or "", reverse=reverse
                    )

                # Update paper list control
                self.paper_list_control = PaperListControl(self.current_papers)
                self.paper_list_control.selected_paper_ids = old_selected_paper_ids
                self.paper_list_control.in_select_mode = old_in_select_mode

                order_text = "descending" if reverse else "ascending"
                self.status_bar.set_success(f"Sorted by {field} ({order_text})")
            else:
                self.status_bar.set_status("Sort cancelled.")

            self.app.invalidate()

        try:
            self.sort_dialog = SortDialog(callback)
            self.sort_float = Float(self.sort_dialog)
            self.app.layout.container.floats.append(self.sort_float)
            self.app.layout.focus(
                self.sort_dialog.get_initial_focus() or self.sort_dialog
            )
            self.app.invalidate()

        except Exception as e:
            self.show_error_panel_with_message(
                "Sort Dialog Error",
                f"Could not open the sort dialog.\n\n{traceback.format_exc()}",
            )

    def show_error_panel_with_message(self, title: str, message: str):
        """Show error panel with a specific message."""
        self.error_panel.add_error(title, message)
        self.show_error_panel = True
        self.app.invalidate()

    def show_help_dialog(self, content: str = None, title: str = "PaperCLI Help"):
        """Show help dialog with content."""
        if content is None:
            content = self.HELP_TEXT

        # Set the dynamic title
        self.help_dialog_title = title

        # Update buffer content correctly by bypassing the read-only flag
        doc = Document(content, 0)
        self.help_buffer.set_document(doc, bypass_readonly=True)

        self.show_help = True
        self.app.layout.focus(self.help_control)
        self.status_bar.set_status(f"{title} opened - Press ESC to close")

    def run(self):
        """Run the CLI application."""
        try:
            # Log application start
            self._add_log("app_start", f"PaperCLI started (version {get_version()})")
            self.app.run()
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            self._add_log("app_exit", "Application terminated by user (Ctrl+C)")
        except Exception as e:
            self._add_log("app_error", f"Application error: {e}")
            raise
        finally:
            self._add_log("app_stop", "PaperCLI stopped")

    def trigger_auto_sync_if_enabled(self):
        """Trigger auto-sync if enabled, typically called after edit operations."""
        trigger_auto_sync(log_callback=self._add_log)
