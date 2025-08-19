from typing import List, Optional, Set

from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import DataTable

from ng.db.models import Paper
from ng.services import ThemeService


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
        background: $primary !important;
        color: $text !important;
        text-style: bold;
    }
    PaperList > .datatable--hover {
        background: $primary-background-lighten-1;
    }
    """

    def __init__(self, papers: List[Paper], *args, **kwargs):
        super().__init__(
            show_header=True,
            zebra_stripes=True,
            cursor_type="row",
            cursor_foreground_priority="renderable",  # Preserve Rich Text colors
            *args,
            **kwargs,
        )
        self.papers = papers or []
        self.selected_paper_ids: Set[int] = set()  # For select mode
        self.in_select_mode: bool = False
        self.current_paper_id: Optional[int] = (
            None  # For single selection (non-select mode)
        )
        self.can_focus = True

    def _get_selection_style(self) -> str:
        """Get the theme-appropriate selection style."""
        app = getattr(self, "app", None)
        success_color = ThemeService.get_color("success", app=app)
        return f"bold {success_color}"

    def on_mount(self) -> None:
        self._setup_columns()
        self.populate_table()

    def _get_available_width(self) -> int:
        """Return the available width for columns based on the widget's actual size."""
        widget_width = 0
        try:
            if getattr(self, "size", None) and self.size.width:
                widget_width = self.size.width
            elif getattr(self, "region", None) and self.region.width:
                widget_width = self.region.width
        except Exception:
            widget_width = 0

        if widget_width <= 0:
            try:
                widget_width = (
                    self.app.size.width if getattr(self.app, "size", None) else 120
                )
            except Exception:
                widget_width = 120

        return max(40, widget_width - 2)

    def _setup_columns(self) -> None:
        """Setup the DataTable columns with dynamic width calculation."""
        available_width = self._get_available_width()

        sel_width = 3
        year_width = 6
        remaining_width = max(10, available_width - sel_width - year_width)

        title_width = int(remaining_width * 0.45)
        authors_width = int(remaining_width * 0.25)
        venue_width = int(remaining_width * 0.15)
        collections_width = remaining_width - title_width - authors_width - venue_width

        title_width = max(20, title_width)
        authors_width = max(15, authors_width)
        venue_width = max(10, min(20, venue_width))  # Max 20 chars for venue
        collections_width = max(10, collections_width)

        # Recalculate collections_width if venue was capped
        original_venue_width = int(remaining_width * 0.15)
        if venue_width < original_venue_width:
            # Add the saved space to collections
            collections_width += original_venue_width - venue_width

        # Cap collections width and redistribute to title
        collections_width = min(20, collections_width)  # Max 20 chars for collections

        total_calculated = (
            sel_width
            + title_width
            + authors_width
            + year_width
            + venue_width
            + collections_width
        )
        if total_calculated < available_width:
            title_width += available_width - total_calculated

        self.add_columns("✓", "Title", "Authors", "Year", "Venue", "Collections")

        try:
            columns = list(self.columns.values())
            if len(columns) >= 6:
                columns[0].width = sel_width
                columns[1].width = title_width
                columns[2].width = authors_width
                columns[3].width = year_width
                columns[4].width = venue_width
                columns[5].width = collections_width
        except Exception:
            pass

    def _prepare_row_data(self, paper: "Paper") -> tuple:
        """Prepare formatted row data for a paper."""
        is_selected = paper.id in self.selected_paper_ids
        should_highlight = self.in_select_mode and is_selected

        # Selection indicator - use theme-appropriate colors
        if is_selected:
            selection_indicator = Text("✓", style=self._get_selection_style())
        elif self.in_select_mode:
            selection_indicator = "☐"
        else:
            selection_indicator = ""

        # Get column widths for text truncation
        try:
            column_list = list(self.columns.values())
            title_width = column_list[1].width - 1 if len(column_list) > 1 else 40
            authors_width = column_list[2].width - 1 if len(column_list) > 2 else 25
            venue_width = column_list[4].width - 1 if len(column_list) > 4 else 15
            collections_width = (
                column_list[5].width - 1 if len(column_list) > 5 else 20
            )
        except (IndexError, KeyError, AttributeError):
            title_width = 40
            authors_width = 25
            venue_width = 15
            collections_width = 20

        # Title
        title_text = paper.title
        if len(title_text) > title_width:
            title_text = title_text[: title_width - 3] + "..."
        title = (
            Text(str(title_text), style=self._get_selection_style())
            if should_highlight
            else title_text
        )

        # Authors
        authors_text = paper.author_names or "Unknown Authors"
        if len(authors_text) > authors_width:
            authors_text = authors_text[: authors_width - 3] + "..."
        authors = (
            Text(str(authors_text), style=self._get_selection_style())
            if should_highlight
            else authors_text
        )

        # Year
        year_text = str(paper.year) if paper.year else "—"
        year = (
            Text(str(year_text), style=self._get_selection_style())
            if should_highlight
            else year_text
        )

        # Venue
        venue_text = paper.venue_acronym or paper.venue_full or "—"
        if len(venue_text) > venue_width:
            venue_text = venue_text[: venue_width - 3] + "..."
        venue = (
            Text(str(venue_text), style=self._get_selection_style())
            if should_highlight
            else venue_text
        )

        # Collections
        collections = ""
        try:
            if hasattr(paper, "collections") and paper.collections:
                collection_names = [c.name for c in paper.collections]
                collections = ", ".join(collection_names)
                if len(collections) > collections_width:
                    collections = collections[: collections_width - 3] + "..."
        except Exception:
            collections = "—"

        if not collections:
            collections = "—"

        collections = (
            Text(str(collections), style=self._get_selection_style())
            if should_highlight
            else collections
        )

        return selection_indicator, title, authors, year, venue, collections

    def _update_row_cells(self, row_index: int, paper: "Paper") -> None:
        """Update cells for a specific row without rebuilding the entire table."""
        try:
            if not (0 <= row_index < len(self.papers)):
                return
                
            # Prepare row data using shared logic
            selection_indicator, title, authors, year, venue, collections = self._prepare_row_data(paper)
            
            # Update the row cells using proper key objects
            row_keys = list(self.rows.keys())
            if 0 <= row_index < len(row_keys):
                actual_row_key = row_keys[row_index]
                
                # Get column key objects
                column_keys = list(self.columns.keys())
                if len(column_keys) >= 6:
                    self.update_cell(actual_row_key, column_keys[0], selection_indicator)  # ✓
                    self.update_cell(actual_row_key, column_keys[1], title)               # Title
                    self.update_cell(actual_row_key, column_keys[2], authors)             # Authors
                    self.update_cell(actual_row_key, column_keys[3], year)                # Year
                    self.update_cell(actual_row_key, column_keys[4], venue)               # Venue
                    self.update_cell(actual_row_key, column_keys[5], collections)         # Collections
                else:
                    raise ValueError("Not enough columns")
            else:
                raise ValueError(f"Row index {row_index} out of range")
            
        except Exception:
            # If individual row update fails, fall back to full table update
            self.populate_table()

    def populate_table(self) -> None:
        """Populate the DataTable with papers."""
        # Save cursor position before clear() which resets it to 0
        saved_cursor = self.cursor_row
        self.clear(columns=False)

        for paper in self.papers:
            selection_indicator, title, authors, year, venue, collections = self._prepare_row_data(paper)
            self.add_row(
                selection_indicator,
                title,
                authors,
                year,
                venue,
                collections,
                key=str(paper.id),
            )
        
        # Restore cursor position after rebuild
        if 0 <= saved_cursor < len(self.papers):
            self.move_cursor(row=saved_cursor)

    def update_table(self) -> None:
        """Update the DataTable display to reflect current selection state."""
        current_cursor = self.cursor_row

        # Save scroll position before rebuilding
        try:
            scroll_x, scroll_y = self.scroll_offset
        except:
            scroll_x, scroll_y = 0, 0

        self.populate_table()

        # Restore cursor position
        if 0 <= current_cursor < len(self.papers):
            self.move_cursor(row=current_cursor)

        # Try to restore scroll position
        try:
            self.scroll_to(scroll_x, scroll_y, animate=False)
        except:
            pass

    def get_current_paper(self) -> Optional[Paper]:
        """Get currently highlighted paper."""
        if 0 <= self.cursor_row < len(self.papers):
            return self.papers[self.cursor_row]
        return None

    def get_selected_papers(self) -> List[Paper]:
        """Get all selected papers (in multi-select mode) or current paper (in single mode)."""
        if self.in_select_mode:
            return [p for p in self.papers if p.id in self.selected_paper_ids]
        else:
            # Return current paper in single-select mode
            if self.current_paper_id:
                current_papers = [
                    p for p in self.papers if p.id == self.current_paper_id
                ]
                return current_papers
            return []

    def set_papers(self, papers: List[Paper]) -> None:
        """Sets the papers for the table and updates the display."""
        self.papers = papers or []
        self.selected_paper_ids.clear()
        self.current_paper_id = None
        self.in_select_mode = False
        self.populate_table()
        if self.papers:
            self.move_cursor(row=0)

    def on_resize(self) -> None:
        """Handle resize events to adjust column widths."""
        if hasattr(self, "_setup_complete") and self._setup_complete and self.papers:
            self.clear(columns=True)
            self._setup_columns()
            self.populate_table()

    def set_in_select_mode(self, mode: bool) -> None:
        """Sets the selection mode."""
        self.in_select_mode = mode
        if not mode:
            self.selected_paper_ids.clear()
        self.update_table()

    def toggle_selection(self) -> None:
        """Toggle selection of current paper (in select mode)."""
        if self.in_select_mode:
            current_paper = self.get_current_paper()
            if current_paper:
                current_row = self.cursor_row

                if current_paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(current_paper.id)
                else:
                    self.selected_paper_ids.add(current_paper.id)
                self._update_row_cells(current_row, current_paper)
                self.post_message(self.StatsChanged())

    async def _async_toggle_update(self, current_row: int) -> None:
        """Async helper for toggle selection updates."""
        await self.update_table_async()
        if 0 <= current_row < len(self.papers):
            self.move_cursor(row=current_row)

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection via mouse or keyboard."""
        if hasattr(event, "cursor_row") and 0 <= event.cursor_row < len(self.papers):
            paper = self.papers[event.cursor_row]
            clicked_row = event.cursor_row

            if self.in_select_mode:
                # In select mode: toggle selection
                if paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(paper.id)
                else:
                    self.selected_paper_ids.add(paper.id)
                # Update just the clicked row to avoid visual flicker
                self._update_row_cells(clicked_row, paper)
            else:
                # In single selection mode: set current paper and move cursor
                self.current_paper_id = paper.id
                self.move_cursor(row=clicked_row)

            # Notify that stats changed for any cursor/selection change
            self.post_message(self.StatsChanged())

    def on_click(self, event) -> None:
        """Handle double-click to show paper details."""
        if event.chain == 2:
            current_paper = self.get_current_paper()
            if current_paper:
                self.post_message(self.ShowDetails(current_paper))
                event.prevent_default()
                event.stop()

    def on_key(self, event: events.Key) -> None:
        """Handle key events for paper list."""
        if event.key == "space" and self.in_select_mode:
            self.toggle_selection()
            event.prevent_default()
        # Let DataTable handle all other navigation keys to avoid double movement

    def on_data_table_row_highlighted(self, event) -> None:
        """Handle cursor movement via keyboard navigation."""
        # This is called when cursor moves via keyboard
        # Update current paper for single selection mode
        if not self.in_select_mode:
            current_paper = self.get_current_paper()
            if current_paper:
                self.current_paper_id = current_paper.id


    # Movement methods
    def move_up(self) -> None:
        """Move cursor up."""
        if self.cursor_row > 0:
            self.move_cursor(row=self.cursor_row - 1)
            self._update_current_paper()
            self.post_message(self.StatsChanged())

    def move_down(self) -> None:
        """Move cursor down."""
        if self.cursor_row < len(self.papers) - 1:
            self.move_cursor(row=self.cursor_row + 1)
            self._update_current_paper()
            self.post_message(self.StatsChanged())
        elif self.papers and self.cursor_row == -1:
            self.move_cursor(row=0)
            self._update_current_paper()
            self.post_message(self.StatsChanged())

    def move_page_up(self) -> None:
        """Move cursor up by a page (approximately 10 items)."""
        page_size = 10
        new_row = max(0, self.cursor_row - page_size)
        self.move_cursor(row=new_row)
        self._update_current_paper()
        self.post_message(self.StatsChanged())

    def move_page_down(self) -> None:
        """Move cursor down by a page (approximately 10 items)."""
        page_size = 10
        new_row = min(len(self.papers) - 1, self.cursor_row + page_size)
        self.move_cursor(row=new_row)
        self._update_current_paper()
        self.post_message(self.StatsChanged())

    def move_to_top(self) -> None:
        """Move cursor to the first item."""
        if self.papers:
            self.move_cursor(row=0)
            self._update_current_paper()
            self.post_message(self.StatsChanged())

    def move_to_bottom(self) -> None:
        """Move cursor to the last item."""
        if self.papers:
            self.move_cursor(row=len(self.papers) - 1)
            self._update_current_paper()
            self.post_message(self.StatsChanged())

    def _update_current_paper(self) -> None:
        """Update current paper based on cursor position (for keyboard navigation)."""
        if not self.in_select_mode:
            current_paper = self.get_current_paper()
            if current_paper:
                self.current_paper_id = current_paper.id
            else:
                self.current_paper_id = None

    class ShowDetails(Message):
        """Message to request showing paper details."""

        def __init__(self, paper: "Paper") -> None:
            super().__init__()
            self.paper = paper

    class StatsChanged(Message):
        """Posted when paper list statistics change (cursor, selection, etc.)."""

        def __init__(self) -> None:
            super().__init__()
