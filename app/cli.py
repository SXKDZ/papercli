
"""
Main CLI application for PaperCLI.
"""

import asyncio
import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.containers import ConditionalContainer, ScrollOffsets, Float, FloatContainer
from prompt_toolkit.layout.controls import FormattedTextControl, BufferControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.widgets import Frame, TextArea, Label, Dialog
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import message_dialog, input_dialog, button_dialog
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding.bindings import scroll
from prompt_toolkit.completion import WordCompleter, Completer, Completion

from .database import get_db_session
from .models import Paper, Author, Collection
from .ui_components import PaperListControl, StatusBar, CommandValidator, ErrorPanel
from .services import (PaperService, SearchService, AuthorService, CollectionService, 
                      MetadataExtractor, ExportService, ChatService, SystemService)
from .simple_dialogs import SimplePaperDialog, SimpleSearchDialog, SimpleFilterDialog
from .update_dialog import UpdateDialog, SimpleUpdateDialog
from .export_dialog import ExportDialog, SimpleExportDialog


class SmartCompleter(Completer):
    """Smart command completer with subcommand and description support."""
    
    def __init__(self):
        self.commands = {
            '/add': ('Add a new paper (from PDF, arXiv, DBLP, etc.)', ['pdf', 'arxiv', 'dblp', 'manual', 'sample']),
            '/search': ('Search papers by keyword (title, author, etc.)', []),
            '/filter': ('Filter papers by specific criteria', ['year', 'author', 'venue', 'type']),
            '/sort': ('Sort the paper list by a field', ['title', 'authors', 'venue', 'year']),
            '/select': ('Enter multi-selection mode', []),
            '/clear': ('Clear all selected papers', []),
            '/chat': ('Chat with an LLM about the selected paper(s)', []),
            '/edit': ('Edit metadata of the selected paper(s)', ['title', 'authors', 'venue', 'year', 'abstract', 'notes']),
            '/export': ('Export selected paper(s) to a file or clipboard', ['bibtex', 'markdown', 'html', 'json']),
            '/delete': ('Delete the selected paper(s)', []),
            '/show': ('Open the PDF for the selected paper(s)', []),
            '/detail': ('Show detailed metadata for the selected paper(s)', []),
            '/help': ('Show the help panel', []),
            '/exit': ('Exit the application', []),
        }

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        
        # Completion for main commands
        if not words or (len(words) == 1 and not text.endswith(' ')):
            partial_cmd = words[0] if words else ''
            for cmd, (description, _) in self.commands.items():
                if cmd.startswith(partial_cmd):
                    yield Completion(
                        cmd, 
                        start_position=-len(partial_cmd),
                        display_meta=description
                    )
        
        # Completion for subcommands
        elif len(words) >= 1 and text.endswith(' '):
            cmd = words[0]
            if cmd in self.commands:
                _, subcommands = self.commands[cmd]
                if subcommands:
                    for subcmd in subcommands:
                        yield Completion(
                            subcmd, 
                            start_position=0,
                            display_meta=f"Option for {cmd}"
                        )

        # Completion for partial subcommands
        elif len(words) == 2 and not text.endswith(' '):
            cmd = words[0]
            if cmd in self.commands:
                _, subcommands = self.commands[cmd]
                partial_subcmd = words[1]
                for subcmd in subcommands:
                    if subcmd.startswith(partial_subcmd):
                        yield Completion(
                            subcmd, 
                            start_position=-len(partial_subcmd),
                            display_meta=f"Option for {cmd}"
                        )


