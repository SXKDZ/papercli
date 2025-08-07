from textual.widgets import Static
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from typing import Optional
from rich.text import Text
from ng.db.models import Paper


class DetailsPanel(Container):
    """A details sidebar panel for displaying paper information."""

    DEFAULT_CSS = """
    DetailsPanel {
        dock: right;
        width: 50%;
        height: 100%;
        background: $panel;
        border: thick $accent;
        layer: dialog;
        display: none;
    }
    
    DetailsPanel.show {
        display: block;
    }
    
    DetailsPanel #details-content {
        height: 1fr;
        padding: 1;
        scrollbar-gutter: stable;
    }
    
    DetailsPanel #details-title {
        text-style: bold;
        background: $accent;
        color: $text;
        height: auto;
        padding: 0 1;
    }
    """

    show_panel = reactive(False)
    current_paper = reactive(None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def compose(self):
        yield Static("Paper Details", id="details-title")
        with VerticalScroll(id="details-content"):
            yield Static("", id="details-text")

    def watch_show_panel(self, show: bool) -> None:
        """Update panel visibility based on show_panel."""
        if show:
            self.add_class("show")
        else:
            self.remove_class("show")

    def watch_current_paper(self, paper: Optional[Paper]) -> None:
        """Update panel content when paper changes."""
        if paper:
            self.update_details(paper)
        else:
            self.clear_details()

    def show_details(self, paper: Paper) -> None:
        """Show the details panel with paper information."""
        self.current_paper = paper
        self.show_panel = True

    def hide_details(self) -> None:
        """Hide the details panel."""
        self.show_panel = False
        self.current_paper = None

    def toggle_details(self, paper: Optional[Paper] = None) -> None:
        """Toggle details panel visibility."""
        if self.show_panel:
            self.hide_details()
        elif paper:
            self.show_details(paper)

    def update_details(self, paper: Paper) -> None:
        """Update the details panel content with paper information."""
        details_text = self.query_one("#details-text", Static)
        
        # Build rich text content
        content = Text()
        
        # Title
        content.append("Title:\n", style="bold cyan")
        content.append(f"{paper.title}\n\n", style="white")
        
        # Authors
        content.append("Authors:\n", style="bold cyan")
        authors = paper.author_names if paper.author_names else "Unknown Authors"
        content.append(f"{authors}\n\n", style="white")
        
        # Year and Venue
        content.append("Publication:\n", style="bold cyan")
        year = str(paper.year) if paper.year else "Unknown"
        venue = paper.venue_full or paper.venue_acronym or "Unknown Venue"
        content.append(f"{year} - {venue}\n\n", style="white")
        
        # Abstract
        if paper.abstract:
            content.append("Abstract:\n", style="bold cyan")
            content.append(f"{paper.abstract}\n\n", style="white")
        
        # DOI
        if paper.doi:
            content.append("DOI:\n", style="bold cyan")
            content.append(f"{paper.doi}\n\n", style="white")
        
        # URL
        if paper.url:
            content.append("URL:\n", style="bold cyan")
            content.append(f"{paper.url}\n\n", style="white")
        
        # Preprint ID
        if paper.preprint_id:
            content.append("Preprint ID:\n", style="bold cyan")
            content.append(f"{paper.preprint_id}\n\n", style="white")
        
        # PDF Path
        if paper.pdf_path:
            content.append("PDF:\n", style="bold cyan")
            content.append(f"{paper.pdf_path}\n\n", style="green")
        else:
            content.append("PDF:\n", style="bold cyan")
            content.append("No PDF available\n\n", style="red")
        
        # Collections
        if hasattr(paper, "collections") and paper.collections:
            content.append("Collections:\n", style="bold cyan")
            collection_names = [c.name for c in paper.collections]
            content.append(f"{', '.join(collection_names)}\n\n", style="yellow")
        
        # Notes
        if paper.notes:
            content.append("Notes:\n", style="bold cyan")
            content.append(f"{paper.notes}\n\n", style="white")
        
        # Metadata
        content.append("Metadata:\n", style="bold cyan")
        content.append(f"Paper Type: {paper.paper_type or 'Unknown'}\n", style="dim white")
        content.append(f"Category: {paper.category or 'Unknown'}\n", style="dim white")
        if paper.volume:
            content.append(f"Volume: {paper.volume}\n", style="dim white")
        if paper.issue:
            content.append(f"Issue: {paper.issue}\n", style="dim white")
        if paper.pages:
            content.append(f"Pages: {paper.pages}\n", style="dim white")
        
        # Dates
        content.append(f"\nAdded: {paper.added_date or 'Unknown'}\n", style="dim white")
        content.append(f"Modified: {paper.modified_date or 'Unknown'}\n", style="dim white")
        
        details_text.update(content)

    def clear_details(self) -> None:
        """Clear the details panel content."""
        details_text = self.query_one("#details-text", Static)
        details_text.update("No paper selected")