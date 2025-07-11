
from typing import Optional, Dict, Any
from prompt_toolkit.shortcuts import input_dialog, checkboxlist_dialog

class SearchDialog:
    """Dialog for search functionality."""

    def show_search_dialog(self) -> Optional[Dict[str, Any]]:
        """Show search dialog."""
        query = input_dialog(
            title="Search Papers",
            text="Enter search query:",
        )

        if not query:
            return None

        # Search options
        fields = checkboxlist_dialog(
            title="Search Fields",
            text="Select fields to search in:",
            values=[
                ("title", "Title"),
                ("authors", "Authors"),
                ("abstract", "Abstract"),
                ("venue", "Venue"),
                ("notes", "Notes")
            ],
            default_values=["title", "authors", "venue"]
        )

        if fields is None:
            return None

        return {
            'query': query,
            'fields': fields
        }
