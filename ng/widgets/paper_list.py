from textual.widgets import DataTable
from textual.message import Message
from typing import List, Optional, Set
from rich.text import Text

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
        background: transparent;
    }
    PaperList > .datatable--cursor-row {
        background: $accent;
        text-style: bold;
        color: $text;
    }
    PaperList > .datatable--hover {
        background: $primary-background-lighten-1;
    }
    PaperList.retain-cursor > .datatable--cursor-row {
        background: $accent;
        text-style: bold;
        color: $text;
    }
    PaperList.retain-selection > .datatable--cursor-row {
        background: $accent;
        text-style: bold;
        color: $text;
    }
    """

    def __init__(self, papers: List[Paper], *args, **kwargs):
        super().__init__(
            show_header=True, zebra_stripes=True, cursor_type="row", *args, **kwargs
        )
        self.papers = papers or []
        self.selected_paper_ids: Set[int] = set()
        self.in_select_mode: bool = False
        self.can_focus = True  # Ensure the table can receive focus

    def on_mount(self) -> None:
        self._setup_columns()
        self.populate_table()

    def _get_available_width(self) -> int:
        """Return the available width for columns based on the widget's actual size."""
        # Prefer the widget's own width; fall back to app width; finally a safe default
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

        # Reserve a couple of cells for scrollbars/borders
        return max(40, widget_width - 2)

    def _setup_columns(self) -> None:
        """Setup the DataTable columns with dynamic width calculation."""
        available_width = self._get_available_width()

        # Fixed widths for specific columns (minimum requirements)
        sel_width = 3  # Selection indicator
        year_width = 6  # Publication year

        # Calculate remaining width for flexible columns
        remaining_width = max(10, available_width - sel_width - year_width)

        # Title gets priority (45%), Authors 25%, Venue 15%, Collections 15%
        title_width = int(remaining_width * 0.45)
        authors_width = int(remaining_width * 0.25)
        venue_width = int(remaining_width * 0.15)
        collections_width = (
            remaining_width - title_width - authors_width - venue_width
        )  # Use all remaining space

        # Ensure minimum widths
        title_width = max(20, title_width)
        authors_width = max(15, authors_width)
        venue_width = max(10, venue_width)
        collections_width = max(10, collections_width)

        # Verify we're using the full available width
        total_calculated = (
            sel_width
            + title_width
            + authors_width
            + year_width
            + venue_width
            + collections_width
        )
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
        except Exception:
            pass  # If width setting fails, use defaults

    def populate_table(self) -> None:
        """Populate the DataTable with papers."""
        # Clear only rows, not columns
        self.clear(columns=False)

        for paper in self.papers:
            is_selected = paper.id in self.selected_paper_ids

            # Selection indicator with enhanced visual styling
            if is_selected:
                # Use bold checkmark with theme-appropriate color for selected items
                success_color = ThemeService.get_color("success", app=self.app)
                selection_indicator = Text("✓", style=f"bold {success_color}")
            elif self.in_select_mode:
                selection_indicator = "☐"  # Checkbox for selectable
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
                # Fallback to defaults if columns aren't setup yet
                title_width = 40
                authors_width = 25
                venue_width = 15
                collections_width = 20

            # Format data with proper truncation
            title_text = paper.title
            if len(title_text) > title_width:
                title_text = title_text[: title_width - 3] + "..."

            # Apply theme-appropriate style to entire row when selected
            if is_selected:
                success_color = ThemeService.get_color("success", app=self.app)
                cell_style = f"bold {success_color}"
            else:
                cell_style = None

            title = Text(title_text, style=cell_style) if cell_style else title_text

            authors_text = paper.author_names or "Unknown Authors"
            if len(authors_text) > authors_width:
                authors_text = authors_text[: authors_width - 3] + "..."

            authors = (
                Text(authors_text, style=cell_style) if cell_style else authors_text
            )

            year_text = str(paper.year) if paper.year else "—"
            year = Text(year_text, style=cell_style) if cell_style else year_text

            venue_text = paper.venue_acronym or paper.venue_full or "—"
            if len(venue_text) > venue_width:
                venue_text = venue_text[: venue_width - 3] + "..."

            venue = Text(venue_text, style=cell_style) if cell_style else venue_text

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
                Text(collections, style=cell_style) if cell_style else collections
            )

            # Collections will use the same blue background as cursor row for selected state

            row_key = str(paper.id)
            added_row = self.add_row(
                selection_indicator,
                title,
                authors,
                year,
                venue,
                collections,
                key=row_key,
            )

            # Apply selected row class if this paper is selected
            if is_selected:
                try:
                    # Add CSS class to mark this row as selected
                    if hasattr(added_row, 'add_class'):
                        added_row.add_class("datatable--selected-row")
                except Exception:
                    pass

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
                # Store current cursor position before update
                current_row = self.cursor_row
                try:
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "toggle_selection_start",
                            f"row={current_row}, paper_id={current_paper.id}, in_select_mode={self.in_select_mode}",
                        )
                except Exception:
                    pass

                if current_paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(current_paper.id)
                    action = "removed"
                else:
                    self.selected_paper_ids.add(current_paper.id)
                    action = "added"

                try:
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "toggle_selection_action",
                            f"{action} paper_id={current_paper.id}, new_selected_ids={list(self.selected_paper_ids)}"
                        )
                except Exception:
                    pass

                self.update_table()  # Re-render to show selection change

                # Restore cursor position after update
                if 0 <= current_row < len(self.papers):
                    self.move_cursor(row=current_row)
                try:
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "toggle_selection_done",
                            f"restored_row={current_row}, selected_ids={list(self.selected_paper_ids)}",
                        )
                except Exception:
                    pass

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
        try:
            # Add logging if app is available
            if hasattr(self, "app") and self.app:
                self.app._add_log(
                    "set_papers", f"PaperList setting {len(papers or [])} papers"
                )
        except Exception:
            pass

        self.papers = papers or []
        self.selected_paper_ids.clear()
        self.in_select_mode = False

        # Always populate the table when papers are set
        self.populate_table()

        if self.papers:
            self.move_cursor(row=0)
        self._setup_complete = True

    def on_resize(self) -> None:
        """Handle resize events to adjust column widths."""
        if hasattr(self, "_setup_complete") and self._setup_complete and self.papers:
            # Clear existing columns and re-setup with new widths
            self.clear(columns=True)
            self._setup_columns()
            self.populate_table()

    def set_in_select_mode(self, mode: bool) -> None:
        """Sets the selection mode."""
        self.in_select_mode = mode
        if not mode:
            self.selected_paper_ids.clear()
        try:
            if hasattr(self, "app") and self.app:
                self.app._add_log(
                    "set_in_select_mode",
                    f"mode={mode}, selected_ids={list(self.selected_paper_ids)}",
                )
        except Exception:
            pass
        self.update_table()  # Re-render to show selection indicators

    def on_data_table_row_selected(self, event) -> None:
        """Handle row selection via mouse or keyboard."""
        if hasattr(event, "cursor_row") and 0 <= event.cursor_row < len(self.papers):
            # Update cursor position to match the selected row
            paper = self.papers[event.cursor_row]
            clicked_row = event.cursor_row
            try:
                if hasattr(self, "app") and self.app:
                    self.app._add_log(
                        "row_selected",
                        f"clicked_row={clicked_row}, paper_id={paper.id}, in_select_mode={self.in_select_mode}",
                    )
            except Exception:
                pass
            
            # Always ensure cursor position is updated, regardless of select mode
            self.move_cursor(row=clicked_row)

            if self.in_select_mode:
                # Toggle selection in select mode
                if paper.id in self.selected_paper_ids:
                    self.selected_paper_ids.remove(paper.id)
                    action = "removed"
                else:
                    self.selected_paper_ids.add(paper.id)
                    action = "added"

                try:
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "mouse_selection_action",
                            f"{action} paper_id={paper.id}, new_selected_ids={list(self.selected_paper_ids)}"
                        )
                except Exception:
                    pass

                # Re-render and restore cursor to keep highlight visible even after focus changes
                self.update_table()
                try:
                    if 0 <= clicked_row < len(self.papers):
                        self.move_cursor(row=clicked_row)
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "row_selected_post_update",
                            f"restored_row={clicked_row}, selected_ids={list(self.selected_paper_ids)}",
                        )
                except Exception:
                    pass
            else:
                # In non-select mode, just ensure cursor position is maintained
                try:
                    if hasattr(self, "app") and self.app:
                        self.app._add_log(
                            "row_selected_cursor_only",
                            f"cursor moved to row={clicked_row}, not in select mode"
                        )
                except Exception:
                    pass

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
        elif event.chain == 1:  # Single-click detected
            # Single-click just selects the paper, no focus change
            # Typing will be handled globally to redirect to command input
            pass

    def on_focus(self) -> None:
        """When the list regains focus, restore cursor position and refresh display."""
        try:
            # Restore stored cursor position if available
            if hasattr(self, '_stored_cursor_row') and 0 <= self._stored_cursor_row < len(self.papers):
                self.move_cursor(row=self._stored_cursor_row)
                # Refresh the table to show cursor styling
                self.update_table()
                if hasattr(self, "app") and self.app:
                    self.app._add_log(
                        "paper_list_focus_restore_cursor",
                        f"restored cursor to stored position={self._stored_cursor_row}"
                    )

            if hasattr(self, "app") and self.app:
                self.app._add_log(
                    "paper_list_focus", 
                    f"cursor_row={self.cursor_row}, "
                    f"selected_ids={list(self.selected_paper_ids)}, in_select_mode={self.in_select_mode}"
                )
        except Exception:
            pass

    def on_blur(self) -> None:
        """When the list loses focus, store cursor position for restoration."""
        try:
            # Store current cursor position for restoration on focus
            self._stored_cursor_row = self.cursor_row

            if hasattr(self, "app") and self.app:
                self.app._add_log(
                    "paper_list_blur",
                    f"cursor_row={self.cursor_row}, stored_cursor={self._stored_cursor_row}, "
                    f"selected_ids={list(self.selected_paper_ids)}, in_select_mode={self.in_select_mode}"
                )
        except Exception:
            pass

    class ShowDetails(Message):
        """Message to request showing paper details."""

        def __init__(self, paper: "Paper") -> None:
            super().__init__()
            self.paper = paper
