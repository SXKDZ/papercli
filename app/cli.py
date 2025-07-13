"""
Main CLI application for PaperCLI.
"""

import os
import traceback
from datetime import datetime
from typing import List, Optional

from .version import VersionManager, get_version

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings import scroll
from prompt_toolkit.layout import HSplit, Layout, Window, WindowAlign
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    ScrollOffsets,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Dialog, Frame, Button, Label

from .models import Paper
from .services import (
    AuthorService,
    ChatService,
    CollectionService,
    DatabaseHealthService,
    ExportService,
    MetadataExtractor,
    PaperService,
    SearchService,
    SystemService,
)
from .add_dialog import AddDialog
from .filter_dialog import FilterDialog
from .sort_dialog import SortDialog
from .ui_components import ErrorPanel, PaperListControl, StatusBar
from .edit_dialog import EditDialog
from .collect_dialog import CollectDialog
from .status_messages import StatusMessages


class SmartCompleter(Completer):
    """Smart command completer with subcommand and description support."""

    def __init__(self):
        self.commands = {
            "/add": {
                "description": "Open add dialog or add paper directly (e.g., /add arxiv 2307.10635)",
                "subcommands": {
                    "pdf": "Add from a local PDF file",
                    "arxiv": "Add from an arXiv ID (e.g., 2307.10635)",
                    "dblp": "Add from a DBLP URL",
                    "openreview": "Add from an OpenReview ID (e.g., bq1JEgioLr)",
                    "bib": "Add papers from a BibTeX (.bib) file",
                    "ris": "Add papers from a RIS (.ris) file",
                    "manual": "Add a paper with manual entry",
                },
            },
            "/filter": {
                "description": "Filter papers by specific criteria or search all fields",
                "subcommands": {
                    "all": "Search across all fields (title, author, venue, abstract)",
                    "year": "Filter by publication year (e.g., 2023)",
                    "author": "Filter by author name (e.g., 'Turing')",
                    "venue": "Filter by venue name (e.g., 'NeurIPS')",
                    "type": "Filter by paper type (e.g., 'journal')",
                    "collection": "Filter by collection name (e.g., 'My Papers')",
                },
            },
            "/sort": {
                "description": "Sort the paper list by a field",
                "subcommands": {
                    "title": "Sort by title",
                    "authors": "Sort by author names",
                    "venue": "Sort by venue",
                    "year": "Sort by publication year",
                },
            },
            "/select": {"description": "Enter multi-selection mode", "subcommands": {}},
            "/all": {
                "description": "Show all papers in the database",
                "subcommands": {},
            },
            "/clear": {"description": "Clear all selected papers", "subcommands": {}},
            "/chat": {
                "description": "Chat with an LLM about the selected paper(s)",
                "subcommands": {},
            },
            "/edit": {
                "description": "Open edit dialog or edit field directly (e.g., /edit title ...)",
                "subcommands": {
                    "extract-pdf": "Extract metadata from PDF and update paper",
                    "summarize": "Generate LLM summary and update notes field",
                    "title": "Edit the title",
                    "abstract": "Edit the abstract",
                    "notes": "Edit your personal notes",
                    "venue_full": "Edit the full venue name",
                    "venue_acronym": "Edit the venue acronym",
                    "year": "Edit the publication year",
                    "paper_type": "Edit the paper type (e.g., journal, conference)",
                    "doi": "Edit the DOI",
                    "pages": "Edit the page numbers",
                    "preprint_id": "Edit the preprint ID (e.g., arXiv 2505.15134)",
                    "url": "Edit the paper URL",
                },
            },
            "/export": {
                "description": "Export selected paper(s) to a file or clipboard",
                "subcommands": {
                    "bibtex": "Export to BibTeX format",
                    "markdown": "Export to Markdown format",
                    "html": "Export to HTML format",
                    "json": "Export to JSON format",
                },
            },
            "/delete": {
                "description": "Delete the selected paper(s)",
                "subcommands": {},
            },
            "/open": {
                "description": "Open the PDF for the selected paper(s)",
                "subcommands": {},
            },
            "/detail": {
                "description": "Show detailed metadata for the selected paper(s)",
                "subcommands": {},
            },
            "/help": {"description": "Show the help panel", "subcommands": {}},
            "/log": {"description": "Show the error log panel", "subcommands": {}},
            "/doctor": {
                "description": "Diagnose and fix database/system issues",
                "subcommands": {
                    "diagnose": "Run full diagnostic check",
                    "clean": "Clean orphaned database records",
                    "help": "Show doctor command help",
                },
            },
            "/add-to": {
                "description": "Add selected paper(s) to a collection",
                "subcommands": {},
            },
            "/remove-from": {
                "description": "Remove selected paper(s) from a collection",
                "subcommands": {},
            },
            "/collect": {
                "description": "Manage collections",
                "subcommands": {},
            },
            "/version": {
                "description": "Show version information and check for updates",
                "subcommands": {
                    "check": "Check for available updates",
                    "update": "Update to the latest version (if possible)",
                    "info": "Show detailed version information",
                },
            },
            "/exit": {"description": "Exit the application", "subcommands": {}},
        }

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()

        # Completion for main commands
        if len(words) <= 1 and not text.endswith(" "):
            partial_cmd = words[0] if words else ""
            for cmd, data in self.commands.items():
                if cmd.startswith(partial_cmd):
                    yield Completion(
                        cmd,
                        start_position=-len(partial_cmd),
                        display_meta=data["description"],
                    )

        # Completion for subcommands
        elif len(words) == 1 and text.endswith(" "):
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                if subcommands:
                    for subcmd, description in subcommands.items():
                        yield Completion(
                            subcmd, start_position=0, display_meta=description
                        )

        # Completion for partial subcommands
        elif len(words) == 2 and not text.endswith(" "):
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                partial_subcmd = words[1]
                for subcmd, description in subcommands.items():
                    if subcmd.startswith(partial_subcmd):
                        yield Completion(
                            subcmd,
                            start_position=-len(partial_subcmd),
                            display_meta=description,
                        )


