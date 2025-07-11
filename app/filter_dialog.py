
from typing import List, Optional, Dict, Any
from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog

from .models import Collection
from .validators import YearValidator


class FilterDialog:
    """Dialog for filter functionality."""

    def show_filter_dialog(self, available_collections: List[Collection]) -> Optional[Dict[str, Any]]:
        """Show filter dialog."""
        filters = {}

        # Filter by year
        year_filter = radiolist_dialog(
            title="Filter by Year",
            text="Filter by publication year:",
            values=[
                ("none", "No year filter"),
                ("specific", "Specific year"),
                ("range", "Year range"),
                ("recent", "Recent (last 5 years)")
            ],
            default="none"
        )

        if year_filter == "specific":
            year = input_dialog(
                title="Specific Year",
                text="Enter year:",
                validator=YearValidator()
            )
            if year:
                filters['year'] = int(year)

        elif year_filter == "range":
            start_year = input_dialog(
                title="Start Year",
                text="Enter start year:",
                validator=YearValidator()
            )
            end_year = input_dialog(
                title="End Year",
                text="Enter end year:",
                validator=YearValidator()
            )
            if start_year and end_year:
                filters['year_range'] = (int(start_year), int(end_year))

        elif year_filter == "recent":
            from datetime import datetime
            current_year = datetime.now().year
            filters['year_range'] = (current_year - 5, current_year)

        # Filter by paper type
        paper_type = radiolist_dialog(
            title="Filter by Type",
            text="Filter by paper type:",
            values=[
                ("none", "No type filter"),
                ("journal", "Journal Articles"),
                ("conference", "Conference Papers"),
                ("preprint", "Preprints"),
                ("website", "Websites"),
                ("book", "Books"),
                ("thesis", "Theses")
            ],
            default="none"
        )

        if paper_type != "none":
            filters['paper_type'] = paper_type

        # Filter by venue
        venue = input_dialog(
            title="Filter by Venue",
            text="Enter venue name (partial match, optional):",
        )
        if venue:
            filters['venue'] = venue

        # Filter by author
        author = input_dialog(
            title="Filter by Author",
            text="Enter author name (partial match, optional):",
        )
        if author:
            filters['author'] = author

        # Filter by collection
        if available_collections:
            collection_values = [("none", "No collection filter")]
            collection_values.extend(
                [(col.name, col.name) for col in available_collections])

            collection = radiolist_dialog(
                title="Filter by Collection",
                text="Filter by collection:",
                values=collection_values,
                default="none"
            )

            if collection != "none":
                filters['collection'] = collection

        return filters if filters else None
