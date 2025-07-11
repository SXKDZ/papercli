"""
UI components for PaperCLI using prompt-toolkit.
"""

from typing import List, Optional, Dict, Any, Callable
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.containers import ConditionalContainer, ScrollOffsets
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.widgets import Frame, Box, TextArea, Label, Button, Dialog, RadioList
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import FormattedText, HTML, ANSI
from prompt_toolkit.shortcuts import message_dialog, input_dialog, button_dialog
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.validation import Validator, ValidationError

from rich.table import Table
from rich.console import Console
from rich.text import Text
from rich.style import Style as RichStyle
from io import StringIO
from .models import Paper, Author, Collection


class PaperListControl:
    """Control for displaying and navigating papers in a list."""
    
    def __init__(self, papers: List[Paper]):
        self.papers = papers
        self.paper_ids = {p.id: i for i, p in enumerate(papers)} # Map paper ID to index
        self.selected_index = 0
        self.selected_paper_ids = set() # Store paper IDs, not indices
        self.in_select_mode = False
    
    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for the paper list using rich."""
        if not self.papers:
            return FormattedText([
                ("class:empty", "No papers found.\n"),
                ("class:help", "Use /add to add your first paper.")
            ])

        console = Console(file=StringIO(), force_terminal=True, width=120) # Use a fixed width for consistent layout
        table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1), expand=True)

        table.add_column(" ", width=3)  # For selector
        table.add_column("ID", width=4)
        table.add_column("Title", no_wrap=True, style="dim", ratio=2)
        table.add_column("Authors", no_wrap=True, ratio=2)
        table.add_column("Year", width=6, justify="right")
        table.add_column("Collections", no_wrap=True, width=25)

        for i, paper in enumerate(self.papers):
            is_current = (i == self.selected_index)
            is_selected = (paper.id in self.selected_paper_ids)

            # Determine style based on state
            if is_current:
                row_style = RichStyle(bgcolor="blue") # Standard blue for the cursor line
            elif is_selected:
                row_style = RichStyle(bgcolor="green4") # Muted green for other selected lines
            else:
                row_style = ""

            # Determine prefix based on state
            if is_current and is_selected:
                prefix = "► ✓"
            elif is_current:
                prefix = "►  "
            elif is_selected:
                prefix = "  ✓"
            elif self.in_select_mode:
                prefix = "□  "
            else:
                prefix = "   "
            
            # Truncate text manually for display
            authors = (paper.author_names[:35] + "...") if len(paper.author_names) > 35 else paper.author_names
            title = (paper.title[:45] + "...") if len(paper.title) > 45 else paper.title
            year = str(paper.year) if paper.year else "----"
            
            collections = ""
            if hasattr(paper, 'collections') and paper.collections:
                collection_names = [c.name if hasattr(c, 'name') else str(c) for c in paper.collections]
                collections = ", ".join(collection_names)
            collections = (collections[:23] + "...") if len(collections) > 23 else collections

            table.add_row(
                Text(prefix),
                Text(str(paper.id)),
                Text(title),
                Text(authors),
                Text(year),
                Text(collections),
                style=row_style
            )

        console.print(table)
        output = console.file.getvalue()
        return ANSI(output)
    
    def move_up(self):
        """Move selection up."""
        if self.selected_index > 0:
            self.selected_index -= 1
    
    def move_down(self):
        """Move selection down."""
        if self.selected_index < len(self.papers) - 1:
            self.selected_index += 1
    
    def toggle_selection(self):
        """Toggle selection of current paper (in select mode)."""
        if self.in_select_mode:
            current_paper = self.get_current_paper()
            if current_paper:
                if current_paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(current_paper.id)
                else:
                    self.selected_paper_ids.add(current_paper.id)
    
    def get_current_paper(self) -> Optional[Paper]:
        """Get currently selected paper."""
        if 0 <= self.selected_index < len(self.papers):
            return self.papers[self.selected_index]
        return None
    
    def get_selected_papers(self) -> List[Paper]:
        """Get all selected papers."""
        return [p for p in self.papers if p.id in self.selected_paper_ids]


class StatusBar:
    """Status bar component."""
    
    def __init__(self):
        self.status_text = "Ready"
        self.progress_text = ""
    
    def set_status(self, text: str):
        """Set status text."""
        self.status_text = text
    
    def set_progress(self, text: str):
        """Set progress text."""
        self.progress_text = text
    
    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for status bar."""
        if self.progress_text:
            content = f" {self.status_text}  {self.progress_text} "
        else:
            content = f" {self.status_text} "
        
        return FormattedText([
            ("class:status", content)
        ])


class CommandValidator(Validator):
    """Validator for command input."""
    
    def __init__(self, valid_commands: List[str]):
        self.valid_commands = valid_commands
    
    def validate(self, document):
        """Validate command input."""
        text = document.text.strip()
        if text.startswith('/'):
            command = text.split()[0]
            if command not in self.valid_commands:
                raise ValidationError(message=f"Unknown command: {command}")


