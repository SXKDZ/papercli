"""
Interactive dialogs for PaperCLI using prompt-toolkit.
"""

from typing import List, Optional, Dict, Any, Tuple
from prompt_toolkit.shortcuts import input_dialog, button_dialog, radiolist_dialog, checkboxlist_dialog
from prompt_toolkit.validation import Validator, ValidationError
from prompt_toolkit.widgets import Dialog, TextArea, Button, Label, Frame, Box, RadioList, CheckboxList
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.formatted_text import FormattedText, HTML
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style
import re
import os
from pathlib import Path

from .models import Paper, Author, Collection


class FilePathValidator(Validator):
    """Validator for file paths."""
    
    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="File path cannot be empty")
        
        path = Path(text)
        if not path.exists():
            raise ValidationError(message="File does not exist")
        
        if not path.is_file():
            raise ValidationError(message="Path is not a file")
        
        if path.suffix.lower() != '.pdf':
            raise ValidationError(message="File must be a PDF")


class ArxivValidator(Validator):
    """Validator for arXiv identifiers."""
    
    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="arXiv ID cannot be empty")
        
        # Clean and validate arXiv ID format
        arxiv_id = re.sub(r'arxiv[:\s]*', '', text, flags=re.IGNORECASE)
        arxiv_id = re.sub(r'[^0-9\.]', '', arxiv_id)
        
        if not re.match(r'\d{4}\.\d{4,5}', arxiv_id):
            raise ValidationError(message="Invalid arXiv ID format (should be YYYY.NNNNN)")


class URLValidator(Validator):
    """Validator for URLs."""
    
    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="URL cannot be empty")
        
        if not text.startswith(('http://', 'https://')):
            raise ValidationError(message="URL must start with http:// or https://")


class YearValidator(Validator):
    """Validator for publication years."""
    
    def validate(self, document):
        text = document.text.strip()
        if not text:
            return  # Year is optional
        
        try:
            year = int(text)
            if year < 1900 or year > 2030:
                raise ValidationError(message="Year must be between 1900 and 2030")
        except ValueError:
            raise ValidationError(message="Year must be a number")