class PaperCLI:
    """Main CLI application class."""
    
    HELP_TEXT = """
PaperCLI Help
=============

Core Commands:
--------------
/add      Add a new paper (from PDF, arXiv, DBLP, etc.)
/search   Search papers by keyword (or just type to search)
/filter   Filter papers by specific criteria (e.g., year, author)
/sort     Sort the paper list by a field (e.g., title, year)
/select   Enter multi-selection mode to act on multiple papers
/clear    Clear all selected papers
/help     Show this help panel (or press F1)
/exit     Exit the application (or press Ctrl+C)

Paper Operations (work on the paper under the cursor ► or selected papers ✓):
-----------------------------------------------------------------------------
/chat     Chat with an LLM about the paper(s)
/edit     Edit metadata of the paper(s)
/show     Open the PDF for the paper(s)
/detail   Show detailed metadata for the paper(s)
/export   Export paper(s) to a file or clipboard (BibTeX, Markdown, etc.)
/delete   Delete the paper(s) from the library

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
        from .database import init_database
        init_database(db_path)
        
        # Initialize services
        self.paper_service = PaperService()
        self.search_service = SearchService()
        self.author_service = AuthorService()
        self.collection_service = CollectionService()
        self.metadata_extractor = MetadataExtractor()
        self.export_service = ExportService()
        self.chat_service = ChatService()
        self.system_service = SystemService()
        
        # UI state
        self.current_papers: List[Paper] = []
        self.paper_list_control = PaperListControl([])
        self.status_bar = StatusBar()
        self.error_panel = ErrorPanel()
        self.in_select_mode = False
        self.show_help = False
        self.show_error_panel = False
        self.show_details_panel = False
        
        
        # Load initial papers
        self.load_papers()
        
        # Setup UI
        self.setup_layout()
        self.setup_key_bindings()
        self.setup_application()
    
    
    
    def load_papers(self):
        """Load papers from database."""
        try:
            # Preserve selection state using paper IDs
            old_selected_index = getattr(self.paper_list_control, 'selected_index', 0)
            old_selected_paper_ids = getattr(self.paper_list_control, 'selected_paper_ids', set()).copy()
            old_in_select_mode = getattr(self.paper_list_control, 'in_select_mode', False)
            
            self.current_papers = self.paper_service.get_all_papers()
            self.paper_list_control = PaperListControl(self.current_papers)
            
            # Restore selection state
            self.paper_list_control.selected_index = min(old_selected_index, len(self.current_papers) - 1) if self.current_papers else 0
            self.paper_list_control.selected_paper_ids = old_selected_paper_ids
            self.paper_list_control.in_select_mode = old_in_select_mode
            
            self.status_bar.set_status(f"📚 Loaded {len(self.current_papers)} papers")
        except Exception as e:
            self.status_bar.set_status(f"❌ Error loading papers: {e}")
            self.current_papers = []
            self.paper_list_control = PaperListControl(self.current_papers)
    
    def setup_key_bindings(self):
        """Setup key bindings."""
        self.kb = KeyBindings()
        
        # Navigation
        @self.kb.add('up', filter=~has_focus(self.help_control) & ~has_focus(self.details_control))
        def move_up(event):
            # If completion menu is open, navigate it
            if self.input_buffer.complete_state:
                self.input_buffer.complete_previous()
            else:
                # Otherwise, navigate the paper list
                self.paper_list_control.move_up()
                event.app.invalidate()

        @self.kb.add('down', filter=~has_focus(self.help_control) & ~has_focus(self.details_control))
        def move_down(event):
            # If completion menu is open, navigate it
            if self.input_buffer.complete_state:
                self.input_buffer.complete_next()
            else:
                # Otherwise, navigate the paper list
                self.paper_list_control.move_down()
                event.app.invalidate()
        
        # Selection (in select mode) - smart space key handling
        @self.kb.add('space')
        def toggle_selection(event):
            # Check if user is actively typing a command
            current_text = self.input_buffer.text
            cursor_pos = self.input_buffer.cursor_position
            
            # If user is typing (has text or cursor not at start), allow normal space
            if len(current_text) > 0 or cursor_pos > 0:
                self.input_buffer.insert_text(' ')
            elif self.in_select_mode:
                # Only toggle selection if input is truly empty and we're in select mode
                self.paper_list_control.toggle_selection()
                selected_count = len(self.paper_list_control.selected_paper_ids)
                self.status_bar.set_status(f"✓ Toggled selection. Selected: {selected_count} papers")
                event.app.invalidate()  # Force refresh of UI
            else:
                # Default behavior - add space
                self.input_buffer.insert_text(' ')
        
        # Command input
        @self.kb.add('enter')
        def handle_enter(event):
            # If completion menu is open, accept current completion
            if self.input_buffer.complete_state:
                self.input_buffer.apply_completion(self.input_buffer.complete_state.current_completion)
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
                    self.status_bar.set_status(f"← Exited selection mode ({selected_count} papers remain selected)")
                else:
                    self.status_bar.set_status("← Exited selection mode")
                event.app.invalidate()
        
        # Help
        @self.kb.add('f1')
        def show_help(event):
            self.show_help_dialog()
        
        # Exit selection mode
        @self.kb.add('escape')
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
            elif self.in_select_mode:
                self.in_select_mode = False
                self.paper_list_control.in_select_mode = False
                selected_count = len(self.paper_list_control.selected_paper_ids)
                if selected_count > 0:
                    self.status_bar.set_status(f"← Exited selection mode ({selected_count} papers remain selected)")
                else:
                    self.status_bar.set_status("← Exited selection mode")
                event.app.invalidate()
                return
            else:
                self.input_buffer.text = ""
                self.status_bar.set_status("🧹 Input cleared")
        
        # Auto-completion - Tab key
        @self.kb.add('tab')
        def complete(event):
            # Always ensure we're focused on the input buffer first
            if event.app.current_buffer != self.input_buffer:
                event.app.layout.focus(self.input_buffer)
                return
            
            # Trigger completion
            buffer = self.input_buffer
            if buffer.complete_state:
                buffer.complete_next()
            else:
                buffer.start_completion(select_first=True)
        
        # Shift+Tab for previous completion
        @self.kb.add('s-tab')
        def complete_previous(event):
            if event.app.current_buffer == self.input_buffer:
                buffer = self.input_buffer
                if buffer.complete_state:
                    buffer.complete_previous()
        
        # Handle backspace
        @self.kb.add('backspace')
        def handle_backspace(event):
            if event.app.current_buffer == self.input_buffer:
                self.input_buffer.delete_before_cursor()
        
        # Handle delete key
        @self.kb.add('delete')
        def handle_delete(event):
            if event.app.current_buffer == self.input_buffer:
                self.input_buffer.delete()
        
        # Handle normal character input
        @self.kb.add('<any>')
        def handle_any_key(event):
            # Make sure we're focused on the input buffer for text input
            if event.app.current_buffer != self.input_buffer:
                event.app.layout.focus(self.input_buffer)
            
            # Let the buffer handle the key if it's a printable character (except space which has its own handler)
            if hasattr(event, 'data') and event.data and len(event.data) == 1:
                char = event.data
                if char.isprintable() and char != ' ':
                    self.input_buffer.insert_text(char)
        
        # Exit application
        @self.kb.add('c-c')
        def exit_app(event):
            event.app.exit()
    
    def setup_layout(self):
        """Setup application layout."""
        # Smart command completer with subcommand support
        smart_completer = SmartCompleter()
        commands = list(smart_completer.commands.keys())
        
        # Input buffer with completion enabled  
        self.input_buffer = Buffer(
            completer=smart_completer,
            complete_while_typing=True,
            accept_handler=lambda buffer: None,
            enable_history_search=True
        )
        
        # Paper list window
        self.paper_list_window = Window(
            content=FormattedTextControl(
                text=lambda: self.paper_list_control.get_formatted_text()
            ),
            scroll_offsets=ScrollOffsets(top=1, bottom=1),
            wrap_lines=False
        )
        
        # Input window with prompt
        from prompt_toolkit.layout.processors import BeforeInput
        
        input_window = Window(
            content=BufferControl(
                buffer=self.input_buffer,
                include_default_input_processors=True,
                input_processors=[
                    BeforeInput("> ", style="class:prompt")
                ]
            ),
            height=1
        )
        
        # Status window
        status_window = Window(
            content=FormattedTextControl(
                text=lambda: self.status_bar.get_formatted_text()
            ),
            height=1,
            align=WindowAlign.LEFT
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
            key_bindings=self._get_help_key_bindings(), # Reuse the same scroll bindings
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
        error_panel = ConditionalContainer(
            content=Frame(
                Window(
                    content=FormattedTextControl(
                        text=lambda: self.error_panel.get_formatted_text()
                    ),
                    wrap_lines=True
                ),
                title="Error Details"
            ),
            filter=Condition(lambda: self.show_error_panel)
        )
        
        # Main layout with floating completion menu
        main_container = HSplit([
            # Header
            Window(
                content=FormattedTextControl(
                    text=lambda: self.get_header_text()
                ),
                height=1
            ),
            # Paper list
            Frame(
                body=self.paper_list_window
            ),
            # Input
            Frame(
                body=input_window
            ),
            # Status
            status_window,
            # Error panel overlay
            error_panel
        ])
        
        # Wrap in FloatContainer to support completion menu and help dialog
        self.layout = Layout(
            FloatContainer(
                content=main_container,
                floats=[
                    Float(
                        content=CompletionsMenu(max_height=16, scroll_offset=1),
                        bottom=3,  # Position above status bar
                        left=2,
                        transparent=True
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
                ]
            )
        )

    def _get_help_key_bindings(self):
        """Key bindings for the help dialog for intuitive scrolling."""
        kb = KeyBindings()

        @kb.add('up')
        def _(event):
            scroll.scroll_one_line_up(event)

        @kb.add('down')
        def _(event):
            scroll.scroll_one_line_down(event)

        @kb.add('pageup')
        def _(event):
            scroll.scroll_page_up(event)

        @kb.add('pagedown')
        def _(event):
            scroll.scroll_page_down(event)

        @kb.add('<any>')
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

        mode = "SELECT" if self.in_select_mode else "LIST"
        selected_count = len(self.paper_list_control.selected_paper_ids)
        
        # Left side of the header
        left_parts = []
        if self.in_select_mode:
            left_parts.append(("class:mode_select", f" {mode} "))
        else:
            left_parts.append(("class:mode_list", f" {mode} "))
        
        left_parts.append(("class:header_content", " Total: "))
        left_parts.append(("class:total", str(len(self.current_papers))))
        
        left_parts.append(("class:header_content", "  Current: "))
        left_parts.append(("class:current", str(self.paper_list_control.selected_index + 1)))
        
        left_parts.append(("class:header_content", "  Selected: "))
        left_parts.append(("class:selected_count", str(selected_count)))

        # Right side of the header
        help_text = "Space: Select  ESC: Exit  ↑↓: Nav  F1: Help "
        right_parts = [("class:header_content", help_text)]

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
            truncated_text = full_text[:width - 3] + "..."
            return FormattedText([("class:header_content", truncated_text)])

        return FormattedText(final_parts)
    
    def setup_application(self):
        """Setup the main application."""
        # Define styles
        style = Style([
            # Header styles - clean and bold with color coding
            ("header_border", "#888888"),
            ("header_content", "bold #ffffff bg:#2d2d2d"),
            ("mode_select", "bold #ff0000 bg:#2d2d2d"),  # Red for SELECT
            ("mode_list", "bold #0066ff bg:#2d2d2d"),    # Blue for LIST
            ("total", "bold #00aa00 bg:#2d2d2d"),        # Green for Total
            ("current", "bold #ffaa00 bg:#2d2d2d"),      # Orange for Current
            ("selected_count", "bold #ff00aa bg:#2d2d2d"), # Pink for Selected
            # Table styles
            ("table_border", "#888888"),
            ("table_header", "bold #ffffff"),
            # Input styles
            ("prompt", "bold #00aa00"),  # Green prompt symbol
            ("input", "#ffffff bg:#1a1a1a"),  # Input text with dark background
            ("selected", "bold #ffffff bg:#007acc"),  # Current paper
            ("highlighted", "bold #ffffff bg:#00aa00"),  # Selected papers (green)
            ("selected_highlighted", "bold #ffffff bg:#ff8800"),  # Both current and selected (orange)
            ("paper", "#ffffff"),
            ("empty", "#888888 italic"),
            ("help", "#00aa00"),
            ("status", "#ffffff bg:#444444"),  # Darker background for status bar
            ("progress", "#ffff00 bg:#444444"),
            ("error", "#ff0000"),
            ("success", "#00ff00"),
            # Error panel styles
            ("error_header", "bold #ffffff bg:#cc0000"),
            ("error_title", "bold #ff6666"),
            ("error_message", "#ffcccc"),
            ("error_details", "#ffaaaa italic"),
            ("error_time", "#888888"),
            ("error_help", "#00aa00"),
            # Help panel styles
            ("help_header", "bold #ffffff bg:#4a90e2"),
            ("help_footer", "bold #ffff00"),
        ])
        
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
            editing_mode='emacs',
            include_default_pygments_style=False
        )
        
        # Set initial focus to input buffer
        self.app.layout.focus(self.input_buffer)
    
    def handle_command(self, command: str):
        """Handle user commands."""
        try:
            parts = command.split()
            cmd = parts[0].lower()
            
            if cmd == '/add':
                self.handle_add_command(parts[1:])
            elif cmd == '/search':
                self.handle_search_command(parts[1:])
            elif cmd == '/filter':
                self.handle_filter_command(parts[1:])
            elif cmd == '/select':
                self.handle_select_command()
            elif cmd == '/help':
                self.show_help_dialog()
            elif cmd == '/chat':
                self.handle_chat_command()
            elif cmd == '/edit':
                self.handle_edit_command(parts[1:])
            elif cmd == '/export':
                self.handle_export_command(parts[1:])
            elif cmd == '/delete':
                self.handle_delete_command()
            elif cmd == '/show':
                self.handle_show_command()
            elif cmd == '/detail':
                self.handle_detail_command()
            elif cmd == '/clear':
                self.handle_clear_command()
            elif cmd == '/exit':
                self.handle_exit_command()
            elif cmd == '/sort':
                self.handle_sort_command(parts[1:])
            else:
                # If not a known command, assume it's a search query
                self.handle_search_command(parts)
        
        except Exception as e:
            # Show detailed error in error panel instead of just status bar
            self.show_error_panel_with_message(
                "Command Error",
                f"Failed to execute command: {command}",
                str(e)
            )

    def handle_clear_command(self):
        """Handle /clear command - deselect all papers."""
        if not self.paper_list_control.selected_paper_ids:
            self.status_bar.set_status("No papers were selected.")
            return
            
        count = len(self.paper_list_control.selected_paper_ids)
        self.paper_list_control.selected_paper_ids.clear()
        self.status_bar.set_status(f"✓ Cleared {count} selected paper(s).")
    
    def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        try:
            # Simple command-line based add
            if len(args) > 0:
                # Quick add from command line arguments
                if args[0] == "arxiv" and len(args) > 1:
                    self._quick_add_arxiv(args[1])
                elif args[0] == "dblp" and len(args) > 1:
                    self._quick_add_dblp(" ".join(args[1:]))  # Support URLs with parameters
                elif args[0] == "manual":
                    self._add_manual_paper()
                elif args[0] == "sample":
                    self._add_sample_paper()
                else:
                    self.status_bar.set_status("📝 Usage: /add [arxiv <id>|dblp <url>|manual|sample]")
            else:
                self.status_bar.set_status("📝 Usage: /add [arxiv <id>|dblp <url>|manual|sample]")
        
        except Exception as e:
            self.status_bar.set_status(f"❌ Error adding paper: {e}")
    
    def _quick_add_arxiv(self, arxiv_id: str):
        """Quickly add a paper from arXiv."""
        try:
            self.status_bar.set_status(f"📡 Fetching arXiv paper {arxiv_id}...")
            
            # Extract metadata from arXiv
            metadata = self.metadata_extractor.extract_from_arxiv(arxiv_id)
            
            # Download PDF
            pdf_dir = os.path.join(os.path.expanduser("~"), ".papercli", "pdfs")
            pdf_path = self.system_service.download_arxiv_pdf(arxiv_id, pdf_dir)
            
            # Prepare paper data
            paper_data = {
                'title': metadata['title'],
                'abstract': metadata.get('abstract', ''),
                'year': metadata.get('year'),
                'venue_full': metadata.get('venue_full', ''),
                'venue_acronym': metadata.get('venue_acronym', ''),
                'paper_type': metadata.get('paper_type', 'preprint'),
                'arxiv_id': metadata.get('arxiv_id'),
                'doi': metadata.get('doi'),
                'pdf_path': pdf_path
            }
            
            # Add to database
            authors = metadata.get('authors', [])
            collections = ['arXiv Papers']  # Default collection
            
            paper = self.paper_service.add_paper_from_metadata(paper_data, authors, collections)
            
            # Refresh display
            self.load_papers()
            
            self.status_bar.set_status(f"📄 ✓ Added: {paper.title[:50]}...")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error adding arXiv paper: {e}")
    
    def _add_sample_paper(self):
        """Add a sample paper for demonstration."""
        try:
            paper_data = {
                'title': 'Sample Paper: Introduction to Machine Learning',
                'abstract': 'This is a sample paper demonstrating the PaperCLI system functionality.',
                'year': 2024,
                'venue_full': 'Journal of Sample Papers',
                'venue_acronym': 'JSP',
                'paper_type': 'journal',
                'notes': 'Sample paper added for demonstration'
            }
            
            authors = ['Sample Author', 'Demo User']
            collections = ['Sample Collection']
            
            paper = self.paper_service.add_paper_from_metadata(paper_data, authors, collections)
            
            # Refresh display
            self.load_papers()
            
            self.status_bar.set_status(f"📄 ✓ Added sample paper: {paper.title}")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error adding sample paper: {e}")
    
    def _quick_add_dblp(self, dblp_url: str):
        """Quickly add a paper from DBLP URL."""
        try:
            self.status_bar.set_status(f"🌐 Fetching DBLP paper from {dblp_url[:50]}...")
            
            # Extract metadata from DBLP
            metadata = self.metadata_extractor.extract_from_dblp(dblp_url)
            
            # Prepare paper data
            paper_data = {
                'title': metadata.get('title', 'Unknown Title'),
                'abstract': metadata.get('abstract', ''),
                'year': metadata.get('year'),
                'venue_full': metadata.get('venue_full', ''),
                'venue_acronym': metadata.get('venue_acronym', ''),
                'paper_type': metadata.get('paper_type', 'conference'),
                'doi': metadata.get('doi'),
                'dblp_url': dblp_url
            }
            
            # Add to database
            authors = metadata.get('authors', [])
            collections = ['DBLP Papers']  # Default collection
            
            paper = self.paper_service.add_paper_from_metadata(paper_data, authors, collections)
            
            # Refresh display
            self.load_papers()
            
            self.status_bar.set_status(f"✓ Added: {paper.title[:50]}...")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error adding DBLP paper: {e}")
    
    def _add_manual_paper(self):
        """Add a paper manually with user input."""
        try:
            # For now, create a basic manual paper
            # This could be enhanced with a proper input dialog
            self.status_bar.set_status(f"✏️ Manual paper entry - using defaults (enhance with dialog later)")
            
            paper_data = {
                'title': 'Manually Added Paper',
                'abstract': 'This paper was added manually via PaperCLI.',
                'year': 2024,
                'venue_full': 'User Input',
                'venue_acronym': 'UI',
                'paper_type': 'journal',
                'notes': 'Added manually - please update metadata'
            }
            
            authors = ['Manual User']
            collections = ['Manual Papers']
            
            paper = self.paper_service.add_paper_from_metadata(paper_data, authors, collections)
            
            # Refresh display
            self.load_papers()
            
            self.status_bar.set_status(f"📝 ✓ Added manual paper: {paper.title} (use /update to edit metadata)")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error adding manual paper: {e}")
    
    def handle_search_command(self, args: List[str]):
        """Handle /search command."""
        try:
            if not args:
                self.status_bar.set_status(f"📖 Usage: /search <query>")
                return
            
            query = " ".join(args)
            self.status_bar.set_status(f"🔍 Searching for '{query}'...")
            
            # Perform search
            results = self.search_service.search_papers(query, ['title', 'authors', 'venue', 'abstract'])
            
            if not results:
                # Try fuzzy search
                results = self.search_service.fuzzy_search_papers(query)
            
            # Update display
            self.current_papers = results
            self.paper_list_control = PaperListControl(self.current_papers)
            
            self.status_bar.set_status(f"🎯 Found {len(results)} papers matching '{query}'")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error searching papers: {e}")
    
    def handle_filter_command(self, args: List[str]):
        """Handle /filter command."""
        try:
            if not args:
                self.status_bar.set_status(f"📖 Usage: /filter year <year> | type <type> | author <name>")
                return
            
            # Simple filter parsing
            filters = {}
            i = 0
            while i < len(args):
                if args[i] == "year" and i + 1 < len(args):
                    try:
                        filters['year'] = int(args[i + 1])
                        i += 2
                    except ValueError:
                        i += 1
                elif args[i] == "type" and i + 1 < len(args):
                    filters['paper_type'] = args[i + 1]
                    i += 2
                elif args[i] == "author" and i + 1 < len(args):
                    filters['author'] = args[i + 1]
                    i += 2
                else:
                    i += 1
            
            if not filters:
                self.status_bar.set_status("No valid filters specified")
                return
            
            self.status_bar.set_status(f"🔽 Applying filters...")
            
            # Apply filters
            results = self.search_service.filter_papers(filters)
            
            # Update display
            self.current_papers = results
            self.paper_list_control = PaperListControl(self.current_papers)
            
            filter_desc = ", ".join([f"{k}={v}" for k, v in filters.items()])
            self.status_bar.set_status(f"🔽 Filtered {len(results)} papers by {filter_desc}")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error filtering papers: {e}")
    
    def handle_select_command(self):
        """Handle /select command."""
        self.in_select_mode = True
        self.paper_list_control.in_select_mode = True
        self.status_bar.set_status("🎯 Entered multi-selection mode. Use Space to select multiple papers, ESC to exit.")
    
    def handle_chat_command(self):
        """Handle /chat command."""
        papers_to_chat = []
        
        if self.in_select_mode:
            papers_to_chat = self.paper_list_control.get_selected_papers()
            if not papers_to_chat:
                self.status_bar.set_status(f"⚠️ No papers selected")
                return
        else:
            # Check if there are previously selected papers, otherwise use current paper under cursor
            selected_papers = self.paper_list_control.get_selected_papers()
            if selected_papers:
                papers_to_chat = selected_papers
            else:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status(f"⚠️ No paper under cursor")
                    return
                papers_to_chat = [current_paper]
        
        try:
            self.status_bar.set_status(f"💬 Opening chat interface...")
            
            # Open chat interface in browser
            result = self.chat_service.open_chat_interface(papers_to_chat)
            
            if isinstance(result, str) and result.startswith("Error"):
                self.status_bar.set_status(result)
            else:
                if self.in_select_mode:
                    mode_info = "selected"
                elif len(papers_to_chat) > 1:
                    mode_info = "previously selected"
                else:
                    mode_info = "current"
                self.status_bar.set_status(f"💬 ✓ Chat interface opened for {len(papers_to_chat)} {mode_info} paper(s)")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error opening chat: {e}")
    
    def handle_edit_command(self, args: List[str] = None):
        """Handle /edit command."""
        papers_to_update = []
        
        if self.in_select_mode:
            papers_to_update = self.paper_list_control.get_selected_papers()
            if not papers_to_update:
                self.status_bar.set_status(f"⚠️ No papers selected")
                return
        else:
            # Check if there are previously selected papers, otherwise use current paper under cursor
            selected_papers = self.paper_list_control.get_selected_papers()
            if selected_papers:
                papers_to_update = selected_papers
            else:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status(f"⚠️ No paper under cursor")
                    return
                papers_to_update = [current_paper]
        
        try:
            
            # Parse command line arguments for quick update
            if args and len(args) >= 2:
                # Quick update: /edit field value
                field = args[0].lower()
                value = " ".join(args[1:])  # Support values with spaces
                
                # Extended field list for comprehensive updating
                valid_fields = ['title', 'abstract', 'notes', 'venue_full', 'venue_acronym', 
                              'year', 'paper_type', 'doi', 'pages', 'arxiv_id', 'dblp_url']
                if field not in valid_fields:
                    self.status_bar.set_status(f"📖 Usage: /edit [title|abstract|notes|venue_full|venue_acronym|year|paper_type|doi|pages] <value>")
                    return
                
                # Convert year to int if needed
                if field == 'year':
                    try:
                        value = int(value)
                    except ValueError:
                        self.status_bar.set_status("Year must be a number")
                        return
                
                updates = {field: value}
            else:
                # Use simple dialog for update
                dialog = SimpleUpdateDialog()
                updates = dialog.show_update_dialog(papers_to_update)
                
                if not updates:
                    self.status_bar.set_status(f"❌ Update cancelled")
                    return
            
            self.status_bar.set_status(f"🔄 Updating papers...")
            
            # Update papers
            updated_count = 0
            for paper in papers_to_update:
                try:
                    self.paper_service.update_paper(paper.id, updates)
                    updated_count += 1
                except Exception as e:
                    self.status_bar.set_status(f"Error updating paper {paper.id}: {e}")
                    break  # Show only first error
            
            # Refresh paper list
            self.load_papers()
            
            field_name = list(updates.keys())[0] if updates else "field"
            if self.in_select_mode:
                mode_info = "selected"
            elif len(papers_to_update) > 1:
                mode_info = "previously selected"
            else:
                mode_info = "current"
            self.status_bar.set_status(f"🔄 ✓ Updated {field_name} for {updated_count} {mode_info} paper(s)")
            
        except Exception as e:
            # Show detailed error in error panel instead of just status bar
            self.show_error_panel_with_message(
                "Update Error",
                f"Failed to update papers",
                str(e)
            )
    
    def handle_export_command(self, args: List[str]):
        """Handle /export command."""
        papers_to_export = []
        
        if self.in_select_mode:
            papers_to_export = self.paper_list_control.get_selected_papers()
            if not papers_to_export:
                self.status_bar.set_status(f"⚠️ No papers selected")
                return
        else:
            # Check if there are previously selected papers, otherwise use current paper under cursor
            selected_papers = self.paper_list_control.get_selected_papers()
            if selected_papers:
                papers_to_export = selected_papers
            else:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status(f"⚠️ No paper under cursor")
                    return
                papers_to_export = [current_paper]
        
        try:
            
            # Parse command line arguments for quick export
            if len(args) >= 1:
                # Quick export: /export bibtex [filename]
                export_format = args[0].lower()
                
                if export_format not in ['bibtex', 'markdown', 'html', 'json']:
                    self.status_bar.set_status(f"📖 Usage: /export [bibtex|markdown|html|json] [filename]")
                    return
                
                # Determine filename
                if len(args) >= 2:
                    filename = " ".join(args[1:])  # Support filenames with spaces
                else:
                    extensions = {"bibtex": ".bib", "markdown": ".md", "html": ".html", "json": ".json"}
                    filename = f"papers{extensions[export_format]}"
                
                export_params = {
                    "format": export_format,
                    "destination": "file",
                    "filename": filename
                }
            else:
                # Interactive dialog
                dialog = SimpleExportDialog()  # Use simple dialog for better UX
                export_params = dialog.show_export_dialog(len(papers_to_export))
                
                if not export_params:
                    self.status_bar.set_status(f"❌ Export cancelled")
                    return
            
            self.status_bar.set_status(f"📤 Exporting papers...")
            
            # Export papers
            export_format = export_params['format']
            destination = export_params['destination']
            
            if export_format == 'bibtex':
                content = self.export_service.export_to_bibtex(papers_to_export)
            elif export_format == 'markdown':
                content = self.export_service.export_to_markdown(papers_to_export)
            elif export_format == 'html':
                content = self.export_service.export_to_html(papers_to_export)
            elif export_format == 'json':
                content = self.export_service.export_to_json(papers_to_export)
            else:
                self.status_bar.set_status("Unknown export format")
                return
            
            if destination == 'file':
                filename = export_params['filename']
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.status_bar.set_status(f"📤 ✓ Exported {len(papers_to_export)} papers to {filename}")
            
            elif destination == 'clipboard':
                if self.system_service.copy_to_clipboard(content):
                    self.status_bar.set_status(f"✓ Copied {len(papers_to_export)} papers to clipboard")
                else:
                    self.status_bar.set_status("Error copying to clipboard")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error exporting papers: {e}")
    
    def handle_delete_command(self):
        """Handle /delete command."""
        papers_to_delete = []
        
        if self.in_select_mode:
            papers_to_delete = self.paper_list_control.get_selected_papers()
            if not papers_to_delete:
                self.status_bar.set_status(f"⚠️ No papers selected")
                return
        else:
            # Check if there are previously selected papers, otherwise use current paper under cursor
            selected_papers = self.paper_list_control.get_selected_papers()
            if selected_papers:
                papers_to_delete = selected_papers
            else:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status(f"⚠️ No paper under cursor")
                    return
                papers_to_delete = [current_paper]
        
        try:
            # Confirm deletion
            from prompt_toolkit.shortcuts import yes_no_dialog
            
            paper_titles = [paper.title[:50] + "..." if len(paper.title) > 50 else paper.title 
                          for paper in papers_to_delete]
            
            confirmation = yes_no_dialog(
                title="Confirm Deletion",
                text=f"Are you sure you want to delete {len(papers_to_delete)} papers?\n\n" + 
                     "\n".join(f"• {title}" for title in paper_titles[:5]) +
                     (f"\n... and {len(paper_titles) - 5} more" if len(paper_titles) > 5 else "")
            )
            
            if confirmation:
                paper_ids = [paper.id for paper in papers_to_delete]
                deleted_count = self.paper_service.delete_papers(paper_ids)
                
                # Refresh paper list
                self.load_papers()
                
                self.status_bar.set_status(f"️ ✓ Deleted {deleted_count} papers")
            else:
                self.status_bar.set_status(f"❌ Deletion cancelled")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error deleting papers: {e}")
    
    def handle_show_command(self):
        """Handle /show command."""
        papers_to_show = []
        
        if self.in_select_mode:
            papers_to_show = self.paper_list_control.get_selected_papers()
            if not papers_to_show:
                self.status_bar.set_status(f"⚠️ No papers selected")
                return
        else:
            # Check if there are previously selected papers, otherwise use current paper under cursor
            selected_papers = self.paper_list_control.get_selected_papers()
            if selected_papers:
                papers_to_show = selected_papers
            else:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status(f"⚠️ No paper under cursor")
                    return
                papers_to_show = [current_paper]
        
        try:
            opened_count = 0
            for paper in papers_to_show:
                if paper.pdf_path:
                    success, error_msg = self.system_service.open_pdf(paper.pdf_path)
                    if success:
                        opened_count += 1
                    else:
                        # Show detailed error in error panel instead of just status bar
                        self.show_error_panel_with_message(
                            "PDF Viewer Error",
                            f"Failed to open PDF for: {paper.title}",
                            error_msg
                        )
                        break  # Show only first error
                else:
                    self.status_bar.set_status(f" ⚠️ No PDF available for: {paper.title}")
                    break
            
            if opened_count > 0:
                if self.in_select_mode:
                    mode_info = "selected"
                elif len(papers_to_show) > 1:
                    mode_info = "previously selected"
                else:
                    mode_info = "current"
                self.status_bar.set_status(f" ✓ Opened {opened_count} {mode_info} PDF(s)")
            else:
                self.status_bar.set_status(f" No PDFs found to open")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error opening PDFs: {e}")

    def handle_exit_command(self):
        """Handle /exit command - exit the application."""
        self.app.exit()
    
    def handle_sort_command(self, args: List[str]):
        """Handle /sort command - sort papers by field."""
        if not args:
            self.status_bar.set_status("⚠️ Usage: /sort <field> [asc|desc]. Fields: title, authors, venue, year")
            return
        
        field = args[0].lower()
        order = args[1].lower() if len(args) > 1 else 'asc'
        
        valid_fields = ['title', 'authors', 'venue', 'year']
        valid_orders = ['asc', 'desc', 'ascending', 'descending']
        
        if field not in valid_fields:
            self.status_bar.set_status(f"⚠️ Invalid field '{field}'. Valid fields: {', '.join(valid_fields)}")
            return
        
        if order not in valid_orders:
            self.status_bar.set_status(f"⚠️ Invalid order '{order}'. Valid orders: asc, desc")
            return
        
        try:
            # Preserve selection state
            old_selected_paper_ids = self.paper_list_control.selected_paper_ids.copy()
            old_in_select_mode = self.paper_list_control.in_select_mode
            
            # Sort papers
            reverse = order.startswith('desc')
            
            if field == 'title':
                self.current_papers.sort(key=lambda p: p.title.lower(), reverse=reverse)
            elif field == 'authors':
                self.current_papers.sort(key=lambda p: p.author_names.lower(), reverse=reverse)
            elif field == 'venue':
                self.current_papers.sort(key=lambda p: p.venue_display.lower(), reverse=reverse)
            elif field == 'year':
                self.current_papers.sort(key=lambda p: p.year or 0, reverse=reverse)
            
            # Update paper list control
            self.paper_list_control = PaperListControl(self.current_papers)
            self.paper_list_control.selected_paper_ids = old_selected_paper_ids
            self.paper_list_control.in_select_mode = old_in_select_mode
            
            order_text = "descending" if reverse else "ascending"
            self.status_bar.set_status(f"📊 ✓ Sorted by {field} ({order_text})")
            
        except Exception as e:
            self.status_bar.set_status(f"❌ Error sorting papers: {e}")

    def handle_detail_command(self):
        """Handle /detail command."""
        try:
            papers_to_show = self.paper_list_control.get_selected_papers()
            if not papers_to_show:
                current_paper = self.paper_list_control.get_current_paper()
                if not current_paper:
                    self.status_bar.set_status("⚠️ No paper selected.")
                    return
                papers_to_show = [current_paper]

            details_text = self._format_paper_details(papers_to_show)
            
            # Update buffer content correctly by bypassing the read-only flag
            doc = Document(details_text, 0)
            self.details_buffer.set_document(doc, bypass_readonly=True)

            self.show_details_panel = True
            self.app.layout.focus(self.details_control)
            self.status_bar.set_status("📄 Details panel opened - Press ESC to close")
        except Exception as e:
            import traceback
            self.show_error_panel_with_message(
                "Detail View Error",
                "Could not display paper details.",
                traceback.format_exc()
            )

    def _format_paper_details(self, papers: List[Paper]) -> str:
        """Format metadata for one or more papers into a string."""
        if not papers:
            return "No papers to display."

        if len(papers) == 1:
            paper = papers[0]
            authors = ", ".join([a.full_name for a in paper.authors])
            collections = ", ".join([c.name for c in paper.collections])
            return (
                f"Title:       {paper.title}\n"
                f"Authors:     {authors}\n"
                f"Year:        {paper.year or 'N/A'}\n"
                f"Venue:       {paper.venue_display}\n"
                f"Type:        {paper.paper_type or 'N/A'}\n"
                f"Collections: {collections or 'N/A'}\n"
                f"DOI:         {paper.doi or 'N/A'}\n"
                f"ArXiv ID:    {paper.arxiv_id or 'N/A'}\n"
                f"DBLP URL:    {paper.dblp_url or 'N/A'}\n"
                f"PDF Path:    {paper.pdf_path or 'N/A'}\n\n"
                f"Abstract:\n"
                f"---------\n"
                f"{paper.abstract or 'No abstract available.'}\n\n"
                f"Notes:\n"
                f"------\n"
                f"{paper.notes or 'No notes available.'}"
            )

        # Multiple papers
        output = [f"Displaying common metadata for {len(papers)} selected papers.\n"]
        
        fields_to_compare = ['year', 'paper_type', 'venue_full']
        first_paper = papers[0]

        for field in fields_to_compare:
            value = getattr(first_paper, field)
            is_common = all(getattr(p, field) == value for p in papers[1:])
            display_value = value if is_common else "<Multiple Values>"
            output.append(f"{field.replace('_', ' ').title() + ':':<12} {display_value or 'N/A'}")

        # Special handling for collections (many-to-many)
        first_collections = set(c.name for c in first_paper.collections)
        is_common_collections = all(set(c.name for c in p.collections) == first_collections for p in papers[1:])
        collections_display = ", ".join(sorted(list(first_collections))) if is_common_collections else "<Multiple Values>"
        output.append(f"{'Collections:':<12} {collections_display or 'N/A'}")

        return "\n".join(output)
    
    def show_error_panel_with_message(self, title: str, message: str, details: str = ""):
        """Show error panel with a specific error message."""
        self.error_panel.add_error(title, message, details)
        self.show_error_panel = True
        self.status_bar.set_status(f"❌ {title} - Press ESC to see details")
    
    def show_help_dialog(self):
        """Show help dialog and focus it."""
        self.show_help = True
        self.app.layout.focus(self.help_control)
        self.status_bar.set_status("📖 Help panel opened - Press ESC to close")
    
    def run(self):
        """Run the application."""
        self.app.run()
