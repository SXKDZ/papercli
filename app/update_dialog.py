"""
Update dialog for editing paper metadata.
"""

from typing import List, Optional, Dict, Any
from prompt_toolkit.shortcuts import input_dialog, button_dialog, radiolist_dialog
from .models import Paper


class UpdateDialog:
    """Dialog for updating paper metadata."""
    
    def show_update_dialog(self, papers: List[Paper]) -> Optional[Dict[str, Any]]:
        """Show update dialog and return updates or None if cancelled."""
        try:
            # Show what we're updating
            if len(papers) == 1:
                title = f"Update Paper: {papers[0].title[:50]}..."
            else:
                title = f"Update {len(papers)} Papers"
            
            # Ask what field to update
            field_choice = radiolist_dialog(
                title="Update Field",
                text="Select field to update:",
                values=[
                    ("notes", "Notes"),
                    ("venue_full", "Venue (Full Name)"),
                    ("venue_acronym", "Venue (Acronym)"),
                    ("year", "Year"),
                    ("paper_type", "Paper Type"),
                    ("collections", "Collections (comma-separated)"),
                ]
            ).run()
            
            if not field_choice:
                return None
            
            # Get current value for display
            current_value = ""
            if len(papers) == 1:
                paper = papers[0]
                if field_choice == "notes":
                    current_value = paper.notes or ""
                elif field_choice == "venue_full":
                    current_value = paper.venue_full or ""
                elif field_choice == "venue_acronym":
                    current_value = paper.venue_acronym or ""
                elif field_choice == "year":
                    current_value = str(paper.year) if paper.year else ""
                elif field_choice == "paper_type":
                    current_value = paper.paper_type or ""
                elif field_choice == "collections":
                    current_value = ", ".join([c.name for c in paper.collections])
            
            # Get new value
            if field_choice == "paper_type":
                new_value = radiolist_dialog(
                    title="Paper Type",
                    text="Select paper type:",
                    values=[
                        ("journal", "Journal Article"),
                        ("conference", "Conference Paper"),
                        ("preprint", "Preprint"),
                        ("book", "Book"),
                        ("thesis", "Thesis"),
                        ("workshop", "Workshop Paper"),
                        ("techreport", "Technical Report"),
                    ]
                ).run()
            else:
                prompt_text = f"Enter new {field_choice.replace('_', ' ')}:"
                if current_value:
                    prompt_text += f"\nCurrent: {current_value}"
                
                new_value = input_dialog(
                    title=title,
                    text=prompt_text,
                    default=current_value
                ).run()
            
            if new_value is None:
                return None
            
            # Convert year to int if needed
            if field_choice == "year" and new_value:
                try:
                    new_value = int(new_value)
                except ValueError:
                    return None
            
            return {field_choice: new_value}
            
        except Exception as e:
            return None


class SimpleUpdateDialog:
    """Simple command-line update dialog."""
    
    def show_update_dialog(self, papers: List[Paper]) -> Optional[Dict[str, Any]]:
        """Show simple update dialog using status messages."""
        # For now, return a simple notes update
        # This will be enhanced with proper CLI prompts
        return {"notes": "Updated via PaperCLI"}