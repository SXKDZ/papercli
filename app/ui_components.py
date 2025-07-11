"""
UI components for PaperCLI using prompt-toolkit.
"""

from typing import List, Optional
from prompt_toolkit.formatted_text import FormattedText, ANSI
from prompt_toolkit.validation import Validator, ValidationError

from rich.table import Table
from rich.console import Console
from rich.text import Text
from rich.style import Style as RichStyle
from io import StringIO
from .models import Paper


class PaperListControl:
    """Control for displaying and navigating papers in a list."""

    def __init__(self, papers: List[Paper]):
        self.papers = papers
        self.paper_ids = {
            p.id: i for i, p in enumerate(papers)
        }  # Map paper ID to index
        self.selected_index = 0
        self.selected_paper_ids = set()  # Store paper IDs, not indices
        self.in_select_mode = False

    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for the paper list using rich."""
        if not self.papers:
            return FormattedText(
                [
                    ("class:empty", "No papers found.\n"),
                    ("class:help", "Use /add to add your first paper."),
                ]
            )

        console = Console(
            file=StringIO(), force_terminal=True, width=120
        )  # Use a fixed width for consistent layout
        table = Table(
            show_header=True,
            header_style="bold magenta",
            box=None,
            padding=(0, 1),
            expand=True,
        )

        table.add_column(" ", width=3)  # For selector
        table.add_column("ID", width=4)
        table.add_column("Title", no_wrap=True, style="dim", ratio=5)
        table.add_column("Authors", no_wrap=True, ratio=5)
        table.add_column("Year", width=6, justify="right")
        table.add_column("Venue", no_wrap=True, width=6)
        table.add_column("Collections", no_wrap=True, width=20)

        for i, paper in enumerate(self.papers):
            is_current = i == self.selected_index
            is_selected = paper.id in self.selected_paper_ids

            # Determine style based on state
            if is_current:
                row_style = RichStyle(
                    bgcolor="blue"
                )  # Standard blue for the cursor line
            elif is_selected:
                row_style = RichStyle(
                    bgcolor="green4"
                )  # Muted green for other selected lines
            else:
                row_style = ""

            # Determine prefix based on state
            if is_current:
                if is_selected:
                    prefix = "► ✓"
                elif self.in_select_mode:
                    prefix = "► □"
                else:
                    prefix = "►  "
            else:  # not current
                if is_selected:
                    prefix = "  ✓"
                elif self.in_select_mode:
                    prefix = "  □"
                else:
                    prefix = "   "

            # Truncate text manually for display
            authors = (
                (paper.author_names[:35] + "...")
                if len(paper.author_names) > 35
                else paper.author_names
            )
            title = (paper.title[:45] + "...") if len(paper.title) > 45 else paper.title
            year = str(paper.year) if paper.year else "----"
            venue = paper.venue_acronym or paper.venue_full or ""
            venue = (
                (venue[:18] + "...")
                if len(venue) > 18
                else venue
            )

            collections = ""
            if hasattr(paper, "collections") and paper.collections:
                collection_names = [
                    c.name if hasattr(c, "name") else str(c) for c in paper.collections
                ]
                collections = ", ".join(collection_names)
            collections = (
                (collections[:23] + "...") if len(collections) > 23 else collections
            )

            table.add_row(
                Text(prefix),
                Text(str(paper.id)),
                Text(title),
                Text(authors),
                Text(year),
                Text(venue),
                Text(collections),
                style=row_style,
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
    """Status bar component with color-coded status types."""

    def __init__(self):
        self.status_text = "Ready"
        self.progress_text = ""
        self.status_type = "info"  # info, success, error, warning

    def set_status(self, text: str, status_type: str = "info"):
        """Set status text with optional type for color coding."""
        # Automatically add prefix based on status type
        prefixes = {
            "success": "✓ ",
            "error": "✗ ",
            "warning": "⚠ ",
            "info": ""
        }
        
        prefix = prefixes.get(status_type, "")
        # Only add prefix if message doesn't already have a symbol
        if prefix and not any(text.strip().startswith(sym) for sym in ["✓", "✗", "⚠", "📚", "🎯", "🔽", "💬", "🔄", "📤", "📊", "🧹", "🔍"]):
            self.status_text = prefix + text
        else:
            self.status_text = text
            
        self.status_type = status_type

    def set_success(self, text: str):
        """Set success status (green background with ✓ prefix)."""
        self.set_status(text, "success")

    def set_error(self, text: str):
        """Set error status (red background with ✗ prefix)."""
        self.set_status(text, "error")

    def set_warning(self, text: str):
        """Set warning status (yellow background with ⚠ prefix)."""
        self.set_status(text, "warning")

    def set_progress(self, text: str):
        """Set progress text."""
        self.progress_text = text

    def get_formatted_text(self) -> FormattedText:
        """Get formatted text for status bar with color coding."""
        if self.progress_text:
            content = f" {self.status_text}  {self.progress_text} "
        else:
            content = f" {self.status_text} "

        # Choose style class based on status type
        style_class = f"class:status-{self.status_type}"
        return FormattedText([(style_class, content)])


class CommandValidator(Validator):
    """Validator for command input."""

    def __init__(self, valid_commands: List[str]):
        self.valid_commands = valid_commands

    def validate(self, document):
        """Validate command input."""
        text = document.text.strip()
        if text.startswith("/"):
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
        self.error_messages.append(
            {
                "title": title,
                "message": message,
                "details": details,
                "timestamp": __import__("datetime").datetime.now(),
            }
        )
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
            timestamp = error["timestamp"].strftime("%H:%M:%S")
            text.append(("class:error_time", f"[{timestamp}] "))

            # Title
            text.append(("class:error_title", f"{error['title']}\n"))

            # Message
            text.append(("class:error_message", f"  {error['message']}\n"))

            # Details if available
            if error["details"]:
                text.append(("class:error_details", f"  Details: {error['details']}\n"))

            if i < len(self.error_messages[-5:]):
                text.append(("", "\n"))

        text.append(("", "\n"))
        text.append(("class:error_help", "Press ESC to close this panel"))

        return FormattedText(text)

    def get_formatted_text_for_buffer(self) -> str:
        """Get plain text for the error buffer."""
        if not self.error_messages:
            return ""

        text = []
        for error in self.error_messages:
            timestamp = error["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            text.append(f"[{timestamp}] {error['title']}")
            text.append(f"  Message: {error['message']}")
            if error["details"]:
                text.append(f"  Details: {error['details']}")
            text.append("-" * 20)
        return "\n".join(text)
