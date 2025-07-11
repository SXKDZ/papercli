"""
Simple text-based dialogs for PaperCLI that work in any terminal.
"""

from typing import List, Optional, Dict, Any, Tuple
import re
import os
from pathlib import Path


class SimpleDialogs:
    """Simple text-based dialogs for terminal use."""
    
    @staticmethod
    def get_input(prompt: str, default: str = "", validator=None) -> Optional[str]:
        """Get user input with optional validation."""
        try:
            if default:
                result = input(f"{prompt} [{default}]: ").strip()
                if not result:
                    result = default
            else:
                result = input(f"{prompt}: ").strip()
            
            if validator:
                error = validator(result)
                if error:
                    print(f"Error: {error}")
                    return None
            
            return result
        except (KeyboardInterrupt, EOFError):
            return None
    
    @staticmethod
    def get_choice(prompt: str, choices: List[Tuple[str, str]], default: str = None) -> Optional[str]:
        """Get user choice from a list."""
        print(f"\n{prompt}")
        for i, (key, desc) in enumerate(choices, 1):
            marker = " (default)" if key == default else ""
            print(f"  {i}. {desc}{marker}")
        
        try:
            choice = input("\nEnter choice number: ").strip()
            if not choice and default:
                return default
            
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(choices):
                    return choices[choice_num - 1][0]
            except ValueError:
                pass
            
            print("Invalid choice")
            return None
        except (KeyboardInterrupt, EOFError):
            return None
    
    @staticmethod
    def get_multiline(prompt: str, default: str = "") -> Optional[str]:
        """Get multiline input."""
        print(f"\n{prompt}")
        print("(Enter empty line to finish)")
        lines = []
        
        if default:
            print(f"Default: {default}")
            use_default = input("Use default? (y/n): ").strip().lower()
            if use_default in ['y', 'yes', '']:
                return default
        
        try:
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
            return '\n'.join(lines) if lines else default
        except (KeyboardInterrupt, EOFError):
            return None
    
    @staticmethod
    def confirm(prompt: str) -> bool:
        """Get yes/no confirmation."""
        try:
            response = input(f"{prompt} (y/n): ").strip().lower()
            return response in ['y', 'yes']
        except (KeyboardInterrupt, EOFError):
            return False


