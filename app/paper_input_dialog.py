from typing import List, Optional, Dict, Any, Tuple
from prompt_toolkit.shortcuts import input_dialog, radiolist_dialog, checkboxlist_dialog, button_dialog
from prompt_toolkit.validation import ValidationError
from prompt_toolkit.styles import Style

from .models import Paper, Collection
from .validators import FilePathValidator, ArxivValidator, URLValidator, YearValidator


class PaperInputDialog:
    """Dialog for adding/editing paper information."""

    def __init__(self, paper: Optional[Paper] = None):
        self.paper = paper
        self.result = None
        self.cancelled = False

    def show_add_source_dialog(self, app) -> Optional[Tuple[str, str]]:
        """Show dialog to select paper source type."""
        result = radiolist_dialog(
            title="Add Paper",
            text="Select the source for the paper:",
            values=[
                ("pdf", "PDF File"),
                ("arxiv", "arXiv ID"),
                ("dblp", "DBLP URL"),
                ("scholar", "Google Scholar URL"),
                ("manual", "Manual Entry")
            ],
            style=Style.from_dict({
                'dialog': 'bg:#88ff88',
                'dialog frame.label': 'bg:#ffffff #000000',
                'dialog.body': 'bg:#000000 #00ff00',
                'dialog shadow': 'bg:#000088',
            }),
            app=app
        )

        if result:
            if result == "pdf":
                file_path = input_dialog(
                    title="PDF File Path",
                    text="Enter the path to the PDF file:",
                    validator=FilePathValidator(),
                    app=app
                )
                return ("pdf", file_path) if file_path else None

            elif result == "arxiv":
                arxiv_id = input_dialog(
                    title="arXiv ID",
                    text="Enter the arXiv identifier (e.g., 1706.03762):",
                    validator=ArxivValidator(),
                    app=app
                )
                return ("arxiv", arxiv_id) if arxiv_id else None

            elif result == "dblp":
                url = input_dialog(
                    title="DBLP URL",
                    text="Enter the DBLP URL:",
                    validator=URLValidator(),
                    app=app
                )
                return ("dblp", url) if url else None

            elif result == "scholar":
                url = input_dialog(
                    title="Google Scholar URL",
                    text="Enter the Google Scholar URL:",
                    validator=URLValidator(),
                    app=app
                )
                return ("scholar", url) if url else None

            elif result == "manual":
                return ("manual", "")

        return None

    def show_metadata_dialog(self, initial_data: Dict[str, Any] = None, app=None) -> Optional[Dict[str, Any]]:
        """Show dialog for entering/editing paper metadata."""
        if initial_data is None:
            initial_data = {}

        # Create form fields
        fields = {}

        # Title
        title = input_dialog(
            title="Paper Title",
            text="Enter the paper title:",
            default=initial_data.get('title', ''),
            validator=lambda doc: ValidationError(
                message="Title cannot be empty") if not doc.text.strip() else None,
            app=app
        )
        if not title:
            return None
        fields['title'] = title

        # Authors
        authors_str = input_dialog(
            title="Authors",
            text="Enter authors (separated by commas):",
            default=', '.join(initial_data.get('authors', [])),
            app=app
        )
        if not authors_str:
            return None
        fields['authors'] = [name.strip()
                             for name in authors_str.split(',') if name.strip()]

        # Year
        year_str = input_dialog(
            title="Publication Year",
            text="Enter publication year (optional):",
            default=str(initial_data.get('year', '')
                        ) if initial_data.get('year') else '',
            validator=YearValidator(),
            app=app
        )
        if year_str is not None:
            fields['year'] = int(year_str) if year_str.strip() else None
        else:
            return None

        # Paper type
        paper_type = radiolist_dialog(
            title="Paper Type",
            text="Select the type of paper:",
            values=[
                ("journal", "Journal Article"),
                ("conference", "Conference Paper"),
                ("preprint", "Preprint"),
                ("website", "Website/Blog"),
                ("book", "Book"),
                ("thesis", "Thesis"),
                ("other", "Other")
            ],
            default=initial_data.get('paper_type', 'journal'),
            app=app
        )
        if not paper_type:
            return None
        fields['paper_type'] = paper_type

        # Venue
        venue_full = input_dialog(
            title="Venue (Full Name)",
            text="Enter the full venue name:",
            default=initial_data.get('venue_full', ''),
            app=app
        )
        if venue_full is not None:
            fields['venue_full'] = venue_full
        else:
            return None

        venue_acronym = input_dialog(
            title="Venue (Acronym)",
            text="Enter the venue acronym:",
            default=initial_data.get('venue_acronym', ''),
            app=app
        )
        if venue_acronym is not None:
            fields['venue_acronym'] = venue_acronym
        else:
            return None

        # Abstract
        abstract = input_dialog(
            title="Abstract",
            text="Enter the abstract (optional):",
            default=initial_data.get('abstract', ''),
            multiline=True,
            app=app
        )
        if abstract is not None:
            fields['abstract'] = abstract
        else:
            return None

        # Notes
        notes = input_dialog(
            title="Notes",
            text="Enter any notes (optional):",
            default=initial_data.get('notes', ''),
            multiline=True,
            app=app
        )
        if notes is not None:
            fields['notes'] = notes
        else:
            return None

        return fields

    def show_collections_dialog(self, available_collections: List[Collection],
                                selected_collections: List[str] = None, app=None) -> Optional[List[str]]:
        """Show dialog for selecting collections."""
        if selected_collections is None:
            selected_collections = []

        if not available_collections:
            # Create new collection dialog
            collection_name = input_dialog(
                title="New Collection",
                text="No collections exist. Create a new collection:",
                app=app
            )
            return [collection_name] if collection_name else []

        # Show existing collections
        values = [(col.name, col.name) for col in available_collections]
        values.append(("__new__", "[Create New Collection]"))

        selected = checkboxlist_dialog(
            title="Select Collections",
            text="Select collections for this paper:",
            values=values,
            default_values=selected_collections,
            app=app
        )

        if selected is None:
            return None

        # Handle new collection creation
        if "__new__" in selected:
            selected.remove("__new__")
            new_collection = input_dialog(
                title="New Collection",
                text="Enter name for new collection:",
                app=app
            )
            if new_collection:
                selected.append(new_collection)

        return selected

    def show_confirmation_dialog(self, paper_data: Dict[str, Any], app) -> bool:
        """Show confirmation dialog with paper summary."""
        summary = self._format_paper_summary(paper_data)

        return button_dialog(
            title="Confirm Paper Addition",
            text=f"Please confirm the paper details:\n\n{summary}",
            buttons=[
                ("Add Paper", True),
                ("Cancel", False)
            ],
            app=app
        )

    def _format_paper_summary(self, paper_data: Dict[str, Any]) -> str:
        """Format paper data for confirmation display."""
        lines = []

        lines.append(f"Title: {paper_data.get('title', 'N/A')}")

        if paper_data.get('authors'):
            lines.append(
                f"Authors: {', '.join(paper_data['authors'])}")

        if paper_data.get('year'):
            lines.append(f"Year: {paper_data['year']}")

        if paper_data.get('venue_full'):
            venue = paper_data['venue_full']
            if paper_data.get('venue_acronym'):
                venue += f" ({paper_data['venue_acronym']})"
            lines.append(f"Venue: {venue}")

        if paper_data.get('paper_type'):
            lines.append(f"Type: {paper_data['paper_type'].title()}")

        if paper_data.get('abstract'):
            abstract = paper_data['abstract'][:100] + \
                "..." if len(paper_data['abstract']) > 100 else paper_data['abstract']
            lines.append(f"Abstract: {abstract}")

        if paper_data.get('collections'):
            lines.append(
                f"Collections: {', '.join(paper_data['collections'])}")

        return '\n'.join(lines)