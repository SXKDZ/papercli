"""Search and filter commands handler."""

import traceback
from typing import List

from ...ui import PaperListControl
from .base import BaseCommandHandler


class SearchCommandHandler(BaseCommandHandler):
    """Handler for search, filter, sort, and selection commands."""

    def handle_all_command(self):
        """Handle /all command - return to full paper list."""
        if self.cli.in_select_mode:
            # Don't exit selection mode, just show all papers while maintaining selection
            self.load_papers()
            self.cli.status_bar.set_status(
                "Showing all papers (selection mode active)", "papers"
            )
        else:
            # Return to full list from search/filter results
            self.load_papers()
            self.cli.is_filtered_view = False
            self.cli.status_bar.set_status(
                f"Showing all {len(self.cli.current_papers)} papers.", "papers"
            )

    def handle_clear_command(self):
        """Handle /clear command - deselect all papers."""
        if not self.cli.paper_list_control.selected_paper_ids:
            self.cli.status_bar.set_warning("No papers were selected.")
            return

        count = len(self.cli.paper_list_control.selected_paper_ids)
        self.cli.paper_list_control.selected_paper_ids.clear()
        self.cli.status_bar.set_success(
            f"Cleared {count} selected {'paper' if count == 1 else 'papers'}."
        )

    def handle_filter_command(self, args: List[str]):
        """Handle /filter command."""
        if not args:
            self.cli.show_filter_dialog()
            return

        try:
            # Parse command-line filter: /filter <field> <value>
            field = args[0].lower()

            # Handle "all" field - search across all fields
            if field == "all":
                if len(args) < 2:
                    self.cli.status_bar.set_status("Usage: /filter all <query>")
                    return

                query = " ".join(args[1:])
                self.cli.status_bar.set_status(
                    f"Searching all fields for '{query}'", "search"
                )

                # Perform search across all fields like the old search command
                results = self.cli.search_service.search_papers(
                    query, ["title", "authors", "venue", "abstract"]
                )

                if not results:
                    # Try fuzzy search
                    results = self.cli.search_service.fuzzy_search_papers(query)

                # Update display
                self.cli.current_papers = results
                self.cli.paper_list_control = PaperListControl(self.cli.current_papers)
                self.cli.is_filtered_view = True

                self.cli.status_bar.set_status(
                    f"Found {len(results)} papers matching '{query}' in all fields",
                    "select",
                )
                return

            # Handle specific field filtering
            if len(args) < 2:
                self.cli.status_bar.set_status(
                    "Usage: /filter <field> <value>. Fields: year, author, venue, type, collection, all"
                )
                return

            value = " ".join(args[1:])

            # Validate field
            valid_fields = ["year", "author", "venue", "type", "collection"]
            if field not in valid_fields:
                self.cli.status_bar.set_error(
                    f"Invalid filter field '{field}'. Valid fields: {', '.join(valid_fields + ['all'])}"
                )
                return

            filters = {}

            # Convert and validate value based on field
            if field == "year":
                try:
                    filters["year"] = int(value)
                except ValueError:
                    self.cli.status_bar.set_error(f"Invalid year value: {value}")
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
                    self.cli.status_bar.set_error(
                        f"Invalid paper type '{value}'. Valid types: {', '.join(valid_types)}"
                    )
                    return
                filters["paper_type"] = value.lower()
            elif field == "collection":
                filters["collection"] = value

            self._add_log("filter_command", f"Command-line filter: {field}={value}")
            self.cli.status_bar.set_status("Applying filters...", "loading")

            # Apply filters
            results = self.cli.search_service.filter_papers(filters)

            # Update display
            self.cli.current_papers = results
            self.cli.paper_list_control = PaperListControl(self.cli.current_papers)
            self.cli.is_filtered_view = True

            filter_desc = ", ".join([f"{k}={v}" for k, v in filters.items()])
            self.cli.status_bar.set_status(
                f"Found {len(results)} papers matching '{filter_desc}'", "filter"
            )

        except Exception as e:
            self.show_error_panel_with_message(
                "Filter Error",
                f"Error filtering papers: {e}\n\nTraceback: {traceback.format_exc()}",
            )
            self.cli.status_bar.set_error(f"Error filtering papers: {e}")

    def handle_sort_command(self, args: List[str]):
        """Handle /sort command - sort papers by field."""
        if not args:
            self.cli.show_sort_dialog()
            return

        field = args[0].lower()
        order = args[1].lower() if len(args) > 1 else "asc"

        valid_fields = [
            "title",
            "authors",
            "venue",
            "year",
            "paper_type",
            "added_date",
            "modified_date",
        ]
        valid_orders = ["asc", "desc", "ascending", "descending"]

        if field not in valid_fields:
            self.cli.status_bar.set_status(
                f"Invalid field '{field}'. Valid fields: {', '.join(valid_fields)}",
                "warning",
            )
            return

        if order not in valid_orders:
            self.cli.status_bar.set_status(
                f"Invalid order '{order}'. Valid orders: asc, desc", "warning"
            )
            return

        try:
            # Preserve selection state
            old_selected_paper_ids = (
                self.cli.paper_list_control.selected_paper_ids.copy()
            )
            old_in_select_mode = self.cli.paper_list_control.in_select_mode

            # Sort papers
            reverse = order.startswith("desc")

            if field == "title":
                self.cli.current_papers.sort(
                    key=lambda p: p.title.lower(), reverse=reverse
                )
            elif field == "authors":
                self.cli.current_papers.sort(
                    key=lambda p: p.author_names.lower(), reverse=reverse
                )
            elif field == "venue":
                self.cli.current_papers.sort(
                    key=lambda p: p.venue_display.lower(), reverse=reverse
                )
            elif field == "year":
                self.cli.current_papers.sort(key=lambda p: p.year or 0, reverse=reverse)
            elif field == "paper_type":
                self.cli.current_papers.sort(
                    key=lambda p: p.paper_type or "", reverse=reverse
                )
            elif field == "added_date":
                self.cli.current_papers.sort(
                    key=lambda p: p.added_date, reverse=reverse
                )
            elif field == "modified_date":
                self.cli.current_papers.sort(
                    key=lambda p: p.modified_date, reverse=reverse
                )

            # Update paper list control
            self.cli.paper_list_control = PaperListControl(self.cli.current_papers)
            self.cli.paper_list_control.selected_paper_ids = old_selected_paper_ids
            self.cli.paper_list_control.in_select_mode = old_in_select_mode

            order_text = "descending" if reverse else "ascending"
            self.cli.status_bar.set_success(f"Sorted by {field} ({order_text})")

        except Exception as e:
            self.cli.status_bar.set_error(f"Error sorting papers: {e}")

    def handle_select_command(self):
        """Handle /select command - toggle multi-selection mode."""
        if self.cli.in_select_mode:
            # Exit select mode
            self.cli.in_select_mode = False
            self.cli.paper_list_control.in_select_mode = False
            self.cli.status_bar.set_status("Exited multi-selection mode.", "info")
        else:
            # Enter select mode
            self.cli.in_select_mode = True
            self.cli.paper_list_control.in_select_mode = True
            self.cli.status_bar.set_status(
                "Entered multi-selection mode. Use Space to select, F11 or ESC to exit.",
                "select",
            )
