from __future__ import annotations
from typing import List, TYPE_CHECKING, Any, Dict

from ng.commands.base import CommandHandler
from ng.services.search import SearchService
from ng.widgets.paper_list import PaperList
from ng.dialogs.filter_dialog import FilterDialog # Import the new FilterDialog
from ng.dialogs.sort_dialog import SortDialog # Import the new SortDialog

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp

class SearchCommandHandler(CommandHandler):
    """Handler for search, filter, sort, and selection commands."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.search_service = SearchService()

    def handle_all_command(self):
        """Handle /all command - return to full paper list."""
        self.app.load_papers() # Reload all papers
        self.app.screen.query_one("#paper-list-view").set_in_select_mode(False)
        self.app.screen.query_one("#status-bar").set_status(
            f"Showing all {len(self.app.current_papers)} papers.", "papers"
        )

    def handle_clear_command(self):
        """Handle /clear command - deselect all papers."""
        paper_list = self.app.screen.query_one("#paper-list-view")
        if not paper_list.selected_paper_ids:
            self.app.screen.query_one("#status-bar").set_warning("No papers were selected.")
            return

        count = len(paper_list.selected_paper_ids)
        paper_list.selected_paper_ids.clear()
        paper_list.update_table() # Refresh the display
        self.app.screen.query_one("#status-bar").set_success(f"Cleared {count} selected {'paper' if count == 1 else 'papers'}.")

    async def handle_filter_command(self, args: List[str]):
        """Handle /filter command."""
        if not args:
            def filter_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    field = result["field"]
                    value = result["value"]
                    self._apply_filter(field, value)
                else:
                    self.app.screen.query_one("#status-bar").set_status("Filter cancelled.")

            await self.app.push_screen(FilterDialog(filter_dialog_callback))
            return

        try:
            # Parse command-line filter: /filter <field> <value>
            field = args[0].lower()

            # Handle "all" field - search across all fields
            if field == "all":
                if len(args) < 2:
                    self.app.screen.query_one("#status-bar").set_status("Usage: /filter all <query>")
                    return

                query = " ".join(args[1:])
                self.app.screen.query_one("#status-bar").set_status(
                    f"Searching all fields for '{query}'", "search"
                )

                # Perform search across all fields like the old search command
                results = self.search_service.search_papers(
                    query, ["title", "authors", "venue", "abstract"]
                )

                if not results:
                    # Try fuzzy search
                    results = self.search_service.fuzzy_search_papers(query)

                # Update display
                self.app.current_papers = results
                self.app.screen.query_one("#paper-list-view").set_papers(self.app.current_papers)
                self.app.screen.query_one("#status-bar").set_status(
                    f"Found {len(results)} papers matching '{query}' in all fields",
                    "select",
                )
                return

            # Handle specific field filtering
            if len(args) < 2:
                self.app.screen.query_one("#status-bar").set_status(
                    "Usage: /filter <field> <value>. Fields: year, author, venue, type, collection, all"
                )
                return

            value = " ".join(args[1:])

            # Validate field
            valid_fields = ["year", "author", "venue", "type", "collection"]
            if field not in valid_fields:
                self.app.screen.query_one("#status-bar").set_error(
                    f"Invalid filter field '{field}'. Valid fields: {', '.join(valid_fields + ['all'])}"
                )
                return

            self._apply_filter(field, value)

        except Exception as e:
            self.app.screen.query_one("#status-bar").set_error(f"Error filtering papers: {e}")

    def _apply_filter(self, field: str, value: str):
        filters = {}
        # Convert and validate value based on field
        if field == "year":
            try:
                filters["year"] = int(value)
            except ValueError:
                self.app.screen.query_one("#status-bar").set_error(f"Invalid year value: {value}")
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
                self.app.screen.query_one("#status-bar").set_error(
                    f"Invalid paper type '{value}'. Valid types: {', '.join(valid_types)}"
                )
                return
            filters["paper_type"] = value.lower()
        elif field == "collection":
            filters["collection"] = value

        self.app.screen.query_one("#status-bar").set_status("Applying filters...", "loading")

        # Apply filters
        results = self.search_service.filter_papers(filters)

        # Update display
        self.app.current_papers = results
        self.app.screen.query_one("#paper-list-view").set_papers(self.app.current_papers)

        filter_desc = ", ".join([f"{k}={v}" for k, v in filters.items()])
        self.app.screen.query_one("#status-bar").set_status(
            f"Found {len(results)} papers matching '{filter_desc}'", "filter"
        )

    async def handle_sort_command(self, args: List[str]):
        """Handle /sort command - sort papers by field."""
        if not args:
            def sort_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    field = result["field"]
                    reverse = result["reverse"]
                    self._apply_sort(field, reverse)
                else:
                    self.app.screen.query_one("#status-bar").set_status("Sort cancelled.")

            await self.app.push_screen(SortDialog(sort_dialog_callback))
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
            self.app.screen.query_one("#status-bar").set_status(
                f"Invalid field '{field}'. Valid fields: {', '.join(valid_fields)}",
                "warning",
            )
            return

        if order not in valid_orders:
            self.app.screen.query_one("#status-bar").set_status(
                f"Invalid order '{order}'. Valid orders: asc, desc", "warning"
            )
            return

        try:
            # Sort papers
            reverse = order.startswith("desc")
            self._apply_sort(field, reverse)

        except Exception as e:
            self.app.screen.query_one("#status-bar").set_error(f"Error sorting papers: {e}")

    def _apply_sort(self, field: str, reverse: bool):
        if field == "title":
            self.app.current_papers.sort(
                key=lambda p: p.title.lower(), reverse=reverse
            )
        elif field == "authors":
            self.app.current_papers.sort(
                key=lambda p: p.author_names.lower(), reverse=reverse
            )
        elif field == "venue":
            self.app.current_papers.sort(
                key=lambda p: p.venue_display.lower(), reverse=reverse
            )
        elif field == "year":
            self.app.current_papers.sort(key=lambda p: p.year or 0, reverse=reverse)
        elif field == "paper_type":
            self.app.current_papers.sort(
                key=lambda p: p.paper_type or "", reverse=reverse
            )
        elif field == "added_date":
            self.app.current_papers.sort(
                key=lambda p: p.added_date, reverse=reverse
            )
        elif field == "modified_date":
            self.app.current_papers.sort(
                key=lambda p: p.modified_date, reverse=reverse
            )

        # Update paper list control
        self.app.screen.query_one("#paper-list-view").set_papers(self.app.current_papers)

        order_text = "descending" if reverse else "ascending"
        self.app.screen.query_one("#status-bar").set_success(f"Sorted by {field} ({order_text})")

    def handle_select_command(self):
        """Handle /select command - toggle multi-selection mode."""
        paper_list = self.app.screen.query_one("#paper-list-view")
        if paper_list.in_select_mode:
            # Exit select mode
            paper_list.set_in_select_mode(False)
            self.app.screen.query_one("#status-bar").set_status("Exited multi-selection mode.", "info")
        else:
            # Enter select mode
            paper_list.set_in_select_mode(True)
            self.app.screen.query_one("#status-bar").set_status(
                "Entered multi-selection mode. Use Space to select, F11 or ESC to exit.",
                "select",
            )