class PaperInputDialog:
    """Dialog for adding/editing paper information."""
    
    def __init__(self, paper: Optional[Paper] = None):
        self.paper = paper
        self.result = None
        self.cancelled = False
    
    def show_add_source_dialog(self) -> Optional[Tuple[str, str]]:
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
            })
        )
        
        if result:
            if result == "pdf":
                file_path = input_dialog(
                    title="PDF File Path",
                    text="Enter the path to the PDF file:",
                    validator=FilePathValidator()
                )
                return ("pdf", file_path) if file_path else None
            
            elif result == "arxiv":
                arxiv_id = input_dialog(
                    title="arXiv ID",
                    text="Enter the arXiv identifier (e.g., 1706.03762):",
                    validator=ArxivValidator()
                )
                return ("arxiv", arxiv_id) if arxiv_id else None
            
            elif result == "dblp":
                url = input_dialog(
                    title="DBLP URL",
                    text="Enter the DBLP URL:",
                    validator=URLValidator()
                )
                return ("dblp", url) if url else None
            
            elif result == "scholar":
                url = input_dialog(
                    title="Google Scholar URL",
                    text="Enter the Google Scholar URL:",
                    validator=URLValidator()
                )
                return ("scholar", url) if url else None
            
            elif result == "manual":
                return ("manual", "")
        
        return None
    
    def show_metadata_dialog(self, initial_data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
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
            validator=lambda doc: ValidationError(message="Title cannot be empty") if not doc.text.strip() else None
        )
        if not title:
            return None
        fields['title'] = title
        
        # Authors
        authors_str = input_dialog(
            title="Authors",
            text="Enter authors (separated by commas):",
            default=', '.join(initial_data.get('authors', []))
        )
        if not authors_str:
            return None
        fields['authors'] = [name.strip() for name in authors_str.split(',') if name.strip()]
        
        # Year
        year_str = input_dialog(
            title="Publication Year",
            text="Enter publication year (optional):",
            default=str(initial_data.get('year', '')) if initial_data.get('year') else '',
            validator=YearValidator()
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
            default=initial_data.get('paper_type', 'journal')
        )
        if not paper_type:
            return None
        fields['paper_type'] = paper_type
        
        # Venue
        venue_full = input_dialog(
            title="Venue (Full Name)",
            text="Enter the full venue name:",
            default=initial_data.get('venue_full', '')
        )
        if venue_full is not None:
            fields['venue_full'] = venue_full
        else:
            return None
        
        venue_acronym = input_dialog(
            title="Venue (Acronym)",
            text="Enter the venue acronym:",
            default=initial_data.get('venue_acronym', '')
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
            multiline=True
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
            multiline=True
        )
        if notes is not None:
            fields['notes'] = notes
        else:
            return None
        
        return fields
    
    def show_collections_dialog(self, available_collections: List[Collection], 
                               selected_collections: List[str] = None) -> Optional[List[str]]:
        """Show dialog for selecting collections."""
        if selected_collections is None:
            selected_collections = []
        
        if not available_collections:
            # Create new collection dialog
            collection_name = input_dialog(
                title="New Collection",
                text="No collections exist. Create a new collection:",
            )
            return [collection_name] if collection_name else []
        
        # Show existing collections
        values = [(col.name, col.name) for col in available_collections]
        values.append(("__new__", "[Create New Collection]"))
        
        selected = checkboxlist_dialog(
            title="Select Collections",
            text="Select collections for this paper:",
            values=values,
            default_values=selected_collections
        )
        
        if selected is None:
            return None
        
        # Handle new collection creation
        if "__new__" in selected:
            selected.remove("__new__")
            new_collection = input_dialog(
                title="New Collection",
                text="Enter name for new collection:",
            )
            if new_collection:
                selected.append(new_collection)
        
        return selected
    
    def show_confirmation_dialog(self, paper_data: Dict[str, Any]) -> bool:
        """Show confirmation dialog with paper summary."""
        summary = self._format_paper_summary(paper_data)
        
        return button_dialog(
            title="Confirm Paper Addition",
            text=f"Please confirm the paper details:\n\n{summary}",
            buttons=[
                ("Add Paper", True),
                ("Cancel", False)
            ]
        )
    
    def _format_paper_summary(self, paper_data: Dict[str, Any]) -> str:
        """Format paper data for confirmation display."""
        lines = []
        
        lines.append(f"Title: {paper_data.get('title', 'N/A')}")
        
        if paper_data.get('authors'):
            lines.append(f"Authors: {', '.join(paper_data['authors'])}")
        
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
            abstract = paper_data['abstract'][:100] + "..." if len(paper_data['abstract']) > 100 else paper_data['abstract']
            lines.append(f"Abstract: {abstract}")
        
        if paper_data.get('collections'):
            lines.append(f"Collections: {', '.join(paper_data['collections'])}")
        
        return '\n'.join(lines)


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
            collection_values.extend([(col.name, col.name) for col in available_collections])
            
            collection = radiolist_dialog(
                title="Filter by Collection",
                text="Filter by collection:",
                values=collection_values,
                default="none"
            )
            
            if collection != "none":
                filters['collection'] = collection
        
        return filters if filters else None