class ErrorPanel:
    """Error panel component for displaying detailed error messages."""
    
    def __init__(self):
        self.error_messages = []
        self.show_panel = False
    
    def add_error(self, title: str, message: str, details: str = ""):
        """Add an error message to the panel."""
        self.error_messages.append({
            'title': title,
            'message': message,
            'details': details,
            'timestamp': __import__('datetime').datetime.now()
        })
        self.show_panel = True
    
    def clear_errors(self):
        """Clear all error messages."""
        self.error_messages.clear()
        self.show_panel = False
    
    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for the error panel."""
        if not self.error_messages:
            return FormattedText([])
        
        text = []
        
        for i, error in enumerate(self.error_messages[-5:], 1):  # Show last 5 errors
            # Timestamp
            timestamp = error['timestamp'].strftime("%H:%M:%S")
            text.append(("class:error_time", f"[{timestamp}] "))
            
            # Title
            text.append(("class:error_title", f"{error['title']}\n"))
            
            # Message
            text.append(("class:error_message", f"  {error['message']}\n"))
            
            # Details if available
            if error['details']:
                text.append(("class:error_details", f"  Details: {error['details']}\n"))
            
            if i < len(self.error_messages[-5:]):
                text.append(("", "\n"))
        
        text.append(("", "\n"))
        text.append(("class:error_help", "Press ESC to close this panel"))
        
        return FormattedText(text)


class HelpDialog:
    """Help dialog component."""
    
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
/export   Export paper(s) to a file or clipboard (BibTeX, Markdown, etc.)
/delete   Delete the paper(s) from the library

Navigation & Interaction:
-------------------------
↑/↓       Navigate the paper list
Space     Toggle selection for a paper (only in /select mode)
Enter     Execute a command from the input bar
ESC       Close panels (Help, Error), exit selection mode, or clear the input bar
Tab       Trigger and cycle through auto-completions

Indicators:
-----------
►         Current cursor position
✓         Selected paper
► ✓       Current cursor is on a selected paper
□         An unselected paper (only shown in /select mode)
"""
    
    @staticmethod
    def create_dialog():
        """Create help dialog."""
        help_text = [
            ("class:help_header", "PaperCLI Help\n"),
            ("class:help_header", "=" * 50 + "\n\n"),
            ("class:help", "Commands:\n"),
            ("class:help", "---------\n"),
            ("class:help", "/add      Add a new paper (PDF, arXiv, DBLP, manual, sample)\n"),
            ("class:help", "/search   Search papers by title, author, venue, etc.\n"),
            ("class:help", "/filter   Filter papers by year, author, venue, type\n"),
            ("class:help", "/select   Enter multi-selection mode\n"),
            ("class:help", "/sort     Sort papers by field (title, authors, venue, year)\n"),
            ("class:help", "/all      Show all papers (exit filter/search)\n"),
            ("class:help", "/exit     Exit the application\n\n"),
            
            ("class:help", "Paper Operations (work on cursor or selection):\n"),
            ("class:help", "-----------------------------------------------\n"),
            ("class:help", "/chat     Chat with LLM about paper(s)\n"),
            ("class:help", "/update   Update any field of paper(s)\n"),
            ("class:help", "/show     Show PDF(s) in system viewer\n\n"),
            
            ("class:help", "Multi-Selection Commands:\n"),
            ("class:help", "-------------------------\n"),
            ("class:help", "/export   Export papers to various formats\n"),
            ("class:help", "/delete   Delete selected papers\n\n"),
            
            ("class:help", "Navigation:\n"),
            ("class:help", "-----------\n"),
            ("class:help", "↑/↓       Navigate paper list\n"),
            ("class:help", "Space     Toggle selection (in multi-select mode)\n"),
            ("class:help", "ESC       Exit panels / Clear input\n"),
            ("class:help", "Enter     Execute command\n"),
            ("class:help", "F1        Show this help\n"),
            ("class:help", "Ctrl+C    Exit application\n\n"),
            
            ("class:help", "Auto-completion:\n"),
            ("class:help", "----------------\n"),
            ("class:help", "Type / and use Tab to see available commands\n"),
            ("class:help", "Most commands support subcommand completion\n\n"),
            
            ("class:help_footer", "Press ESC to close this help panel")
        ]
        
        help_text_str = """PaperCLI Help
=============

Commands:
---------
/add      Add a new paper (PDF, arXiv, DBLP, manual, sample)
/search   Search papers by title, author, venue, etc.
/filter   Filter papers by year, author, venue, type
/select   Enter multi-selection mode
/sort     Sort papers by field (title, authors, venue, year)
/all      Show all papers (exit filter/search)
/exit     Exit the application

Paper Operations (work on cursor or selection):
-----------------------------------------------
/chat     Chat with LLM about paper(s)
/update   Update any field of paper(s)
/show     Show PDF(s) in system viewer

Multi-Selection Commands:
-------------------------
/export   Export papers to various formats
/delete   Delete selected papers

Navigation:
-----------
↑/↓       Navigate paper list
Space     Toggle selection (in multi-select mode)
ESC       Exit panels / Clear input
Enter     Execute command
F1        Show this help
Ctrl+C    Exit application

Auto-completion:
----------------
Type / and use Tab to see available commands
Most commands support subcommand completion

Press ESC to close this help panel."""

        # This method is now only used for the HELP_TEXT constant
        # The actual dialog is created using message_dialog in cli.py
        return None