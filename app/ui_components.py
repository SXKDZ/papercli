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
from prompt_toolkit.formatted_text import FormattedText, HTML
from prompt_toolkit.shortcuts import message_dialog, input_dialog, button_dialog
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.validation import Validator, ValidationError

from .models import Paper, Author, Collection


class PaperListControl:
    """Control for displaying and navigating papers in a list."""
    
    def __init__(self, papers: List[Paper]):
        self.papers = papers
        self.selected_index = 0
        self.selected_papers = set()
        self.in_select_mode = False
    
    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for the paper list."""
        if not self.papers:
            return FormattedText([
                ("class:empty", "No papers found.\n"),
                ("class:help", "Use /add to add your first paper.")
            ])
        
        text = []
        
        # Calculate responsive column widths
        terminal_width = 120  # Assume reasonable terminal width
        prefix_width = 2  # For ► or ✓/□ 
        id_width = 6  # For ID column
        
        # Minimum widths
        title_min, authors_min, venue_min, year_width = 30, 20, 15, 4
        available_width = terminal_width - prefix_width - id_width - year_width - 12  # 12 for spacing and separators
        
        # Distribute remaining width proportionally
        title_width = max(title_min, int(available_width * 0.45))
        authors_width = max(authors_min, int(available_width * 0.35))
        venue_width = max(venue_min, available_width - title_width - authors_width)
        
        # Add table headers without border (Frame provides it)
        header_line = f"{'':>{prefix_width}}{'ID':<{id_width}} │ {'Title':<{title_width}} │ {'Authors':<{authors_width}} │ {'Year':<{year_width}} │ {'Collections':<{venue_width}}"
        separator_line = f"{'':>{prefix_width}}{'─' * id_width}─┼─{'─' * title_width}─┼─{'─' * authors_width}─┼─{'─' * year_width}─┼─{'─' * venue_width}"
        
        text.append(("class:table_header", header_line + "\n"))
        text.append(("class:table_border", separator_line + "\n"))
        
        for i, paper in enumerate(self.papers):
            # Determine style and prefix
            if i == self.selected_index:
                if i in self.selected_papers:
                    prefix = "✓ " if self.in_select_mode else "► "
                    style = "class:selected_highlighted"  # Both selected and current
                else:
                    prefix = "□ " if self.in_select_mode else "► "
                    style = "class:selected"
            else:
                if i in self.selected_papers:
                    prefix = "✓ "
                    style = "class:highlighted"  # Selected but not current
                else:
                    prefix = "  " if not self.in_select_mode else "□ "
                    style = "class:paper"
            
            # Format paper info with proper truncation
            paper_id = str(paper.id) if hasattr(paper, 'id') and paper.id else str(i+1)
            authors = (paper.author_names[:authors_width-3] + "...") if len(paper.author_names) > authors_width else paper.author_names
            title = (paper.title[:title_width-3] + "...") if len(paper.title) > title_width else paper.title
            year = str(paper.year) if paper.year else "----"
            
            # Get collections for display
            collections = ""
            if hasattr(paper, 'collections') and paper.collections:
                collection_names = [c.name if hasattr(c, 'name') else str(c) for c in paper.collections]
                collections = ", ".join(collection_names)
            collections = (collections[:venue_width-3] + "...") if len(collections) > venue_width else collections
            
            # Create properly aligned table row with column separators
            line = f"{prefix}{paper_id:<{id_width}} │ {title:<{title_width}} │ {authors:<{authors_width}} │ {year:<{year_width}} │ {collections:<{venue_width}}"
            text.append((style, line + "\n"))
        
        return FormattedText(text)
    
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
            if self.selected_index in self.selected_papers:
                self.selected_papers.remove(self.selected_index)
            else:
                self.selected_papers.add(self.selected_index)
    
    def get_current_paper(self) -> Optional[Paper]:
        """Get currently selected paper."""
        if 0 <= self.selected_index < len(self.papers):
            return self.papers[self.selected_index]
        return None
    
    def get_selected_papers(self) -> List[Paper]:
        """Get all selected papers."""
        return [self.papers[i] for i in self.selected_papers if i < len(self.papers)]


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

Commands:
---------
/add      Add a new paper (PDF, arXiv, DBLP, Google Scholar)
/search   Search papers by title, author, venue, etc.
/filter   Filter papers by criteria
/select   Enter multi-selection mode
/help     Show this help

Paper Operations (work on cursor or selection):
-----------------------------------------------
/chat     Chat with LLM about paper(s)
/update   Update any field of paper(s)
/show     Show PDF(s) in system viewer

Multi-Selection Commands (require /select):
------------------------------------------
/export   Export papers to various formats
/delete   Delete selected papers
/back     Show all papers

Navigation:
-----------
↑/↓       Navigate paper list
Space     Toggle selection (in multi-select mode)
ESC       Exit multi-selection mode / Clear input
Enter     Execute command
Ctrl+C    Exit application

Usage Modes:
------------
LIST MODE:    /chat, /update, /show work on current paper (cursor)
SELECT MODE:  /chat, /update, /show work on selected papers
              Use Space to select multiple papers

Icons:
------
►         Current cursor position
✓         Selected paper (in multi-select mode)
□         Unselected paper (in multi-select mode)
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