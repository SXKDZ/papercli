from __future__ import annotations
from typing import List, TYPE_CHECKING, Any, Dict

from ng.commands import CommandHandler
from ng.services import SearchService
from ng.dialogs import FilterDialog, SortDialog

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class SearchCommandHandler(CommandHandler):
    """Handler for search, filter, sort, and selection commands."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.search_service = SearchService()
    
    def _find_paper_list_view(self):
        """Find the paper list view, which may be behind modal dialogs."""
        try:
            # Try current screen first
            return self.app.screen.query_one("#paper-list-view")
        except:
            # If not found, look through screen stack for MainScreen
            for screen in reversed(self.app.screen_stack):
                try:
                    return screen.query_one("#paper-list-view")
                except:
                    continue
            
            # If still not found, try main_screen reference
            if hasattr(self.app, 'main_screen'):
                try:
                    return self.app.main_screen.query_one("#paper-list-view")
                except:
                    pass
        return None

    def handle_all_command(self):
        """Handle /all command - return to full paper list."""
        self.app.load_papers()  # Reload all papers
        
        # Find the paper list view
        paper_list = self._find_paper_list_view()
        if paper_list:
            paper_list.set_in_select_mode(False)
            
        self.app.notify(
            f"Showing all {len(self.app.current_papers)} papers",
            severity="information",
        )

    def handle_clear_command(self):
        """Handle /clear command - deselect all papers."""
        paper_list = self._find_paper_list_view()
        if not paper_list:
            return
            
        if not paper_list.selected_paper_ids:
            self.app.notify("No papers were selected", severity="warning")
            return

        count = len(paper_list.selected_paper_ids)
        paper_list.selected_paper_ids.clear()
        paper_list.update_table()  # Refresh the display
        self.app.notify(
            f"Cleared {count} selected {'paper' if count == 1 else 'papers'}",
            severity="information",
        )

    async def handle_filter_command(self, args: List[str]):
        """Handle /filter command."""
        if not args:

            def filter_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    field = result["field"]
                    value = result["value"]
                    self._apply_filter(field, value)

            await self.app.push_screen(FilterDialog(filter_dialog_callback))
            return

        try:
            # Parse command-line filter: /filter <field> <value>
            field = args[0].lower()

            # Handle "all" field - search across all fields
            if field == "all":
                if len(args) < 2:
                    self.app.notify(
                        "Usage: /filter all <query>", severity="information"
                    )
                    return

                query = " ".join(args[1:])
                self.app.notify(
                    f"Searching all fields for '{query}'", severity="information"
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
                paper_list = self._find_paper_list_view()
                if paper_list:
                    paper_list.set_papers(self.app.current_papers)
                self.app.notify(
                    f"Found {len(results)} papers matching '{query}' in all fields",
                    severity="information",
                )
                return

            # Handle specific field filtering
            if len(args) < 2:
                self.app.notify(
                    "Usage: /filter <field> <value>. Fields: title, abstract, notes, year, author, venue, type, collection, all",
                    severity="information",
                )
                return

            value = " ".join(args[1:])

            # Validate field
            valid_fields = ["title", "abstract", "notes", "year", "author", "venue", "type", "collection"]
            if field not in valid_fields:
                self.app.notify(
                    f"Invalid filter field '{field}'. Valid fields: {', '.join(valid_fields + ['all'])}",
                    severity="error",
                )
                return

            self._apply_filter(field, value)

        except Exception as e:
            self.app.notify(f"Error filtering papers: {e}", severity="error")

    def _apply_filter(self, field: str, value: str):
        # Handle "all" field - search across all fields
        if field == "all":
            self.app.notify(f"Searching all fields for '{value}'", severity="information")
            
            # Perform search across all fields like the old search command
            results = self.search_service.search_papers(
                value, ["title", "authors", "venue", "abstract"]
            )
            
            if not results:
                # Try fuzzy search
                results = self.search_service.fuzzy_search_papers(value)
            
            # Update display
            self.app.current_papers = results
            paper_list = self._find_paper_list_view()
            if paper_list:
                paper_list.set_papers(self.app.current_papers)
                
            self.app.notify(
                f"Found {len(results)} papers matching '{value}' in all fields",
                severity="information",
            )
            return
        
        # Handle individual field searches
        if field in ["title", "abstract", "notes"]:
            # Perform search on specific field
            field_mapping = {
                "title": ["title"],
                "abstract": ["abstract"],
                "notes": ["notes"]
            }
            
            results = self.search_service.search_papers(value, field_mapping[field])
            
            if not results:
                # Try fuzzy search on the specific field
                results = self.search_service.fuzzy_search_papers(value)
            
            # Update display
            self.app.current_papers = results
            paper_list = self._find_paper_list_view()
            if paper_list:
                paper_list.set_papers(self.app.current_papers)
                
            self.app.notify(
                f"Found {len(results)} papers matching '{value}' in {field}",
                severity="information",
            )
            return
        
        filters = {}
        # Convert and validate value based on field
        if field == "year":
            try:
                filters["year"] = int(value)
            except ValueError:
                self.app.notify(f"Invalid year value: {value}", severity="error")
                return
        elif field == "author":
            filters["author"] = value
        elif field == "venue":
            filters["venue"] = value
        elif field == "type":
            # Validate paper type
            valid_types = [
                "conference",
                "journal",
                "workshop",
                "preprint",
                "website",
                "other",
            ]
            if value.lower() not in valid_types:
                self.app.notify(
                    f"Invalid paper type '{value}'. Valid types: {', '.join(valid_types)}",
                    severity="error",
                )
                return
            filters["paper_type"] = value.lower()
        elif field == "collection":
            filters["collection"] = value

        self.app.notify("Applying filters...", severity="information")

        # Apply filters
        results = self.search_service.filter_papers(filters)

        # Update display
        self.app.current_papers = results
        paper_list = self._find_paper_list_view()
        if paper_list:
            paper_list.set_papers(self.app.current_papers)

        filter_desc = ", ".join([f"{k}={v}" for k, v in filters.items()])
        self.app.notify(
            f"Found {len(results)} papers matching '{filter_desc}'",
            severity="information",
        )

    async def handle_sort_command(self, args: List[str]):
        """Handle /sort command - sort papers by field."""
        if not args:

            def sort_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    field = result["field"]
                    reverse = result["reverse"]
                    self._apply_sort(field, reverse)

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
            self.app.notify(
                f"Invalid field '{field}'. Valid fields: {', '.join(valid_fields)}",
                severity="warning",
            )
            return

        if order not in valid_orders:
            self.app.notify(
                f"Invalid order '{order}'. Valid orders: asc, desc", severity="warning"
            )
            return

        try:
            # Sort papers
            reverse = order.startswith("desc")
            self._apply_sort(field, reverse)

        except Exception as e:
            self.app.notify(f"Error sorting papers: {e}", severity="error")

    def _apply_sort(self, field: str, reverse: bool):
        if field == "title":
            self.app.current_papers.sort(key=lambda p: p.title.lower(), reverse=reverse)
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
            self.app.current_papers.sort(key=lambda p: p.added_date, reverse=reverse)
        elif field == "modified_date":
            self.app.current_papers.sort(key=lambda p: p.modified_date, reverse=reverse)

        # Update paper list control
        paper_list = self._find_paper_list_view()
        if paper_list:
            paper_list.set_papers(self.app.current_papers)

        order_text = "descending" if reverse else "ascending"
        self.app.notify(f"Sorted by {field} ({order_text})", severity="information")

    def handle_select_command(self):
        """Handle /select command - toggle multi-selection mode."""
        paper_list = self._find_paper_list_view()
        if not paper_list:
            return
            
        if paper_list.in_select_mode:
            # Exit select mode
            paper_list.set_in_select_mode(False)
            self.app.notify("Exited multi-selection mode", severity="information")
        else:
            # Enter select mode
            paper_list.set_in_select_mode(True)
            self.app.notify(
                "Entered multi-selection mode. Use Space to select, F11 or ESC to exit.",
                severity="information",
            )