class UpdateDialog:
    """Dialog for updating paper metadata."""
    
    def show_update_dialog(self, papers: List[Paper]) -> Optional[Dict[str, Any]]:
        """Show update dialog for selected papers."""
        if len(papers) == 1:
            # Single paper update
            paper = papers[0]
            initial_data = {
                'title': paper.title,
                'authors': [author.full_name for author in paper.authors],
                'year': paper.year,
                'venue_full': paper.venue_full or '',
                'venue_acronym': paper.venue_acronym or '',
                'paper_type': paper.paper_type or 'journal',
                'abstract': paper.abstract or '',
                'notes': paper.notes or ''
            }
            
            paper_input = PaperInputDialog()
            return paper_input.show_metadata_dialog(initial_data)
        
        else:
            # Multiple papers update - show common fields
            return self._show_bulk_update_dialog(papers)
    
    def _show_bulk_update_dialog(self, papers: List[Paper]) -> Optional[Dict[str, Any]]:
        """Show bulk update dialog for multiple papers."""
        # Find common values
        common_values = self._find_common_values(papers)
        
        updates = {}
        
        # What to update
        fields_to_update = checkboxlist_dialog(
            title="Bulk Update",
            text="Select fields to update:",
            values=[
                ("year", "Publication Year"),
                ("paper_type", "Paper Type"),
                ("venue", "Venue Information"),
                ("collections", "Collections")
            ]
        )
        
        if not fields_to_update:
            return None
        
        # Year update
        if "year" in fields_to_update:
            year_str = input_dialog(
                title="Update Year",
                text="Enter new year for all selected papers:",
                default=str(common_values.get('year', '')),
                validator=YearValidator()
            )
            if year_str:
                updates['year'] = int(year_str)
        
        # Paper type update
        if "paper_type" in fields_to_update:
            paper_type = radiolist_dialog(
                title="Update Paper Type",
                text="Select new paper type for all selected papers:",
                values=[
                    ("journal", "Journal Article"),
                    ("conference", "Conference Paper"),
                    ("preprint", "Preprint"),
                    ("website", "Website/Blog"),
                    ("book", "Book"),
                    ("thesis", "Thesis"),
                    ("other", "Other")
                ],
                default=common_values.get('paper_type', 'journal')
            )
            if paper_type:
                updates['paper_type'] = paper_type
        
        # Venue update
        if "venue" in fields_to_update:
            venue_full = input_dialog(
                title="Update Venue (Full Name)",
                text="Enter new venue full name:",
                default=common_values.get('venue_full', '')
            )
            if venue_full is not None:
                updates['venue_full'] = venue_full
                
                venue_acronym = input_dialog(
                    title="Update Venue (Acronym)",
                    text="Enter new venue acronym:",
                    default=common_values.get('venue_acronym', '')
                )
                if venue_acronym is not None:
                    updates['venue_acronym'] = venue_acronym
        
        return updates if updates else None
    
    def _find_common_values(self, papers: List[Paper]) -> Dict[str, Any]:
        """Find common values among selected papers."""
        common = {}
        
        # Check year
        years = [p.year for p in papers if p.year]
        if years and all(y == years[0] for y in years):
            common['year'] = years[0]
        
        # Check paper type
        types = [p.paper_type for p in papers if p.paper_type]
        if types and all(t == types[0] for t in types):
            common['paper_type'] = types[0]
        
        # Check venue
        venues = [p.venue_full for p in papers if p.venue_full]
        if venues and all(v == venues[0] for v in venues):
            common['venue_full'] = venues[0]
        
        venue_acronyms = [p.venue_acronym for p in papers if p.venue_acronym]
        if venue_acronyms and all(v == venue_acronyms[0] for v in venue_acronyms):
            common['venue_acronym'] = venue_acronyms[0]
        
        return common


class ExportDialog:
    """Dialog for export functionality."""
    
    def show_export_dialog(self, paper_count: int) -> Optional[Dict[str, Any]]:
        """Show export dialog."""
        # Export format
        export_format = radiolist_dialog(
            title="Export Format",
            text=f"Select export format for {paper_count} papers:",
            values=[
                ("bibtex", "BibTeX (.bib)"),
                ("markdown", "Markdown (.md)"),
                ("html", "HTML (.html)"),
                ("json", "JSON (.json)")
            ],
            default="bibtex"
        )
        
        if not export_format:
            return None
        
        # Export destination
        destination = radiolist_dialog(
            title="Export Destination",
            text="Where to export:",
            values=[
                ("file", "Save to file"),
                ("clipboard", "Copy to clipboard")
            ],
            default="file"
        )
        
        if not destination:
            return None
        
        result = {
            'format': export_format,
            'destination': destination
        }
        
        # Get filename if saving to file
        if destination == "file":
            extensions = {
                'bibtex': '.bib',
                'markdown': '.md',
                'html': '.html',
                'json': '.json'
            }
            
            filename = input_dialog(
                title="Export Filename",
                text="Enter filename:",
                default=f"papers{extensions[export_format]}"
            )
            
            if filename:
                result['filename'] = filename
            else:
                return None
        
        return result