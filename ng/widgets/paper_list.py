from textual.widgets import DataTable
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.message import Message
from typing import List, Optional, Set
from rich.text import Text
from datetime import datetime

from ng.db.models import Paper


class PaperList(DataTable):
    """A DataTable widget to display a list of papers with proper Rich table formatting."""

    DEFAULT_CSS = """
    PaperList {
        height: 1fr;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    PaperList > .datatable--header {
        background: $accent;
        text-style: bold;
        color: $text;
    }
    PaperList > .datatable--cursor {
        background: transparent;
    }
    PaperList > .datatable--cursor-row {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    PaperList > .datatable--hover {
        background: $primary-background-lighten-1;
    }
    """

    def __init__(self, papers: List[Paper], *args, **kwargs):
        super().__init__(show_header=True, zebra_stripes=True, cursor_type="row", *args, **kwargs)
        self.papers = papers or []
        self.selected_paper_ids: Set[int] = set()
        self.in_select_mode: bool = False
        self.can_focus = True  # Ensure the table can receive focus

    def on_mount(self) -> None:
        self._setup_columns()
        self.populate_table()

    def _setup_columns(self) -> None:
        """Setup the DataTable columns with dynamic width calculation."""
        # Get terminal width, with safe defaults
        try:
            terminal_width = self.app.size.width if hasattr(self.app, 'size') and self.app.size else 120
        except:
            terminal_width = 120
        
        # Use most of the terminal width - only reserve minimal space for scrollbar
        available_width = max(80, terminal_width - 2)
        
        # Fixed widths for specific columns (minimum requirements)
        sel_width = 3       # Selection indicator
        year_width = 6      # Publication year
        
        # Calculate remaining width for flexible columns
        remaining_width = available_width - sel_width - year_width
        
        # Calculate flexible column widths to use ALL remaining space
        # Title gets priority (45%), Authors 25%, Venue 15%, Collections 15%
        title_width = int(remaining_width * 0.45)
        authors_width = int(remaining_width * 0.25)
        venue_width = int(remaining_width * 0.15)
        collections_width = remaining_width - title_width - authors_width - venue_width  # Use all remaining space
        
        # Ensure minimum widths
        title_width = max(20, title_width)
        authors_width = max(15, authors_width)
        venue_width = max(10, venue_width)
        collections_width = max(10, collections_width)
        
        # Verify we're using the full available width
        total_calculated = sel_width + title_width + authors_width + year_width + venue_width + collections_width
        if total_calculated < available_width:
            # Add extra space to title column
            title_width += available_width - total_calculated
        
        # Use add_columns first to create headers (this is what makes headers work!)
        self.add_columns("✓", "Title", "Authors", "Year", "Venue", "Collections")
        
        # Then set column widths after creation
        try:
            columns = list(self.columns.values())
            if len(columns) >= 6:
                columns[0].width = sel_width
                columns[1].width = title_width
                columns[2].width = authors_width
                columns[3].width = year_width
                columns[4].width = venue_width
                columns[5].width = collections_width
        except:
            pass  # If width setting fails, use defaults
    
    def populate_table(self) -> None:
        """Populate the DataTable with papers."""
        # Clear only rows, not columns
        self.clear(columns=False)
        
        for paper in self.papers:
            is_selected = paper.id in self.selected_paper_ids
            
            # Selection indicator
            if is_selected:
                selection_indicator = "✓"
            elif self.in_select_mode:
                selection_indicator = "□"
            else:
                selection_indicator = ""
            
            # Get column widths for text truncation
            try:
                column_list = list(self.columns.values())
                title_width = column_list[1].width - 1 if len(column_list) > 1 else 40
                authors_width = column_list[2].width - 1 if len(column_list) > 2 else 25
                venue_width = column_list[4].width - 1 if len(column_list) > 4 else 15
                collections_width = column_list[5].width - 1 if len(column_list) > 5 else 20
            except (IndexError, KeyError, AttributeError):
                # Fallback to defaults if columns aren't setup yet
                title_width = 40
                authors_width = 25
                venue_width = 15
                collections_width = 20

            # Format data with proper truncation
            title = paper.title
            if len(title) > title_width:
                title = title[:title_width - 3] + "..."

            authors = paper.author_names or "Unknown Authors"
            if len(authors) > authors_width:
                authors = authors[:authors_width - 3] + "..."

            year = str(paper.year) if paper.year else "—"

            venue = paper.venue_acronym or paper.venue_full or "—"
            if len(venue) > venue_width:
                venue = venue[:venue_width - 3] + "..."

            # Collections
            collections = ""
            try:
                if hasattr(paper, "collections") and paper.collections:
                    collection_names = [c.name for c in paper.collections]
                    collections = ", ".join(collection_names)
                    if len(collections) > collections_width:
                        collections = collections[:collections_width - 3] + "..."
            except:
                collections = "—"

            if not collections:
                collections = "—"
            
            self.add_row(
                selection_indicator,
                title,
                authors,
                year,
                venue,
                collections,
                key=str(paper.id)
            )
    
    def update_table(self) -> None:
        """Update the DataTable display to reflect current selection state."""
        self.populate_table()

    def move_up(self) -> None:
        """Move cursor up."""
        if self.cursor_row > 0:
            self.move_cursor(row=self.cursor_row - 1)

    def move_down(self) -> None:
        """Move cursor down."""
        if self.cursor_row < len(self.papers) - 1:
            self.move_cursor(row=self.cursor_row + 1)
        elif self.papers and self.cursor_row == -1:
            self.move_cursor(row=0)

    def move_page_up(self) -> None:
        """Move cursor up by a page (approximately 10 items)."""
        page_size = 10
        new_row = max(0, self.cursor_row - page_size)
        self.move_cursor(row=new_row)

    def move_page_down(self) -> None:
        """Move cursor down by a page (approximately 10 items)."""
        page_size = 10
        new_row = min(len(self.papers) - 1, self.cursor_row + page_size)
        self.move_cursor(row=new_row)

    def move_to_top(self) -> None:
        """Move cursor to the first item."""
        if self.papers:
            self.move_cursor(row=0)

    def move_to_bottom(self) -> None:
        """Move cursor to the last item."""
        if self.papers:
            self.move_cursor(row=len(self.papers) - 1)

    def toggle_selection(self) -> None:
        """Toggle selection of current paper (in select mode)."""
        if self.in_select_mode:
            current_paper = self.get_current_paper()
            if current_paper:
                if current_paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(current_paper.id)
                else:
                    self.selected_paper_ids.add(current_paper.id)
                self.update_table()  # Re-render to show selection change

    def get_current_paper(self) -> Optional[Paper]:
        """Get currently highlighted paper."""
        if 0 <= self.cursor_row < len(self.papers):
            return self.papers[self.cursor_row]
        return None

    def get_selected_papers(self) -> List[Paper]:
        """Get all selected papers (in multi-select mode) or current paper (in single mode)."""
        if self.in_select_mode:
            # Return all selected papers in multi-select mode
            return [p for p in self.papers if p.id in self.selected_paper_ids]
        else:
            # Return current paper in single-select mode
            current = self.get_current_paper()
            return [current] if current else []

    def set_papers(self, papers: List[Paper]) -> None:
        """Sets the papers for the table and updates the display."""
        self.papers = papers or []
        self.selected_paper_ids.clear()
        self.in_select_mode = False
        if hasattr(self, '_setup_complete'):
            self.populate_table()
        if self.papers:
            self.move_cursor(row=0)
        self._setup_complete = True
        
    def on_resize(self) -> None:
        """Handle resize events to adjust column widths."""
        if hasattr(self, '_setup_complete') and self._setup_complete and self.papers:
            # Clear existing columns and re-setup with new widths
            self.clear(columns=True)
            self._setup_columns()
            self.populate_table()

    def set_in_select_mode(self, mode: bool) -> None:
        """Sets the selection mode."""
        self.in_select_mode = mode
        if not mode:
            self.selected_paper_ids.clear()
        self.update_table()  # Re-render to show selection indicators

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection via mouse or keyboard."""
        if hasattr(event, 'cursor_row') and 0 <= event.cursor_row < len(self.papers):
            # Update cursor position to match the selected row
            paper = self.papers[event.cursor_row]
            if self.in_select_mode:
                # Toggle selection in select mode
                if paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(paper.id)
                else:
                    self.selected_paper_ids.add(paper.id)
                self.update_table()

    def on_data_table_row_highlighted(self, event) -> None:
        """Handle row highlighting via mouse hover or keyboard navigation."""
        # This is called when user navigates with mouse or keyboard
        # We don't need to do anything special here as the DataTable handles highlighting
        pass
    
    def on_click(self, event) -> None:
        """Handle click events on the paper list."""
        if event.chain == 2:  # Double-click detected
            current_paper = self.get_current_paper()
            if current_paper:
                # Post message to show details dialog
                self.post_message(self.ShowDetails(current_paper))
                # Prevent default behavior
                event.prevent_default()
                event.stop()
    
    class ShowDetails(Message):
        """Message to request showing paper details."""
        def __init__(self, paper: 'Paper') -> None:
            super().__init__()
            self.paper = paper