class SimplePaperDialog:
    """Simple paper input dialog."""
    
    def __init__(self):
        self.dialogs = SimpleDialogs()
    
    def show_add_source_dialog(self) -> Optional[Tuple[str, str]]:
        """Show source selection dialog."""
        choices = [
            ("pdf", "PDF File"),
            ("arxiv", "arXiv ID"),
            ("dblp", "DBLP URL"),
            ("scholar", "Google Scholar URL"),
            ("manual", "Manual Entry")
        ]
        
        source_type = self.dialogs.get_choice("Select paper source:", choices, "manual")
        if not source_type:
            return None
        
        if source_type == "pdf":
            path = self.dialogs.get_input("Enter PDF file path", validator=self._validate_pdf_path)
            return ("pdf", path) if path else None
        
        elif source_type == "arxiv":
            arxiv_id = self.dialogs.get_input("Enter arXiv ID (e.g., 1706.03762)", validator=self._validate_arxiv)
            return ("arxiv", arxiv_id) if arxiv_id else None
        
        elif source_type == "dblp":
            url = self.dialogs.get_input("Enter DBLP URL", validator=self._validate_url)
            return ("dblp", url) if url else None
        
        elif source_type == "scholar":
            url = self.dialogs.get_input("Enter Google Scholar URL", validator=self._validate_url)
            return ("scholar", url) if url else None
        
        elif source_type == "manual":
            return ("manual", "")
        
        return None
    
    def show_metadata_dialog(self, initial_data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Show metadata input dialog."""
        if initial_data is None:
            initial_data = {}
        
        print("\n=== Paper Metadata ===")
        
        # Title
        title = self.dialogs.get_input(
            "Title", 
            initial_data.get('title', ''),
            validator=lambda x: "Title cannot be empty" if not x.strip() else None
        )
        if not title:
            return None
        
        # Authors
        authors_str = self.dialogs.get_input(
            "Authors (comma-separated)",
            ', '.join(initial_data.get('authors', []))
        )
        if authors_str is None:
            return None
        
        authors = [name.strip() for name in authors_str.split(',') if name.strip()]
        
        # Year
        year_str = self.dialogs.get_input(
            "Year (optional)",
            str(initial_data.get('year', '')) if initial_data.get('year') else '',
            validator=self._validate_year
        )
        if year_str is None:
            return None
        
        year = int(year_str) if year_str.strip() else None
        
        # Paper type
        type_choices = [
            ("journal", "Journal Article"),
            ("conference", "Conference Paper"),
            ("preprint", "Preprint"),
            ("website", "Website/Blog"),
            ("book", "Book"),
            ("thesis", "Thesis"),
            ("other", "Other")
        ]
        
        paper_type = self.dialogs.get_choice(
            "Paper type:",
            type_choices,
            initial_data.get('paper_type', 'journal')
        )
        if not paper_type:
            return None
        
        # Venue
        venue_full = self.dialogs.get_input(
            "Venue (full name, optional)",
            initial_data.get('venue_full', '')
        )
        if venue_full is None:
            return None
        
        venue_acronym = self.dialogs.get_input(
            "Venue (acronym, optional)",
            initial_data.get('venue_acronym', '')
        )
        if venue_acronym is None:
            return None
        
        # Abstract
        abstract = self.dialogs.get_multiline(
            "Abstract (optional):",
            initial_data.get('abstract', '')
        )
        if abstract is None:
            return None
        
        # Notes
        notes = self.dialogs.get_multiline(
            "Notes (optional):",
            initial_data.get('notes', '')
        )
        if notes is None:
            return None
        
        return {
            'title': title,
            'authors': authors,
            'year': year,
            'paper_type': paper_type,
            'venue_full': venue_full,
            'venue_acronym': venue_acronym,
            'abstract': abstract,
            'notes': notes
        }
    
    def show_collections_dialog(self, available_collections, selected_collections=None) -> Optional[List[str]]:
        """Show collections selection dialog."""
        if selected_collections is None:
            selected_collections = []
        
        print("\n=== Collections ===")
        if available_collections:
            print("Available collections:")
            for i, collection in enumerate(available_collections, 1):
                selected = "✓" if collection.name in selected_collections else " "
                print(f"  [{selected}] {i}. {collection.name}")
            
            selections = self.dialogs.get_input(
                "Select collections (comma-separated numbers, or 'n' for new)",
                "n"
            )
            
            if selections is None:
                return None
            
            if selections.strip().lower() == 'n':
                new_collection = self.dialogs.get_input("New collection name")
                return [new_collection] if new_collection else []
            
            try:
                selected_nums = [int(x.strip()) for x in selections.split(',') if x.strip()]
                collection_names = []
                for num in selected_nums:
                    if 1 <= num <= len(available_collections):
                        collection_names.append(available_collections[num - 1].name)
                return collection_names
            except ValueError:
                print("Invalid selection")
                return []
        else:
            new_collection = self.dialogs.get_input("Create new collection")
            return [new_collection] if new_collection else []
    
    def show_confirmation_dialog(self, paper_data: Dict[str, Any]) -> bool:
        """Show confirmation dialog."""
        print("\n=== Confirm Paper Details ===")
        print(f"Title: {paper_data.get('title', 'N/A')}")
        
        if paper_data.get('authors'):
            print(f"Authors: {', '.join(paper_data['authors'])}")
        
        if paper_data.get('year'):
            print(f"Year: {paper_data['year']}")
        
        if paper_data.get('venue_full'):
            venue = paper_data['venue_full']
            if paper_data.get('venue_acronym'):
                venue += f" ({paper_data['venue_acronym']})"
            print(f"Venue: {venue}")
        
        if paper_data.get('paper_type'):
            print(f"Type: {paper_data['paper_type'].title()}")
        
        if paper_data.get('abstract'):
            abstract = paper_data['abstract'][:100] + "..." if len(paper_data['abstract']) > 100 else paper_data['abstract']
            print(f"Abstract: {abstract}")
        
        if paper_data.get('collections'):
            print(f"Collections: {', '.join(paper_data['collections'])}")
        
        return self.dialogs.confirm("\nAdd this paper?")
    
    def _validate_pdf_path(self, path: str) -> Optional[str]:
        """Validate PDF file path."""
        if not path:
            return "File path cannot be empty"
        
        path_obj = Path(path)
        if not path_obj.exists():
            return "File does not exist"
        
        if not path_obj.is_file():
            return "Path is not a file"
        
        if path_obj.suffix.lower() != '.pdf':
            return "File must be a PDF"
        
        return None
    
    def _validate_arxiv(self, arxiv_id: str) -> Optional[str]:
        """Validate arXiv ID."""
        if not arxiv_id:
            return "arXiv ID cannot be empty"
        
        # Clean and validate arXiv ID format
        cleaned = re.sub(r'arxiv[:\s]*', '', arxiv_id, flags=re.IGNORECASE)
        cleaned = re.sub(r'[^0-9\.]', '', cleaned)
        
        if not re.match(r'\d{4}\.\d{4,5}', cleaned):
            return "Invalid arXiv ID format (should be YYYY.NNNNN)"
        
        return None
    
    def _validate_url(self, url: str) -> Optional[str]:
        """Validate URL."""
        if not url:
            return "URL cannot be empty"
        
        if not url.startswith(('http://', 'https://')):
            return "URL must start with http:// or https://"
        
        return None
    
    def _validate_year(self, year_str: str) -> Optional[str]:
        """Validate year."""
        if not year_str.strip():
            return None  # Year is optional
        
        try:
            year = int(year_str)
            if year < 1900 or year > 2030:
                return "Year must be between 1900 and 2030"
        except ValueError:
            return "Year must be a number"
        
        return None


class SimpleSearchDialog:
    """Simple search dialog."""
    
    def __init__(self):
        self.dialogs = SimpleDialogs()
    
    def show_search_dialog(self) -> Optional[Dict[str, Any]]:
        """Show search dialog."""
        query = self.dialogs.get_input("Enter search query")
        if not query:
            return None
        
        print("\nSearch in:")
        field_choices = [
            ("title", "Title"),
            ("authors", "Authors"),
            ("abstract", "Abstract"),
            ("venue", "Venue"),
            ("notes", "Notes")
        ]
        
        # Simple field selection
        fields_input = self.dialogs.get_input(
            "Select fields (comma-separated numbers, default: 1,2,4 for title,authors,venue)",
            "1,2,4"
        )
        
        if fields_input is None:
            return None
        
        try:
            field_nums = [int(x.strip()) for x in fields_input.split(',')]
            selected_fields = []
            for num in field_nums:
                if 1 <= num <= len(field_choices):
                    selected_fields.append(field_choices[num - 1][0])
            
            return {
                'query': query,
                'fields': selected_fields if selected_fields else ['title', 'authors', 'venue']
            }
        except ValueError:
            return {
                'query': query,
                'fields': ['title', 'authors', 'venue']
            }