class PaperCLI:
    """Main CLI application class."""

    HELP_TEXT = """
PaperCLI Help
=============

Core Commands:
--------------
/add      Open add dialog or add paper directly (e.g., /add arxiv 2307.10635)
/filter   Filter papers by criteria or search all fields (e.g., /filter all keyword)
/sort     Open sort dialog or sort directly (e.g., /sort title asc)
/all      Show all papers in the database
/select   Enter multi-selection mode to act on multiple papers
/clear    Clear all selected papers
/help     Show this help panel (or press F1)
/log      Show the error log panel
/exit     Exit the application (or press Ctrl+C)

Paper Operations (work on the paper under the cursor ► or selected papers ✓):
-----------------------------------------------------------------------------
/chat     Chat with an LLM about the paper(s)
/edit     Open edit dialog or edit field directly (e.g., /edit title ...)
/open     Open the PDF for the paper(s)
/detail   Show detailed metadata for the paper(s)
/export   Export paper(s) to a file or clipboard (BibTeX, Markdown, etc.)
/delete   Delete the paper(s) from the library

Collection Management:
---------------------
/collect     Manage collections
/add-to      Add selected paper(s) to a collection
/remove-from Remove selected paper(s) from a collection

System Commands:
---------------
/doctor      Diagnose and fix database/system issues
  diagnose   Run full diagnostic check (default)
  clean      Clean orphaned database records and PDF files
  help       Show doctor command help
/version     Show version info and check for updates
  check      Check for available updates
  update     Update to latest version (if possible)
  info       Show detailed version information

Navigation & Interaction:
-------------------------
↑/↓       Navigate the paper list or scroll panels
PageUp/↓  Scroll panels by a full page
Space     Toggle selection for a paper (only in /select mode)
Enter     Execute a command from the input bar
ESC       Close panels (Help, Error), exit selection mode, or clear input
Tab       Trigger and cycle through auto-completions

Indicators (in the first column):
---------------------------------
►         Indicates the current line (cursor).
  ✓       Indicates a selected paper.
  □       Indicates an unselected paper (in /select mode).
► ✓       Indicates that the current line is also selected.
► □       Indicates the current line is not selected (in /select mode).
"""

    def __init__(self, db_path: str):
        self.db_path = db_path

        # Initialize database if not already done
        from .database import init_database, get_pdf_directory

        init_database(db_path)

        # Initialize services
        self.paper_service = PaperService()
        self.search_service = SearchService()
        self.author_service = AuthorService()
        self.collection_service = CollectionService()
        self.metadata_extractor = MetadataExtractor(self._add_log)
        self.export_service = ExportService()
        self.chat_service = ChatService(self._add_log)
        self.system_service = SystemService()
        self.db_health_service = DatabaseHealthService()

        # UI state
        self.smart_completer = SmartCompleter()
        self.current_papers: List[Paper] = []
        self.paper_list_control = PaperListControl([])
        self.status_bar = StatusBar()
        self.error_panel = ErrorPanel()
        self.in_select_mode = False
        self.show_help = False
        self.show_error_panel = False
        self.show_details_panel = False
        self.is_filtered_view = False
        self.edit_dialog = None
        self.edit_float = None
        self.add_dialog = None
        self.add_float = None
        self.filter_dialog = None
        self.filter_float = None
        self.sort_dialog = None
        self.sort_float = None
        self.collect_dialog = None
        self.collect_float = None
        self.logs = []

        # Load initial papers
        self.load_papers()

        # Setup UI
        self.setup_layout()
        self.setup_key_bindings()
        self.setup_application()

    def _add_log(self, action: str, details: str):
        """Add a log entry."""

        self.logs.append(
            {"timestamp": datetime.now(), "action": action, "details": details}
        )

    def handle_log_command(self):
        """Handle /log command."""
        if not self.logs:
            log_content = "No activities logged in this session."
        else:
            log_entries = []
            for log in reversed(self.logs):
                log_entries.append(
                    f"[{log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {log['action']}: {log['details']}"
                )
            log_content = "\n".join(log_entries)

        self.show_help_dialog(log_content, "Activity Log")
        self.status_bar.set_status("📜 Activity log opened - Press ESC to close")

    def handle_doctor_command(self, args: List[str]):
        """Handle /doctor command for database diagnostics and cleanup."""
        try:
            action = args[0] if args else "diagnose"

            if action == "diagnose":
                self.status_bar.set_status("🔍 Running diagnostic checks...")
                report = self.db_health_service.run_full_diagnostic()
                self._show_doctor_report(report)

            elif action == "clean":
                self.status_bar.set_status("🧹 Cleaning orphaned records and files...")
                cleaned_records = self.db_health_service.clean_orphaned_records()
                cleaned_pdfs = self.db_health_service.clean_orphaned_pdfs()

                total_cleaned_records = sum(cleaned_records.values())
                total_cleaned_pdfs = sum(cleaned_pdfs.values())

                if total_cleaned_records > 0 or total_cleaned_pdfs > 0:
                    details = []
                    if total_cleaned_records > 0:
                        details.append(f"• Records: {total_cleaned_records}")
                    if total_cleaned_pdfs > 0:
                        details.append(f"• PDF files: {total_cleaned_pdfs}")

                    message = f"✓ Cleaned orphaned items"
                    self.show_error_panel_with_message(
                        "PaperCLI Doctor - Cleanup Complete",
                        message,
                        "\n".join(details),
                    )
                    self.status_bar.set_success(f"Database cleanup complete")
                else:
                    self.status_bar.set_success(
                        "No orphaned items found - database is clean"
                    )

            elif action == "help":
                help_text = """Database Doctor Commands:

/doctor                 - Run full diagnostic check
/doctor diagnose        - Run full diagnostic check  
/doctor clean           - Clean orphaned database records and PDF files
/doctor help            - Show this help

The doctor command helps maintain database health by:
• Checking database integrity and structure
• Detecting orphaned association records and PDF files
• Verifying system dependencies  
• Checking terminal capabilities
• Providing automated cleanup"""

                self.show_help_dialog(help_text, "Database Doctor Help")

            else:
                self.status_bar.set_error(
                    f"Unknown doctor action: {action}. Use 'diagnose', 'clean', or 'help'"
                )

        except Exception as e:
            self.show_error_panel_with_message(
                "PaperCLI Doctor - Error",
                f"Failed to run doctor command: {str(e)}",
                f"Action: {action if 'action' in locals() else 'unknown'}\nError details: {traceback.format_exc()}",
            )

    def _show_doctor_report(self, report: dict):
        """Display the doctor diagnostic report."""
        # Create formatted report text
        lines = [
            f"Database Doctor Report - {report['timestamp'][:19]}",
            "=" * 60,
            "",
            "📊 DATABASE HEALTH:",
        ]

        db_checks = report["database_checks"]
        lines.extend(
            [
                f"  Database exists: {'✓' if db_checks['database_exists'] else '✗'}",
                f"  Tables exist: {'✓' if db_checks['tables_exist'] else '✗'}",
                f"  Database size: {db_checks.get('database_size', 0) // 1024} KB",
                f"  Foreign key constraints: {'✓' if db_checks['foreign_key_constraints'] else '✗'}",
            ]
        )

        if db_checks.get("table_counts"):
            lines.append("  Table counts:")
            for table, count in db_checks["table_counts"].items():
                lines.append(f"    {table}: {count}")

        lines.extend(["", "🔗 ORPHANED RECORDS:"])
        orphaned_records = report["orphaned_records"]["summary"]
        pc_count = orphaned_records.get("orphaned_paper_collections", 0)
        pa_count = orphaned_records.get("orphaned_paper_authors", 0)
        lines.extend(
            [
                f"  Paper-collection associations: {pc_count}",
                f"  Paper-author associations: {pa_count}",
            ]
        )

        orphaned_pdfs = report.get("orphaned_pdfs", {}).get("summary", {})
        pdf_count = orphaned_pdfs.get("orphaned_pdf_files", 0)
        if pdf_count > 0:
            lines.append(f"  Orphaned PDF files: {pdf_count}")

        lines.extend(["", "💻 SYSTEM HEALTH:"])
        sys_checks = report["system_checks"]
        lines.append(f"  Python version: {sys_checks['python_version']}")
        lines.append("  Dependencies:")
        for dep, status in sys_checks["dependencies"].items():
            lines.append(f"    {dep}: {status}")

        if "disk_space" in sys_checks and "free_mb" in sys_checks["disk_space"]:
            lines.append(f"  Free disk space: {sys_checks['disk_space']['free_mb']} MB")

        lines.extend(["", "🖥️  TERMINAL SETUP:"])
        term_checks = report["terminal_checks"]
        lines.extend(
            [
                f"  Terminal type: {term_checks['terminal_type']}",
                f"  Unicode support: {'✓' if term_checks['unicode_support'] else '✗'}",
                f"  Color support: {'✓' if term_checks['color_support'] else '✗'}",
            ]
        )

        if "terminal_size" in term_checks and "columns" in term_checks["terminal_size"]:
            size = term_checks["terminal_size"]
            lines.append(f"  Terminal size: {size['columns']}x{size['lines']}")

        # Issues and recommendations
        if report["issues_found"]:
            lines.extend(["", "⚠ ISSUES FOUND:"])
            for issue in report["issues_found"]:
                lines.append(f"  • {issue}")

        if report["recommendations"]:
            lines.extend(["", "💡 RECOMMENDATIONS:"])
            for rec in report["recommendations"]:
                lines.append(f"  • {rec}")

        if pc_count > 0 or pa_count > 0:
            lines.extend(["", "🧹 To clean orphaned records, run: /doctor clean"])

        report_text = "\n".join(lines)

        # Show in error panel (reusing for display)
        issues_count = len(report["issues_found"])
        status = (
            "✓ System healthy"
            if issues_count == 0
            else f"⚠ {issues_count} issues found"
        )

        self.show_help_dialog(report_text, "Database Doctor Report")

    def load_papers(self):
        """Load papers from database."""
        try:
            # Preserve selection state using paper IDs
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
                StatusMessages.papers_loaded(len(self.current_papers))
            )
        except Exception as e:
            self.status_bar.set_error(f"Error loading papers: {e}")
            self.current_papers = []
            self.paper_list_control = PaperListControl(self.current_papers)

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
                    f"✓ Toggled selection. Selected: {selected_count} papers"
                )
                event.app.invalidate()  # Force refresh of UI
            else:
                # Default behavior - add space to main input buffer
                self.input_buffer.insert_text(" ")

        # Command input
        @self.kb.add("enter")
        def handle_enter(event):
            # If an edit dialog is open and a multiline TextArea is focused, insert a newline.
            if self.edit_dialog and hasattr(event.app.layout.current_control, "buffer"):
                current_buffer = event.app.layout.current_control.buffer
                if (
                    current_buffer
                    in [f.buffer for f in self.edit_dialog.input_fields.values()]
                    and current_buffer.multiline()
                ):
                    current_buffer.insert_text("\n")
                    return  # Consume the event

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
                        f"← Exited selection mode ({selected_count} papers remain selected)"
                    )
                else:
                    self.status_bar.set_status("← Exited selection mode")
                event.app.invalidate()

        # Function key bindings
        @self.kb.add("f1")
        def show_help(event):
            self.show_help_dialog(self.HELP_TEXT, "PaperCLI Help")

        @self.kb.add("f2")
        def add_paper(event):
            self.show_add_dialog()

        @self.kb.add("f3")
        def open_paper(event):
            self.handle_open_command()

        @self.kb.add("f4")
        def show_detail(event):
            self.handle_detail_command()

        @self.kb.add("f5")
        def edit_paper(event):
            self.handle_edit_command()

        @self.kb.add("f6")
        def delete_paper(event):
            self.handle_delete_command()

        @self.kb.add("f7")
        def manage_collections(event):
            self.handle_collect_command()

        @self.kb.add("f8")
        def filter_papers(event):
            self.show_filter_dialog()

        @self.kb.add("f9")
        def show_all_papers(event):
            self.handle_all_command()

        @self.kb.add("f10")
        def sort_papers(event):
            self.show_sort_dialog()

        @self.kb.add("f11")
        def toggle_select_mode(event):
            self.handle_select_command()

        @self.kb.add("f12")
        def clear_selection(event):
            self.handle_clear_command()

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
                self.status_bar.set_status("← Closed error panel")
                event.app.invalidate()
                return
            elif self.show_help:
                self.show_help = False
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed help panel")
                event.app.invalidate()
                return
            elif self.show_details_panel:
                self.show_details_panel = False
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed details panel")
                event.app.invalidate()
                return
            elif self.edit_dialog is not None:
                self.app.layout.container.floats.remove(self.edit_float)
                self.edit_dialog = None
                self.edit_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed edit dialog")
                event.app.invalidate()
                return
            elif self.add_dialog is not None:
                self.app.layout.container.floats.remove(self.add_float)
                self.add_dialog = None
                self.add_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed add dialog")
                event.app.invalidate()
                return
            elif self.filter_dialog is not None:
                self.app.layout.container.floats.remove(self.filter_float)
                self.filter_dialog = None
                self.filter_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed filter dialog")
                event.app.invalidate()
                return
            elif self.sort_dialog is not None:
                self.app.layout.container.floats.remove(self.sort_float)
                self.sort_dialog = None
                self.sort_float = None
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("← Closed sort dialog")
                event.app.invalidate()
                return
            elif self.in_select_mode:
                self.in_select_mode = False
                self.paper_list_control.in_select_mode = False
                selected_count = len(self.paper_list_control.selected_paper_ids)
                if selected_count > 0:
                    self.status_bar.set_status(
                        f"← Exited selection mode ({selected_count} papers remain selected)"
                    )
                else:
                    self.status_bar.set_status("← Exited selection mode")
                event.app.invalidate()
                return
            else:
                self.input_buffer.text = ""
                self.status_bar.set_status("🧹 Input cleared")

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

        # Paper list window
        self.paper_list_window = Window(
            content=FormattedTextControl(
                text=lambda: self.paper_list_control.get_formatted_text()
            ),
            scroll_offsets=ScrollOffsets(top=1, bottom=1),
            wrap_lines=False,
        )

        # Input window with prompt
        from prompt_toolkit.layout.processors import BeforeInput

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

    def _get_help_key_bindings(self):
        """Key bindings for the help dialog for intuitive scrolling."""
        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            scroll.scroll_one_line_up(event)

        @kb.add("down")
        def _(event):
            scroll.scroll_one_line_down(event)

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
        from prompt_toolkit.application import get_app

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
        from prompt_toolkit.application import get_app

        try:
            width = get_app().output.get_size().columns
        except Exception:
            width = 120  # Fallback

        # Function key shortcuts with configurable spacing
        shortkey_spacing = "    "  # Adjust this to control spacing between shortcuts
        shortcuts = [
            "F1: Help",
            "F2: Add",
            "F3: Open",
            "F4: Detail",
            "F5: Edit",
            "F6: Delete",
            "F7: Collect",
            "F8: Filter",
            "F9: All",
            "F10: Sort",
            "F11: Select",
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
        from prompt_toolkit.key_binding import merge_key_bindings
        from prompt_toolkit.key_binding.defaults import load_key_bindings

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

        # Set initial focus to input buffer
        self.app.layout.focus(self.input_buffer)

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
            self.status_bar.set_warning(StatusMessages.no_papers_selected())
            return None

        return target_papers

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
                if cmd == "/add":
                    self.handle_add_command(parts[1:])
                elif cmd == "/filter":
                    self.handle_filter_command(parts[1:])
                elif cmd == "/select":
                    self.handle_select_command()
                elif cmd == "/all":
                    self.handle_all_command()
                elif cmd == "/help":
                    self.show_help_dialog(self.HELP_TEXT, "PaperCLI Help")
                elif cmd == "/log":
                    self.handle_log_command()
                elif cmd == "/doctor":
                    self.handle_doctor_command(parts[1:])
                elif cmd == "/chat":
                    self.handle_chat_command()
                elif cmd == "/edit":
                    self.handle_edit_command(parts[1:])
                elif cmd == "/export":
                    self.handle_export_command(parts[1:])
                elif cmd == "/delete":
                    self.handle_delete_command()
                elif cmd == "/open":
                    self.handle_open_command()
                elif cmd == "/detail":
                    self.handle_detail_command()
                elif cmd == "/clear":
                    self.handle_clear_command()
                elif cmd == "/exit":
                    self.handle_exit_command()
                elif cmd == "/sort":
                    self.handle_sort_command(parts[1:])
                elif cmd == "/add-to":
                    self.handle_add_to_command(parts[1:])
                elif cmd == "/remove-from":
                    self.handle_remove_from_command(parts[1:])
                elif cmd == "/collect":
                    self.handle_collect_command()
                elif cmd == "/version":
                    self.handle_version_command(parts[1:])
            else:
                self.status_bar.set_error(f"Unknown command: {cmd}")

        except Exception as e:
            # Show detailed error in error panel instead of just status bar
            self.show_error_panel_with_message(
                "Command Error",
                f"Failed to execute command: {command}",
                traceback.format_exc(),
            )

    def handle_all_command(self):
        """Handle /all command - return to full paper list."""
        if self.in_select_mode:
            # Don't exit selection mode, just show all papers while maintaining selection
            self.load_papers()
            self.status_bar.set_status(f"📚 Showing all papers (selection mode active)")
        else:
            # Return to full list from search/filter results
            self.load_papers()
            self.is_filtered_view = False
            self.status_bar.set_status(
                f"📚 Showing all {len(self.current_papers)} papers."
            )

    def handle_clear_command(self):
        """Handle /clear command - deselect all papers."""
        if not self.paper_list_control.selected_paper_ids:
            self.status_bar.set_status("No papers were selected.")
            return

        count = len(self.paper_list_control.selected_paper_ids)
        self.paper_list_control.selected_paper_ids.clear()
        self.status_bar.set_success(f"Cleared {count} selected paper(s).")

    def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        try:
            # Simple command-line based add
            if len(args) > 0:
                # Quick add from command line arguments
                if args[0] == "arxiv" and len(args) > 1:
                    self._quick_add_arxiv(args[1])
                elif args[0] == "dblp" and len(args) > 1:
                    self._quick_add_dblp(
                        " ".join(args[1:])
                    )  # Support URLs with parameters
                elif args[0] == "openreview" and len(args) > 1:
                    self._quick_add_openreview(args[1])
                elif args[0] == "pdf" and len(args) > 1:
                    self._quick_add_pdf(" ".join(args[1:]))
                elif args[0] == "bib" and len(args) > 1:
                    self._quick_add_bib(" ".join(args[1:]))
                elif args[0] == "ris" and len(args) > 1:
                    self._quick_add_ris(" ".join(args[1:]))
                elif args[0] == "manual":
                    self._add_manual_paper()
                else:
                    self.status_bar.set_status(
                        "📝 Usage: /add [arxiv <id>|dblp <url>|openreview <id>|pdf <path>|bib <path>|ris <path>|manual]"
                    )
            else:
                # Open add dialog when no arguments provided
                self.show_add_dialog()

        except Exception as e:
            self.status_bar.set_error(f"Error adding paper: {e}")

    def _quick_add_arxiv(self, arxiv_id: str):
        """Quickly add a paper from arXiv."""
        try:
            self.status_bar.set_status(f"📡 Fetching arXiv paper {arxiv_id}...")

            # Extract metadata from arXiv
            metadata = self.metadata_extractor.extract_from_arxiv(arxiv_id)

            # Prepare paper data (without PDF initially)
            paper_data = {
                "title": metadata["title"],
                "abstract": metadata.get("abstract", ""),
                "year": metadata.get("year"),
                "venue_full": metadata.get("venue_full", ""),
                "venue_acronym": metadata.get("venue_acronym", ""),
                "paper_type": metadata.get("paper_type", "preprint"),
                "preprint_id": metadata.get("preprint_id"),
                "doi": metadata.get("doi"),
                "url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            }

            # Add to database first (without PDF)
            authors = metadata.get("authors", [])
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Download PDF
            pdf_dir = get_pdf_directory()
            self.status_bar.set_status(f"📡 Downloading PDF for {arxiv_id}...")
            pdf_path, pdf_error = self.system_service.download_pdf("arxiv", arxiv_id, pdf_dir, paper_data)

            if pdf_path:
                self._add_log("add_arxiv", f"PDF download successful: {pdf_path}")
                # Update paper with local PDF path (this will generate proper filename with authors)
                updated_paper, error = self.paper_service.update_paper(
                    paper.id, {"pdf_path": pdf_path}
                )
                if error:
                    self.status_bar.set_error(
                        f"Failed to update PDF path for '{paper.title}': {error}"
                    )
                    self.show_error_panel_with_message(
                        "Database Update Error",
                        f"Failed to update PDF path for '{paper.title}'",
                        str(error),
                    )
                else:
                    self._add_log(
                        "add_arxiv", f"Database updated with PDF path: {pdf_path}"
                    )
            else:
                # Continue without PDF but show warning
                self.status_bar.set_error(f"PDF download failed for arXiv {arxiv_id}")
                self.show_error_panel_with_message(
                    "PDF Download Warning",
                    f"Could not download PDF for arXiv paper: {arxiv_id}",
                    pdf_error or "The paper metadata will still be added, but without the PDF file.",
                )

            # Refresh display
            self.load_papers()
            self._add_log("add_arxiv", f"Added arXiv paper '{paper.title}'")
            self.status_bar.set_status(StatusMessages.paper_added(paper.title))

        except Exception as e:
            self.show_error_panel_with_message(
                "Add arXiv Paper Error",
                f"Failed to add arXiv paper: {arxiv_id}",
                traceback.format_exc(),
            )

    def _quick_add_dblp(self, dblp_url: str):
        """Quickly add a paper from DBLP URL."""
        try:
            self.status_bar.set_status(
                f"🌐 Fetching DBLP paper from {dblp_url[:50]}..."
            )

            # Extract metadata from DBLP
            metadata = self.metadata_extractor.extract_from_dblp(dblp_url)

            # Prepare paper data
            paper_data = {
                "title": metadata.get("title", "Unknown Title"),
                "abstract": metadata.get("abstract", ""),
                "year": metadata.get("year"),
                "venue_full": metadata.get("venue_full", ""),
                "venue_acronym": metadata.get("venue_acronym", ""),
                "paper_type": metadata.get("paper_type", "conference"),
                "doi": metadata.get("doi"),
                "url": metadata.get("url", dblp_url),
            }

            # Add to database
            authors = metadata.get("authors", [])
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Refresh display
            self.load_papers()
            self._add_log("add_dblp", f"Added DBLP paper '{paper.title}'")
            self.status_bar.set_success(f"Added: {paper.title[:50]}...")

        except Exception as e:
            self.show_error_panel_with_message(
                "Add DBLP Paper Error",
                f"Failed to add DBLP paper: {dblp_url}",
                traceback.format_exc(),
            )

    def _quick_add_openreview(self, openreview_id: str):
        """Quickly add a paper from OpenReview."""
        try:
            self.status_bar.set_status(
                f"🔬 Fetching OpenReview paper {openreview_id}..."
            )

            # Extract metadata from OpenReview
            metadata = self.metadata_extractor.extract_from_openreview(openreview_id)

            # Prepare paper data
            paper_data = {
                "title": metadata.get("title", "Unknown Title"),
                "abstract": metadata.get("abstract", ""),
                "year": metadata.get("year"),
                "venue_full": metadata.get("venue_full", ""),
                "venue_acronym": metadata.get("venue_acronym", ""),
                "paper_type": metadata.get("paper_type", "conference"),
                "category": metadata.get("category"),
                "url": metadata.get(
                    "url", f"https://openreview.net/forum?id={openreview_id}"
                ),
            }

            # Add to database
            authors = metadata.get("authors", [])
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Download PDF
            pdf_dir = get_pdf_directory()
            self._add_log("add_openreview", f"Attempting to download PDF to {pdf_dir}")
            pdf_path, pdf_error = self.system_service.download_pdf(
                "openreview", openreview_id, pdf_dir, paper_data
            )

            if pdf_path:
                self._add_log("add_openreview", f"PDF download successful: {pdf_path}")
                # Update paper with local PDF path
                updated_paper, error = self.paper_service.update_paper(
                    paper.id, {"pdf_path": pdf_path}
                )
                if error:
                    self.status_bar.set_error(
                        f"Failed to update PDF path for '{paper.title}': {error}"
                    )
                    self.show_error_panel_with_message(
                        "Database Update Error",
                        f"Failed to update PDF path for '{paper.title}'",
                        str(error),
                    )
                else:
                    self._add_log(
                        "add_openreview", f"Database updated with PDF path: {pdf_path}"
                    )
            else:
                self.status_bar.set_error(f"PDF download failed for '{paper.title}'")
                self.show_error_panel_with_message(
                    "PDF Download Error",
                    f"PDF download failed for '{paper.title}'",
                    pdf_error or "Please check the network connection or the paper's availability.",
                )

            # Refresh display
            self.load_papers()
            self._add_log("add_openreview", f"Added OpenReview paper '{paper.title}'")
            self.status_bar.set_success(f"Added: {paper.title[:50]}...")

        except Exception as e:
            self.show_error_panel_with_message(
                "Add OpenReview Paper Error",
                f"Failed to add OpenReview paper: {openreview_id}",
                traceback.format_exc(),
            )

    def _quick_add_pdf(self, pdf_path: str):
        """Quickly add a paper from local PDF file."""
        try:
            # Expand user path and resolve relative paths
            pdf_path = os.path.expanduser(pdf_path)
            pdf_path = os.path.abspath(pdf_path)

            # Check if file exists
            if not os.path.exists(pdf_path):
                self.status_bar.set_error(f"PDF file not found: {pdf_path}")
                return

            # Check if it's a PDF file
            if not pdf_path.lower().endswith(".pdf"):
                self.status_bar.set_error("File must be a PDF")
                return

            self.status_bar.set_status(
                f"📄 Processing PDF: {os.path.basename(pdf_path)}..."
            )

            # Extract metadata from PDF using LLM
            metadata = self.metadata_extractor.extract_from_pdf(pdf_path)
            if not metadata:
                self.status_bar.set_error("Failed to extract metadata from PDF")
                return

            # Copy PDF to pdfs folder
            pdf_dir = get_pdf_directory()

            # Generate smart filename using PDFManager
            from .services import PDFManager

            pdf_manager = PDFManager()
            filename = pdf_manager._generate_pdf_filename(metadata, pdf_path)
            target_path = os.path.join(pdf_dir, filename)

            # Copy the file
            import shutil

            shutil.copy2(pdf_path, target_path)

            # Prepare paper data
            paper_data = {
                "title": metadata.get("title", "Unknown Title"),
                "abstract": metadata.get("abstract", ""),
                "year": metadata.get("year"),
                "venue_full": metadata.get("venue_full", ""),
                "venue_acronym": metadata.get("venue_acronym", ""),
                "paper_type": metadata.get("paper_type", "conference"),
                "category": metadata.get("category"),
                "url": metadata.get("url", ""),
                "pdf_path": target_path,
            }

            # Add to database
            authors = metadata.get("authors", [])
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Refresh display
            self.load_papers()
            self._add_log("add_pdf", f"Added PDF paper '{paper.title}'")
            self.status_bar.set_success(f"Added: {paper.title[:50]}...")

        except Exception as e:
            self.show_error_panel_with_message(
                "Add PDF Paper Error",
                f"Failed to add PDF paper: {pdf_path}",
                traceback.format_exc(),
            )

    def _quick_add_bib(self, bib_path: str):
        """Quickly add papers from .bib file."""
        try:
            # Expand user path and resolve relative paths
            bib_path = os.path.expanduser(bib_path)
            bib_path = os.path.abspath(bib_path)

            # Check if file exists
            if not os.path.exists(bib_path):
                self.status_bar.set_error(f"BibTeX file not found: {bib_path}")
                return

            # Check if it's a .bib file
            if not bib_path.lower().endswith(".bib"):
                self.status_bar.set_error("File must be a .bib file")
                return

            self.status_bar.set_status(
                f"📚 Processing BibTeX: {os.path.basename(bib_path)}..."
            )

            # Extract metadata from BibTeX file
            papers_metadata = self.metadata_extractor.extract_from_bibtex(bib_path)
            if not papers_metadata:
                self.status_bar.set_error("Failed to extract metadata from BibTeX file")
                return

            added_count = 0
            for metadata in papers_metadata:
                # Prepare paper data
                paper_data = {
                    "title": metadata.get("title", "Unknown Title"),
                    "abstract": metadata.get("abstract", ""),
                    "year": metadata.get("year"),
                    "venue_full": metadata.get("venue_full", ""),
                    "venue_acronym": metadata.get("venue_acronym", ""),
                    "paper_type": metadata.get("paper_type", "conference"),
                    "category": metadata.get("category"),
                    "url": metadata.get("url", ""),
                    "pdf_path": metadata.get("pdf_path"),
                    "doi": metadata.get("doi"),
                    "preprint_id": metadata.get("preprint_id"),
                    "volume": metadata.get("volume"),
                    "issue": metadata.get("issue"),
                    "pages": metadata.get("pages"),
                }

                # Add to database
                authors = metadata.get("authors", [])
                collections = []

                try:
                    paper = self.paper_service.add_paper_from_metadata(
                        paper_data, authors, collections
                    )
                    added_count += 1
                    self._add_log("add_bib", f"Added paper '{paper.title}' from BibTeX")
                except Exception as e:
                    self.show_error_panel_with_message(
                        "Add BibTeX Paper Error",
                        f"Failed to add paper '{metadata.get('title', 'Unknown')}' from BibTeX",
                        traceback.format_exc(),
                    )

            # Refresh display
            self.load_papers()
            self.status_bar.set_success(f"Added {added_count} papers from BibTeX file")

        except Exception as e:
            self.show_error_panel_with_message(
                "Add BibTeX Papers Error",
                f"Failed to add papers from BibTeX file: {bib_path}",
                traceback.format_exc(),
            )

    def _quick_add_ris(self, ris_path: str):
        """Quickly add papers from .ris file."""
        try:
            # Expand user path and resolve relative paths
            ris_path = os.path.expanduser(ris_path)
            ris_path = os.path.abspath(ris_path)

            # Check if file exists
            if not os.path.exists(ris_path):
                self.status_bar.set_error(f"RIS file not found: {ris_path}")
                return

            # Check if it's a .ris file
            if not ris_path.lower().endswith(".ris"):
                self.status_bar.set_error("File must be a .ris file")
                return

            self.status_bar.set_status(
                f"📚 Processing RIS: {os.path.basename(ris_path)}..."
            )

            # Extract metadata from RIS file
            papers_metadata = self.metadata_extractor.extract_from_ris(ris_path)
            if not papers_metadata:
                self.status_bar.set_error("Failed to extract metadata from RIS file")
                return

            added_count = 0
            for metadata in papers_metadata:
                # Prepare paper data
                paper_data = {
                    "title": metadata.get("title", "Unknown Title"),
                    "abstract": metadata.get("abstract", ""),
                    "year": metadata.get("year"),
                    "venue_full": metadata.get("venue_full", ""),
                    "venue_acronym": metadata.get("venue_acronym", ""),
                    "paper_type": metadata.get("paper_type", "conference"),
                    "category": metadata.get("category"),
                    "url": metadata.get("url", ""),
                    "pdf_path": metadata.get("pdf_path"),
                    "doi": metadata.get("doi"),
                    "preprint_id": metadata.get("preprint_id"),
                    "volume": metadata.get("volume"),
                    "issue": metadata.get("issue"),
                    "pages": metadata.get("pages"),
                }

                # Add to database
                authors = metadata.get("authors", [])
                collections = []

                try:
                    paper = self.paper_service.add_paper_from_metadata(
                        paper_data, authors, collections
                    )
                    added_count += 1
                    self._add_log("add_ris", f"Added paper '{paper.title}' from RIS")
                except Exception as e:
                    self.show_error_panel_with_message(
                        "Add RIS Paper Error",
                        f"Failed to add paper '{metadata.get('title', 'Unknown')}' from RIS",
                        traceback.format_exc(),
                    )

            # Refresh display
            self.load_papers()
            self.status_bar.set_success(f"Added {added_count} papers from RIS file")

        except Exception as e:
            self.show_error_panel_with_message(
                "Add RIS Papers Error",
                f"Failed to add papers from RIS file: {ris_path}",
                traceback.format_exc(),
            )

    def _add_manual_paper(self):
        """Add a paper manually with user input."""
        try:
            # For now, create a basic manual paper
            # This could be enhanced with a proper input dialog
            self.status_bar.set_status(
                f"✏️ Manual paper entry - using defaults (enhance with dialog later)"
            )

            paper_data = {
                "title": "Manually Added Paper",
                "abstract": "This paper was added manually via PaperCLI.",
                "year": 2024,
                "venue_full": "User Input",
                "venue_acronym": "UI",
                "paper_type": "journal",
                "notes": "Added manually - please update metadata",
            }

            authors = ["Manual User"]
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Refresh display
            self.load_papers()
            self._add_log("add_manual", f"Added manual paper '{paper.title}'")
            self.status_bar.set_status(
                f"📝 Added manual paper: {paper.title} (use /update to edit metadata)"
            )

        except Exception as e:
            self.show_error_panel_with_message(
                "Add Manual Paper Error",
                "Failed to add manual paper",
                traceback.format_exc(),
            )

    def handle_filter_command(self, args: List[str]):
        """Handle /filter command."""
        try:
            if len(args) < 1:
                self.status_bar.set_status(
                    "Usage: /filter <field> <value> OR /filter all <query>. Fields: year, author, venue, type, collection, all"
                )
                return

            # Parse command-line filter: /filter <field> <value>
            field = args[0].lower()

            # Handle "all" field - search across all fields
            if field == "all":
                if len(args) < 2:
                    self.status_bar.set_status("Usage: /filter all <query>")
                    return

                query = " ".join(args[1:])
                self.status_bar.set_status(f"🔍 Searching all fields for '{query}'")

                # Perform search across all fields like the old search command
                results = self.search_service.search_papers(
                    query, ["title", "authors", "venue", "abstract"]
                )

                if not results:
                    # Try fuzzy search
                    results = self.search_service.fuzzy_search_papers(query)

                # Update display
                self.current_papers = results
                self.paper_list_control = PaperListControl(self.current_papers)
                self.is_filtered_view = True

                self.status_bar.set_status(
                    f"🎯 Found {len(results)} papers matching '{query}' in all fields"
                )
                return

            # Handle specific field filtering
            if len(args) < 2:
                self.status_bar.set_status(
                    "Usage: /filter <field> <value>. Fields: year, author, venue, type, collection, all"
                )
                return

            value = " ".join(args[1:])

            # Validate field
            valid_fields = ["year", "author", "venue", "type", "collection"]
            if field not in valid_fields:
                self.status_bar.set_error(
                    f"Invalid filter field '{field}'. Valid fields: {', '.join(valid_fields + ['all'])}"
                )
                return

            filters = {}

            # Convert and validate value based on field
            if field == "year":
                try:
                    filters["year"] = int(value)
                except ValueError:
                    self.status_bar.set_error(f"Invalid year value: {value}")
                    return
            elif field == "author":
                filters["author"] = value
            elif field == "venue":
                filters["venue"] = value
            elif field == "type":
                # Validate paper type
                valid_types = [
                    "journal",
                    "conference",
                    "preprint",
                    "website",
                    "book",
                    "thesis",
                ]
                if value.lower() not in valid_types:
                    self.status_bar.set_error(
                        f"Invalid paper type '{value}'. Valid types: {', '.join(valid_types)}"
                    )
                    return
                filters["paper_type"] = value.lower()
            elif field == "collection":
                filters["collection"] = value

            self._add_log("filter_command", f"Command-line filter: {field}={value}")
            self.status_bar.set_status(f"🔽 Applying filters...")

            # Apply filters
            results = self.search_service.filter_papers(filters)

            # Update display
            self.current_papers = results
            self.paper_list_control = PaperListControl(self.current_papers)
            self.is_filtered_view = True

            filter_desc = ", ".join([f"{k}={v}" for k, v in filters.items()])
            self.status_bar.set_status(
                f"🔽 Filtered {len(results)} papers by {filter_desc}"
            )

        except Exception as e:
            import traceback

            self.show_error_panel_with_message(
                "Filter Error",
                f"Error filtering papers: {e}",
                f"Traceback: {traceback.format_exc()}",
            )
            self.status_bar.set_error(f"Error filtering papers: {e}")

    def handle_select_command(self):
        """Handle /select command."""
        self.in_select_mode = True
        self.paper_list_control.in_select_mode = True
        self.status_bar.set_status(StatusMessages.selection_mode_entered())

    def handle_chat_command(self):
        """Handle /chat command."""
        papers_to_chat = self._get_target_papers()
        if not papers_to_chat:
            return

        try:
            self.status_bar.set_status(f"💬 Opening chat interface...")

            # Open chat interface in browser
            result = self.chat_service.open_chat_interface(papers_to_chat)

            # Handle new return format
            if isinstance(result, dict):
                if result["success"]:
                    self.status_bar.set_success(result["message"])
                    # Errors are now logged by the service itself
                else:
                    self.status_bar.set_error(result["message"])
                    self.show_error_panel_with_message(
                        "Chat Error",
                        result["message"],
                        "Failed to open chat interface.",
                    )

        except Exception as e:
            self.status_bar.set_error(f"Error opening chat: {e}")

    def handle_edit_command(self, args: List[str] = None):
        """Handle /edit command."""
        papers_to_update = self._get_target_papers()
        if not papers_to_update:
            return

        try:
            # Handle extract-pdf subcommand
            if args and len(args) == 1 and args[0].lower() == "extract-pdf":
                self._handle_extract_pdf_command(papers_to_update)
                return

            # Handle summarize subcommand
            if args and len(args) == 1 and args[0].lower() == "summarize":
                self._handle_summarize_command(papers_to_update)
                return

            # Parse command line arguments for quick update
            if args and len(args) >= 2:
                # Quick update: /edit field value
                field = args[0].lower()
                value = " ".join(args[1:])  # Support values with spaces

                # Extended field list for comprehensive updating
                valid_fields = [
                    "title",
                    "abstract",
                    "notes",
                    "venue_full",
                    "venue_acronym",
                    "year",
                    "paper_type",
                    "doi",
                    "pages",
                    "preprint_id",
                    "url",
                    "category",
                ]
                if field not in valid_fields:
                    self.status_bar.set_error(
                        f"Usage: /edit [field] <value>. Valid fields: title, abstract, etc."
                    )
                    return

                # Convert year to int if needed
                if field == "year":
                    try:
                        value = int(value)
                    except ValueError:
                        self.status_bar.set_error("Year must be a number")
                        return

                updates = {field: value}
                self.status_bar.set_status(
                    f"🔄 Updating {len(papers_to_update)} paper(s)..."
                )

                # Update papers
                updated_count = 0
                for paper in papers_to_update:
                    try:
                        # Log before and after
                        old_value = getattr(paper, field)
                        updated_paper, error = self.paper_service.update_paper(
                            paper.id, updates
                        )
                        if error:
                            self.status_bar.set_error(f"Update error: {error}")
                            continue
                        self._add_log(
                            "edit",
                            f"Updated '{field}' for paper '{paper.title}'. From '{old_value}' to '{value}'",
                        )
                        updated_count += 1
                    except Exception as e:
                        self.status_bar.set_error(
                            f"Error updating paper {paper.id}: {e}"
                        )
                        break  # Show only first error

                if updated_count > 0:
                    self.load_papers()
                    self.status_bar.set_success(
                        f"Updated '{field}' for {updated_count} paper(s)"
                    )

            else:
                # Use enhanced edit dialog for all cases
                self._show_edit_dialog(papers_to_update)

        except Exception as e:
            self.show_error_panel_with_message(
                "Update Error", f"Failed to update papers", traceback.format_exc()
            )

    def _show_edit_dialog(self, papers):
        if not isinstance(papers, list):
            papers = [papers]

        def callback(result):
            # This callback is executed when the dialog is closed.
            if self.edit_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.edit_float)
            self.edit_dialog = None
            self.edit_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                try:
                    updated_count = 0
                    for paper in papers:
                        # The result from EditDialog now contains proper model objects for relationships
                        # and can be passed directly to the update service.
                        updated_paper, error = self.paper_service.update_paper(
                            paper.id, result
                        )
                        if error:
                            self.status_bar.set_error(f"Update error: {error}")
                            # Show detailed error for PDF processing issues
                            if "PDF processing failed" in error:
                                self.show_error_panel_with_message(
                                    "PDF Processing Error",
                                    f"Failed to process PDF for '{paper.title}'",
                                    error,
                                )
                        else:
                            updated_count += 1

                    self.load_papers()
                    if updated_count > 0:
                        self.status_bar.set_success(
                            f"Updated {updated_count} paper(s)."
                        )
                except Exception as e:
                    self.show_error_panel_with_message(
                        "Update Error",
                        "Failed to update paper(s)",
                        traceback.format_exc(),
                    )
            else:
                self.status_bar.set_status("Update cancelled.")

            self.app.invalidate()

        read_only_fields = []
        if len(papers) == 1:
            paper = papers[0]
            initial_data = {
                field.name: getattr(paper, field.name)
                for field in paper.__table__.columns
            }
            initial_data["authors"] = paper.get_ordered_authors()
            initial_data["collections"] = paper.collections
        else:
            # For multiple papers, show common values or indicate multiple values
            def get_common_value(field):
                values = {getattr(p, field) for p in papers}
                return values.pop() if len(values) == 1 else ""

            initial_data = {
                "title": f"<Editing {len(papers)} papers>",
                "abstract": f"<Editing {len(papers)} papers>",
                "year": get_common_value("year"),
                "venue_full": get_common_value("venue_full"),
                "venue_acronym": get_common_value("venue_acronym"),
                "volume": get_common_value("volume"),
                "issue": get_common_value("issue"),
                "pages": get_common_value("pages"),
                "doi": get_common_value("doi"),
                "preprint_id": get_common_value("preprint_id"),
                "category": get_common_value("category"),
                "url": get_common_value("url"),
                "pdf_path": get_common_value("pdf_path"),
                "paper_type": get_common_value("paper_type") or "conference",
                "notes": get_common_value("notes"),
                "authors": [],
                "collections": [],
            }
            read_only_fields = ["title", "abstract", "author_names", "collections"]

        self.edit_dialog = EditDialog(
            initial_data,
            callback,
            self._add_log,
            self.show_error_panel_with_message,
            read_only_fields=read_only_fields,
        )
        self.edit_float = Float(self.edit_dialog)
        self.app.layout.container.floats.append(self.edit_float)
        self.app.layout.focus(self.edit_dialog.get_initial_focus() or self.edit_dialog)
        self.app.invalidate()

    def _handle_extract_pdf_command(self, papers):
        """Handle /edit extract-pdf command with confirmation dialog."""
        if not isinstance(papers, list):
            papers = [papers]

        if len(papers) > 1:
            self.status_bar.set_error("PDF extraction works with one paper at a time")
            return

        paper = papers[0]
        pdf_path = paper.pdf_path

        if not pdf_path or not os.path.exists(pdf_path):
            self.status_bar.set_error("No PDF file available for this paper")
            return

        try:
            extracted_data = self.metadata_extractor.extract_from_pdf(pdf_path)

            # Prepare changes summary
            changes = []
            field_mapping = {
                "title": "title",
                "authors": "authors",
                "abstract": "abstract",
                "year": "year",
                "venue_full": "venue_full",
                "venue_acronym": "venue_acronym",
                "doi": "doi",
                "url": "url",
                "category": "category",
                "paper_type": "paper_type",
            }

            for extracted_field, paper_field in field_mapping.items():
                if (
                    extracted_field in extracted_data
                    and extracted_data[extracted_field]
                ):
                    new_value = extracted_data[extracted_field]

                    # Get current value
                    if paper_field == "authors":
                        ordered_authors = paper.get_ordered_authors()
                        current_value = (
                            ", ".join([a.full_name for a in ordered_authors])
                            if ordered_authors
                            else ""
                        )
                        new_value = (
                            ", ".join(new_value)
                            if isinstance(new_value, list)
                            else str(new_value)
                        )
                    else:
                        current_value = (
                            str(getattr(paper, paper_field, ""))
                            if getattr(paper, paper_field, None)
                            else ""
                        )
                        new_value = str(new_value) if new_value else ""

                    if current_value != new_value:
                        changes.append(
                            f"{paper_field}: '{current_value}' → '{new_value}'"
                        )

            if not changes:
                self.status_bar.set_status("No changes detected from PDF extraction")
                return

            # Show confirmation dialog
            changes_text = "The following changes will be applied:\n\n" + "\n".join(
                changes
            )

            from prompt_toolkit.widgets import Label
            from prompt_toolkit.layout.containers import Float

            def confirm_apply():
                if hasattr(self, "confirmation_float"):
                    self.app.layout.container.floats.remove(self.confirmation_float)
                self.app.layout.focus(self.input_buffer)

                # Apply changes
                try:
                    updates = {}

                    for extracted_field, paper_field in field_mapping.items():
                        if (
                            extracted_field in extracted_data
                            and extracted_data[extracted_field]
                        ):
                            value = extracted_data[extracted_field]

                            if paper_field == "authors":
                                from .services import AuthorService

                                author_service = AuthorService()
                                if isinstance(value, list):
                                    updates["authors"] = [
                                        author_service.get_or_create_author(name)
                                        for name in value
                                    ]
                            elif paper_field == "year" and isinstance(value, int):
                                updates["year"] = value
                            else:
                                updates[paper_field] = value

                    updated_paper, error = self.paper_service.update_paper(
                        paper.id, updates
                    )
                    if error:
                        self.status_bar.set_error(f"Update error: {error}")
                    else:
                        self.load_papers()
                        self.status_bar.set_success("Paper updated with PDF metadata")
                        self._add_log(
                            "pdf_extract",
                            f"Extracted and applied PDF metadata for '{paper.title}'",
                        )

                except Exception as e:
                    self.status_bar.set_error(f"Error applying changes: {e}")

            def confirm_cancel():
                if hasattr(self, "confirmation_float"):
                    self.app.layout.container.floats.remove(self.confirmation_float)
                self.app.layout.focus(self.input_buffer)
                self.status_bar.set_status("PDF extraction cancelled")

            from prompt_toolkit.widgets import Dialog, Button

            confirmation_dialog = Dialog(
                title="Confirm PDF Metadata Extraction",
                body=Label(text=changes_text, dont_extend_height=True),
                buttons=[
                    Button(text="Yes", handler=confirm_apply),
                    Button(text="No", handler=confirm_cancel),
                ],
                with_background=False,
            )

            self.confirmation_float = Float(content=confirmation_dialog)
            self.app.layout.container.floats.append(self.confirmation_float)
            self.app.layout.focus(confirmation_dialog)

        except Exception as e:
            self.show_error_panel_with_message(
                "PDF Extraction Error",
                f"Failed to extract metadata from PDF: {pdf_path}",
                traceback.format_exc(),
            )

    def _handle_summarize_command(self, papers):
        """Handle /edit summarize command to generate LLM summary for paper(s)."""
        if not isinstance(papers, list):
            papers = [papers]

        from .database import get_pdf_directory

        successful_count = 0
        failed_papers = []

        for paper in papers:
            pdf_path = paper.pdf_path

            if not pdf_path or not os.path.exists(pdf_path):
                failed_papers.append(f"'{paper.title}': No PDF file available")
                continue

            try:
                self.status_bar.set_status(f"🤖 Generating summary for '{paper.title}'...")
                self._add_log("summarize", f"Generating LLM summary for '{paper.title}'")
                
                # Generate summary using LLM
                summary = self.metadata_extractor.generate_paper_summary(pdf_path)
                
                if summary:
                    # Update paper with the generated summary
                    updated_paper, error = self.paper_service.update_paper(
                        paper.id, {"notes": summary}
                    )
                    
                    if error:
                        failed_papers.append(f"'{paper.title}': Database update failed - {error}")
                    else:
                        successful_count += 1
                        self._add_log("summarize", f"Successfully generated summary for '{paper.title}'")
                else:
                    failed_papers.append(f"'{paper.title}': LLM summary generation failed")

            except Exception as e:
                failed_papers.append(f"'{paper.title}': {str(e)}")
                self._add_log("summarize_error", f"Error summarizing '{paper.title}': {traceback.format_exc()}")

        # Update display and show results
        if successful_count > 0:
            self.load_papers()

        # Prepare result message
        if successful_count > 0 and not failed_papers:
            self.status_bar.set_success(f"Generated summaries for {successful_count} paper(s)")
        elif successful_count > 0 and failed_papers:
            self.status_bar.set_success(f"Generated summaries for {successful_count} paper(s), {len(failed_papers)} failed")
            # Show details about failures
            self.show_error_panel_with_message(
                "Partial Summary Success",
                f"Successfully summarized {successful_count} papers, but {len(failed_papers)} failed:",
                "\n".join(failed_papers)
            )
        else:
            self.status_bar.set_error(f"Failed to generate summaries for all {len(failed_papers)} paper(s)")
            if failed_papers:
                self.show_error_panel_with_message(
                    "Summary Generation Failed",
                    "Failed to generate summaries:",
                    "\n".join(failed_papers)
                )

    def show_add_dialog(self):
        """Show the add paper dialog."""

        def callback(result):
            # This callback is executed when the dialog is closed.
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
                        "manual",
                    ]:
                        # Handle subcommand-style addition
                        if path_id:
                            self.handle_add_command([source, path_id])
                        else:
                            self.handle_add_command([source])
                    else:
                        # Treat as manual entry with source as title
                        self.handle_add_command(["manual", source])

                except Exception as e:
                    self.status_bar.set_error(f"Error adding paper: {e}")
            else:
                # Dialog was cancelled
                self.status_bar.set_status("← Cancelled add paper")

        self.add_dialog = AddDialog(callback)
        self.add_float = Float(self.add_dialog)
        self.app.layout.container.floats.append(self.add_float)
        self.app.layout.focus(self.add_dialog.get_initial_focus() or self.add_dialog)
        self.app.invalidate()

    def show_filter_dialog(self):
        """Show the filter papers dialog."""

        def callback(result):
            # This callback is executed when the dialog is closed.
            if self.filter_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.filter_float)
            self.filter_dialog = None
            self.filter_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                try:
                    field = result.get("field", "").strip()
                    value = result.get("value", "").strip()

                    if not field or not value:
                        self.status_bar.set_error("Both field and value are required")
                        return

                    # Call the filter command with the selected field and value
                    self.handle_filter_command([field, value])

                except Exception as e:
                    self.status_bar.set_error(f"Error filtering papers: {e}")
            else:
                # Dialog was cancelled
                self.status_bar.set_status("← Cancelled filter")

        self.filter_dialog = FilterDialog(callback)
        self.filter_float = Float(self.filter_dialog)
        self.app.layout.container.floats.append(self.filter_float)
        self.app.layout.focus(
            self.filter_dialog.get_initial_focus() or self.filter_dialog
        )
        self.app.invalidate()

    def show_sort_dialog(self):
        """Show the sort papers dialog."""

        def callback(result):
            # This callback is executed when the dialog is closed.
            if self.sort_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.sort_float)
            self.sort_dialog = None
            self.sort_float = None
            self.app.layout.focus(self.input_buffer)

            if result:
                try:
                    field, order = result

                    # Call the sort command with the selected field and order
                    self.handle_sort_command([field, order])

                except Exception as e:
                    self.status_bar.set_error(f"Error sorting papers: {e}")
            else:
                # Dialog was cancelled
                self.status_bar.set_status("← Cancelled sort")

        self.sort_dialog = SortDialog(callback)
        self.sort_float = Float(self.sort_dialog)
        self.app.layout.container.floats.append(self.sort_float)
        self.app.layout.focus(self.sort_dialog.get_initial_focus() or self.sort_dialog)
        self.app.invalidate()

    def handle_export_command(self, args: List[str]):
        """Handle /export command."""
        papers_to_export = self._get_target_papers()
        if not papers_to_export:
            return

        try:

            # Parse command line arguments for quick export
            if len(args) >= 1:
                # Quick export: /export bibtex [filename]
                export_format = args[0].lower()

                if export_format not in ["bibtex", "markdown", "html", "json"]:
                    self.status_bar.set_status(
                        f"ℹ Usage: /export <format> [filename]. Formats: bibtex, markdown, html, json"
                    )
                    return

                # Determine destination and filename
                if len(args) >= 2:
                    destination = "file"
                    filename = " ".join(args[1:])
                else:
                    destination = "clipboard"
                    filename = None

                export_params = {
                    "format": export_format,
                    "destination": destination,
                    "filename": filename,
                }
            else:
                # Show usage instead of interactive dialog
                self.status_bar.set_status(
                    f"ℹ Usage: /export <format> [filename]. Formats: bibtex, markdown, html, json"
                )
                return

            self.status_bar.set_status(StatusMessages.export_started())

            # Export papers
            export_format = export_params["format"]
            destination = export_params["destination"]

            if export_format == "bibtex":
                content = self.export_service.export_to_bibtex(papers_to_export)
            elif export_format == "markdown":
                content = self.export_service.export_to_markdown(papers_to_export)
            elif export_format == "html":
                content = self.export_service.export_to_html(papers_to_export)
            elif export_format == "json":
                content = self.export_service.export_to_json(papers_to_export)
            else:
                self.status_bar.set_status("Unknown export format")
                return

            if destination == "file":
                filename = export_params["filename"]
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
                self.status_bar.set_status(
                    f"✓ Exported {len(papers_to_export)} papers to {filename}"
                )

            elif destination == "clipboard":
                if self.system_service.copy_to_clipboard(content):
                    self.status_bar.set_status(
                        f"✓ Copied {len(papers_to_export)} papers to clipboard"
                    )
                else:
                    self.status_bar.set_status("Error copying to clipboard")

        except Exception as e:
            self.status_bar.set_error(f"Error exporting papers: {e}")

    def handle_delete_command(self):
        """Handle /delete command."""
        papers_to_delete = self._get_target_papers()
        if not papers_to_delete:
            return

        future = self.app.loop.create_future()
        future.add_done_callback(lambda future: self.app.layout.container.floats.pop())

        def perform_delete():
            future.set_result(None)
            try:
                paper_ids = [paper.id for paper in papers_to_delete]
                paper_titles = [paper.title for paper in papers_to_delete]
                deleted_count = self.paper_service.delete_papers(paper_ids)
                self.load_papers()
                self._add_log(
                    "delete",
                    f"Deleted {deleted_count} paper(s): {', '.join(paper_titles)}",
                )
                self.status_bar.set_success(f"Deleted {deleted_count} papers")
            except Exception as e:
                self.status_bar.set_error(f"Error during deletion: {e}")

            self.app.invalidate()

        def cancel_delete():
            future.set_result(None)
            self.status_bar.set_error("Deletion cancelled")
            self.app.invalidate()

        paper_titles = [
            paper.title[:50] + "..." if len(paper.title) > 50 else paper.title
            for paper in papers_to_delete
        ]
        dialog_text = (
            f"Are you sure you want to delete {len(papers_to_delete)} papers?\n\n"
            + "\n".join(f"• {title}" for title in paper_titles[:5])
            + (
                f"\n... and {len(paper_titles) - 5} more"
                if len(paper_titles) > 5
                else ""
            )
        )

        # Create handlers that clean up properly
        def cleanup_delete():
            if hasattr(self, "_delete_dialog_active"):
                self._delete_dialog_active = False
            perform_delete()

        def cleanup_cancel():
            if hasattr(self, "_delete_dialog_active"):
                self._delete_dialog_active = False
            cancel_delete()

        confirmation_dialog = Dialog(
            title="Confirm Deletion",
            body=Label(text=dialog_text, dont_extend_height=True),
            buttons=[
                Button(text="Yes", handler=cleanup_delete),
                Button(text="No", handler=cleanup_cancel),
            ],
            with_background=False,
        )

        # Create a flag to track if dialog is active
        self._delete_dialog_active = True

        # Add key binding for ESC to default to "No"
        @self.kb.add(
            "escape",
            filter=Condition(lambda: getattr(self, "_delete_dialog_active", False)),
        )
        def _(event):
            self._delete_dialog_active = False
            cancel_delete()

        dialog_float = Float(content=confirmation_dialog)
        self.app.layout.container.floats.append(dialog_float)
        self.app.layout.focus(confirmation_dialog)
        self.app.invalidate()

    def handle_open_command(self):
        """Handle /open command."""
        papers_to_open = self._get_target_papers()
        if not papers_to_open:
            return

        try:
            opened_count = 0
            for paper in papers_to_open:
                if paper.pdf_path:
                    success, error_msg = self.system_service.open_pdf(paper.pdf_path)
                    if success:
                        opened_count += 1
                    else:
                        # Show detailed error in error panel instead of just status bar
                        self.show_error_panel_with_message(
                            "PDF Viewer Error",
                            f"Failed to open PDF for: {paper.title}",
                            error_msg,
                        )
                        break  # Show only first error
                else:
                    self.status_bar.set_warning(f"No PDF available for: {paper.title}")
                    break

            if opened_count > 0:
                self.status_bar.set_success(f"Opened {opened_count} PDF(s)")
            elif (
                opened_count == 0
                and len(papers_to_open) == 1
                and not papers_to_open[0].pdf_path
            ):
                # This case is already handled above, so this is for clarity
                pass
            else:
                self.status_bar.set_error(
                    "No PDFs found to open for the selected paper(s)"
                )

        except Exception as e:
            self.status_bar.set_error(f"Error opening PDFs: {e}")

    def handle_exit_command(self):
        """Handle /exit command - exit the application."""
        self.app.exit()

    def handle_sort_command(self, args: List[str]):
        """Handle /sort command - sort papers by field."""
        if not args:
            self.status_bar.set_status(
                "⚠ Usage: /sort <field> [asc|desc]. Fields: title, authors, venue, year"
            )
            return

        field = args[0].lower()
        order = args[1].lower() if len(args) > 1 else "asc"

        valid_fields = ["title", "authors", "venue", "year"]
        valid_orders = ["asc", "desc", "ascending", "descending"]

        if field not in valid_fields:
            self.status_bar.set_status(
                f"⚠ Invalid field '{field}'. Valid fields: {', '.join(valid_fields)}"
            )
            return

        if order not in valid_orders:
            self.status_bar.set_status(
                f"⚠ Invalid order '{order}'. Valid orders: asc, desc"
            )
            return

        try:
            # Preserve selection state
            old_selected_paper_ids = self.paper_list_control.selected_paper_ids.copy()
            old_in_select_mode = self.paper_list_control.in_select_mode

            # Sort papers
            reverse = order.startswith("desc")

            if field == "title":
                self.current_papers.sort(key=lambda p: p.title.lower(), reverse=reverse)
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

            # Update paper list control
            self.paper_list_control = PaperListControl(self.current_papers)
            self.paper_list_control.selected_paper_ids = old_selected_paper_ids
            self.paper_list_control.in_select_mode = old_in_select_mode

            order_text = "descending" if reverse else "ascending"
            self.status_bar.set_success(f"Sorted by {field} ({order_text})")

        except Exception as e:
            self.status_bar.set_error(f"Error sorting papers: {e}")

    def handle_detail_command(self):
        """Handle /detail command."""
        papers_to_show = self._get_target_papers()
        if not papers_to_show:
            return

        try:
            details_text = self._format_paper_details(papers_to_show)

            # Update buffer content correctly by bypassing the read-only flag
            doc = Document(details_text, 0)
            self.details_buffer.set_document(doc, bypass_readonly=True)

            self.show_details_panel = True
            self.app.layout.focus(self.details_control)
            self.status_bar.set_status("Details panel opened - Press ESC to close")
        except Exception as e:
            import traceback

            self.show_error_panel_with_message(
                "Detail View Error",
                "Could not display paper details.",
                traceback.format_exc(),
            )

    def _format_paper_details(self, papers: List[Paper]) -> str:
        """Format metadata for one or more papers into a string."""
        if not papers:
            return "No papers to display."

        if len(papers) == 1:
            paper = papers[0]
            authors = ", ".join([a.full_name for a in paper.get_ordered_authors()])
            collections = ", ".join([c.name for c in paper.collections])
            # Format timestamps
            added_date_str = (
                paper.added_date.strftime("%Y-%m-%d %H:%M:%S")
                if paper.added_date
                else "N/A"
            )
            modified_date_str = (
                paper.modified_date.strftime("%Y-%m-%d %H:%M:%S")
                if paper.modified_date
                else "N/A"
            )

            # Choose appropriate label for venue field
            venue_label = "Website:" if paper.paper_type == "preprint" else "Venue:"

            lines = []
            lines.append(f"Title:        {paper.title}")
            lines.append(f"Authors:      {authors}")
            if paper.year:
                lines.append(f"Year:         {paper.year}")
            lines.append(f"{venue_label:<13} {paper.venue_display}")
            if paper.paper_type:
                lines.append(f"Type:         {paper.paper_type}")
            if collections:
                lines.append(f"Collections:  {collections}")
            if paper.doi:
                lines.append(f"DOI:          {paper.doi}")
            if paper.preprint_id:
                lines.append(f"Preprint ID:  {paper.preprint_id}")
            if paper.category:
                lines.append(f"Category:     {paper.category}")
            if paper.volume:
                lines.append(f"Volume:       {paper.volume}")
            if paper.issue:
                lines.append(f"Issue:        {paper.issue}")
            if paper.pages:
                lines.append(f"Pages:        {paper.pages}")
            if paper.url:
                lines.append(f"URL:          {paper.url}")
            if paper.pdf_path:
                lines.append(f"PDF Path:     {paper.pdf_path}")
            lines.append(f"Added:        {added_date_str}")
            lines.append(f"Modified:     {modified_date_str}")
            lines.append("")
            lines.append("Abstract:")
            lines.append("---------")
            lines.append(paper.abstract or "No abstract available.")
            lines.append("")
            lines.append("Notes:")
            lines.append("------")
            lines.append(paper.notes or "No notes available.")
            lines.append("\n")

            return "\n".join(lines)

        # Multiple papers
        output = [f"Displaying common metadata for {len(papers)} selected papers.\n"]

        fields_to_compare = ["year", "paper_type", "venue_full"]
        first_paper = papers[0]

        for field in fields_to_compare:
            value = getattr(first_paper, field)
            is_common = all(getattr(p, field) == value for p in papers[1:])
            display_value = value if is_common else "<Multiple Values>"
            output.append(
                f"{field.replace('_', ' ').title() + ':':<12} {display_value or 'N/A'}"
            )

        # Special handling for collections (many-to-many)
        first_collections = set(c.name for c in first_paper.collections)
        is_common_collections = all(
            set(c.name for c in p.collections) == first_collections for p in papers[1:]
        )
        collections_display = (
            ", ".join(sorted(list(first_collections)))
            if is_common_collections
            else "<Multiple Values>"
        )
        output.append(f"{'Collections:':<12} {collections_display or 'N/A'}")

        return "\n".join(output)

    def show_error_panel_with_message(
        self, title: str, message: str, details: str = ""
    ):
        """Show error panel with a specific error message."""
        self._add_log(f"error: {title}", f"{message} - {details}")
        self.error_panel.add_error(title, message, details)
        doc = Document(self.error_panel.get_formatted_text_for_buffer(), 0)
        self.error_buffer.set_document(doc, bypass_readonly=True)
        self.show_error_panel = True
        self.app.layout.focus(self.error_control)
        self.status_bar.set_status(f"{title} - Press ESC to close details")

    def show_help_dialog(self, content: str = None, title: str = "PaperCLI Help"):
        """Show help dialog with optional custom content and title."""
        if content is not None:
            doc = Document(content, 0)
            self.help_buffer.set_document(doc, bypass_readonly=True)

        # Update dialog title
        self.help_dialog.title = title

        self.show_help = True
        self.app.layout.focus(self.help_control)
        self.status_bar.set_status("📖 Help panel opened - Press ESC to close")

    def run(self):
        """Run the application."""
        # Check for updates on startup (non-blocking)
        try:
            version_manager = VersionManager()
            # Perform silent check in background without blocking startup
            import threading
            def check_updates():
                try:
                    update_available, latest_version = version_manager.check_for_updates_silently()
                    if update_available:
                        # Log to activity log instead of interfering with UI
                        self._add_log("version_check", f"Update available: v{latest_version}")
                except Exception:
                    pass  # Silently ignore update check failures
            
            update_thread = threading.Thread(target=check_updates, daemon=True)
            update_thread.start()
        except Exception:
            pass  # Silently ignore any version checking issues
        
        self.app.run()

    def handle_add_to_command(self, args: List[str]):
        """Handle /add-to command."""
        if not args:
            self.status_bar.set_error("Usage: /add-to <collection_name>")
            return

        collection_name = " ".join(args)
        papers_to_add = self._get_target_papers()

        if not papers_to_add:
            return

        paper_ids = [p.id for p in papers_to_add]
        paper_titles = [p.title for p in papers_to_add]
        added_count = self.collection_service.add_papers_to_collection(
            paper_ids, collection_name
        )

        if added_count > 0:
            self._add_log(
                "add_to_collection",
                f"Added {added_count} paper(s) to '{collection_name}': {', '.join(paper_titles)}",
            )
            self.status_bar.set_success(
                f"Added {added_count} paper(s) to collection '{collection_name}'."
            )
            self.load_papers()
        else:
            self.status_bar.set_status(
                "No papers were added to the collection (they may have already been in it)."
            )

    def handle_remove_from_command(self, args: List[str]):
        """Handle /remove-from command."""
        if not args:
            self.status_bar.set_error("Usage: /remove-from <collection_name>")
            return

        collection_name = " ".join(args)
        papers_to_remove = self._get_target_papers()

        if not papers_to_remove:
            return

        paper_ids = [p.id for p in papers_to_remove]
        paper_titles = [p.title for p in papers_to_remove]
        removed_count, errors = self.collection_service.remove_papers_from_collection(
            paper_ids, collection_name
        )

        if errors:
            # Show only the first error in the status bar for clarity
            self.show_error_panel_with_message(
                "Remove from Collection Error",
                f"Encountered {len(errors)} error(s).",
                "\n".join(errors),
            )

        if removed_count > 0:
            self._add_log(
                "remove_from_collection",
                f"Removed {removed_count} paper(s) from '{collection_name}': {', '.join(paper_titles)}",
            )
            self.status_bar.set_success(
                f"Removed {removed_count} paper(s) from collection '{collection_name}'."
            )
            self.load_papers()
        elif not errors:
            self.status_bar.set_status("No papers were removed from the collection.")

    def handle_collect_command(self):
        """Handle /collect command by showing the collection management dialog."""
        self.show_collect_dialog()

    def show_collect_dialog(self):
        """Show the collection management dialog."""
        import logging

        debug_logger = logging.getLogger("papercli")

        def callback(result):
            """Callback executed when the dialog is closed."""
            if self.collect_float in self.app.layout.container.floats:
                self.app.layout.container.floats.remove(self.collect_float)

            self.collect_dialog = None
            self.collect_float = None
            self.app.layout.focus(self.input_buffer)

            # Restore original key bindings
            if hasattr(self, "original_key_bindings"):
                self.app.key_bindings = self.original_key_bindings
                del self.original_key_bindings

            if result and result.get("action") == "save":
                self.load_papers()  # Reload papers to reflect changes
                self.status_bar.set_success("Collections updated successfully.")
            else:
                self.status_bar.set_status("Collection management cancelled.")

            self.app.invalidate()

        try:
            # Store original key bindings
            self.original_key_bindings = self.app.key_bindings

            debug_logger.debug("Fetching all collections and papers for CollectDialog")
            all_collections = self.collection_service.get_all_collections()
            all_papers = self.paper_service.get_all_papers()
            debug_logger.debug(
                f"Found {len(all_collections)} collections and {len(all_papers)} papers."
            )

            debug_logger.debug("Creating CollectDialog")
            self.collect_dialog = CollectDialog(
                self.collection_service.get_all_collections(),
                self.paper_service.get_all_papers(),
                callback,
                self.collection_service,
                self.paper_service,
                self.status_bar,
                self._add_log,
                self.show_error_panel_with_message,
            )
            debug_logger.debug("CollectDialog created successfully")

            self.collect_float = Float(self.collect_dialog)
            self.app.layout.container.floats.append(self.collect_float)

            initial_focus_target = self.collect_dialog.get_initial_focus()
            debug_logger.debug(
                f"Initial focus target from dialog: {initial_focus_target}"
            )

            if initial_focus_target:
                self.app.layout.focus(initial_focus_target)
                debug_logger.debug("Focus set on initial_focus_target")
            else:
                self.app.layout.focus(self.collect_dialog)
                debug_logger.debug("Focus set on collect_dialog as fallback")

            # Set application key bindings to dialog's key bindings
            self.app.key_bindings = self.collect_dialog.dialog.container.key_bindings

            self.app.invalidate()
            debug_logger.debug("Application layout invalidated")

        except Exception as e:
            debug_logger.error(
                f"Error creating or showing CollectDialog: {e}", exc_info=True
            )
            self.show_error_panel_with_message(
                "Collection Dialog Error",
                "Could not open the collection management dialog.",
                traceback.format_exc(),
            )

    def handle_version_command(self, args: List[str]):
        """Handle /version command for version management."""
        version_manager = VersionManager()
        
        if not args:
            # Show basic version info
            current_version = version_manager.get_current_version()
            install_method = version_manager.get_installation_method()
            
            version_info = f"PaperCLI v{current_version}\n"
            version_info += f"Installation: {install_method}\n"
            
            # Check for updates in background
            try:
                update_available, latest_version = version_manager.is_update_available()
                if update_available:
                    version_info += f"Update available: v{latest_version}\n"
                    version_info += f"Run '/version update' to upgrade"
                else:
                    version_info += "You're running the latest version"
            except Exception:
                version_info += "Could not check for updates"
            
            self.show_help_dialog(version_info, "Version Information")
            return
        
        action = args[0].lower()
        
        if action == "check":
            self.status_bar.set_status("Checking for updates...")
            try:
                update_available, latest_version = version_manager.is_update_available()
                current_version = version_manager.get_current_version()
                
                if update_available:
                    update_info = f"Update Available!\n\n"
                    update_info += f"Current version: v{current_version}\n"
                    update_info += f"Latest version:  v{latest_version}\n\n"
                    
                    if version_manager.can_auto_update():
                        update_info += "To update, run: /version update\n\n"
                    else:
                        update_info += f"To update manually, run:\n"
                        update_info += f"{version_manager.get_update_instructions()}\n\n"
                    
                    # Get release notes from GitHub
                    try:
                        import requests
                        url = f"https://api.github.com/repos/{version_manager.github_repo}/releases/latest"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            release_data = response.json()
                            if release_data.get("body"):
                                update_info += f"Release Notes:\n{release_data['body']}"
                    except Exception:
                        pass
                    
                    self.show_help_dialog(update_info, "Update Available")
                else:
                    self.status_bar.set_success(f"You're running the latest version (v{current_version})")
            except Exception as e:
                self.status_bar.set_error(f"Could not check for updates: {e}")
        
        elif action == "update":
            if not version_manager.can_auto_update():
                install_method = version_manager.get_installation_method()
                self.status_bar.set_error(f"Auto-update not supported for {install_method} installations")
                
                manual_info = f"Manual Update Required\n\n"
                manual_info += f"Installation method: {install_method}\n\n"
                manual_info += f"To update manually, run:\n"
                manual_info += f"{version_manager.get_update_instructions()}"
                
                self.show_help_dialog(manual_info, "Manual Update Required")
                return
            
            # Check if update is available first
            try:
                update_available, latest_version = version_manager.is_update_available()
                if not update_available:
                    current_version = version_manager.get_current_version()
                    self.status_bar.set_success(f"Already running latest version (v{current_version})")
                    return
                
                self.status_bar.set_status(f"Updating to v{latest_version}...")
                
                # Perform the update
                if version_manager.perform_update():
                    self.status_bar.set_success("Update successful! Please restart PaperCLI.")
                    # Show restart dialog
                    restart_info = f"Update Successful!\n\n"
                    restart_info += f"PaperCLI has been updated to v{latest_version}.\n\n"
                    restart_info += f"Please restart the application to use the new version.\n\n"
                    restart_info += f"Press ESC to close this dialog and exit."
                    
                    self.show_help_dialog(restart_info, "Restart Required")
                else:
                    self.status_bar.set_error("Update failed. Please update manually.")
                    
            except Exception as e:
                self.status_bar.set_error(f"Update failed: {e}")
        
        elif action == "info":
            version_manager = VersionManager()
            current_version = version_manager.get_current_version()
            install_method = version_manager.get_installation_method()
            config = version_manager.get_update_config()
            
            info = f"PaperCLI Version Information\n"
            info += f"=" * 30 + "\n\n"
            info += f"Version: v{current_version}\n"
            info += f"Installation: {install_method}\n"
            info += f"GitHub Repository: {version_manager.github_repo}\n\n"
            
            info += f"Update Settings:\n"
            info += f"- Auto-check: {'Yes' if config.get('auto_check', True) else 'No'}\n"
            info += f"- Check interval: {config.get('check_interval_days', 7)} days\n"
            info += f"- Auto-update: {'Yes' if config.get('auto_update', False) else 'No'}\n"
            info += f"- Can auto-update: {'Yes' if version_manager.can_auto_update() else 'No'}\n"
            
            if config.get('last_check'):
                info += f"- Last check: {config['last_check'][:19]}\n"
            else:
                info += f"- Last check: Never\n"
            
            info += f"\nTo check for updates: /version check\n"
            if version_manager.can_auto_update():
                info += f"To update: /version update\n"
            else:
                info += f"To update manually:\n{version_manager.get_update_instructions()}\n"
            
            self.show_help_dialog(info, "Version Information")
        
        else:
            self.status_bar.set_error(f"Unknown version command: {action}")
            self.status_bar.set_status("Usage: /version [check|update|info]")
