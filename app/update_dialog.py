"""
Dialog for updating paper metadata using simple terminal input.
"""

from typing import List, Optional, Dict, Any
from .models import Paper
from .simple_dialogs import SimpleDialogs, SimplePaperDialog


class SimpleUpdateDialog:
    """Dialog for updating paper metadata."""

    def __init__(self):
        self.dialogs = SimpleDialogs()
        self.paper_dialog = SimplePaperDialog()

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
            return self.paper_dialog.show_metadata_dialog(initial_data)
        else:
            # Multiple papers update
            return self._show_bulk_update_dialog(papers)

    def _show_bulk_update_dialog(self, papers: List[Paper]) -> Optional[Dict[str, Any]]:
        """Show bulk update dialog for multiple papers."""
        common_values = self._find_common_values(papers)
        updates = {}

        print("\n=== Bulk Update ===")
        print("Select fields to update:")
        
        # Simple choice for fields
        fields_to_update = self.dialogs.get_input(
            "Enter fields (year, type, venue, collections), comma-separated"
        )
        if not fields_to_update:
            return None
        
        fields = [f.strip() for f in fields_to_update.split(',')]

        if "year" in fields:
            year_str = self.dialogs.get_input(
                "New year", 
                str(common_values.get('year', ''))
            )
            if year_str:
                updates['year'] = int(year_str)

        if "type" in fields:
            paper_type = self.dialogs.get_choice(
                "New paper type",
                [("journal", "Journal"), ("conference", "Conference"), ("preprint", "Preprint")],
                common_values.get('paper_type', 'journal')
            )
            if paper_type:
                updates['paper_type'] = paper_type

        if "venue" in fields:
            venue_full = self.dialogs.get_input("New venue (full)", common_values.get('venue_full', ''))
            venue_acronym = self.dialogs.get_input("New venue (acronym)", common_values.get('venue_acronym', ''))
            updates['venue_full'] = venue_full
            updates['venue_acronym'] = venue_acronym
            
        return updates

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