from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Button, Static, TextArea
from textual.screen import ModalScreen
from typing import Callable, Dict, Any, List, Optional
from rich.text import Text
from ng.db.models import Paper
import subprocess
import platform
import os
import webbrowser

class DetailDialog(ModalScreen):
    """A modal dialog for displaying detailed paper information."""

    DEFAULT_CSS = """
    DetailDialog {
        align: center middle;
    }
    
    #detail-container {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $surface;
    }
    
    #detail-content {
        height: 1fr;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }
    
    #button-bar {
        height: auto;
        align: center middle;
        margin: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(self, paper: Paper, callback: Callable[[Dict[str, Any] | None], None], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paper = paper
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container(id="detail-container"):
            title = self.paper.title if self.paper.title else "Unknown Title"
            yield Static(f"Paper Details: {title[:50]}{'...' if len(title) > 50 else ''}", id="detail-title")
            with VerticalScroll(id="detail-content"):
                yield Static("", id="detail-text")
            with Horizontal(id="button-bar"):
                yield Button("Close", id="close-button", variant="default")
                yield Button("Open Website", id="website-button", variant="primary", disabled=True)
                yield Button("Open PDF", id="pdf-button", variant="success", disabled=True)

    def on_mount(self) -> None:
        """Initialize the detail display with paper information."""
        detail_text_widget = self.query_one("#detail-text", Static)
        
        if not self.paper:
            detail_text_widget.update("No paper selected for detail view.")
            return
            
        # Format the detail text with rich formatting
        formatted_content = self._format_paper_details_rich(self.paper)
        detail_text_widget.update(formatted_content)
        
        # Enable/disable buttons based on availability
        website_button = self.query_one("#website-button", Button)
        pdf_button = self.query_one("#pdf-button", Button)
        
        # Enable website button if URL is available
        if self.paper.url:
            website_button.disabled = False
            
        # Enable PDF button if PDF path is available
        if self.paper.pdf_path:
            pdf_button.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-button":
            self.dismiss(None)
        elif event.button.id == "website-button":
            self._open_website()
        elif event.button.id == "pdf-button":
            self._open_pdf()
    
    def _open_website(self) -> None:
        """Open the paper's website URL."""
        if self.paper.url:
            try:
                webbrowser.open(self.paper.url)
                self.app.notify(f"Opened website for '{self.paper.title}'", severity="information")
            except Exception as e:
                self.app.notify(f"Failed to open website: {str(e)}", severity="error")
    
    def _open_pdf(self) -> None:
        """Open the paper's PDF file."""
        if not self.paper.pdf_path:
            return
            
        try:
            pdf_path = self.paper.pdf_path
            if not os.path.isabs(pdf_path):
                # Convert relative path to absolute (assuming app has db_path)
                if hasattr(self.app, 'db_path'):
                    data_dir = os.path.dirname(self.app.db_path)
                    pdf_path = os.path.join(data_dir, pdf_path)
            
            if os.path.exists(pdf_path):
                system = platform.system()
                if system == "Darwin":  # macOS
                    subprocess.run(["open", pdf_path])
                elif system == "Windows":
                    os.startfile(pdf_path)
                else:  # Linux
                    subprocess.run(["xdg-open", pdf_path])
                
                self.app.notify(f"Opened PDF for '{self.paper.title}'", severity="information")
            else:
                self.app.notify(f"PDF file not found: {pdf_path}", severity="error")
        except Exception as e:
            self.app.notify(f"Failed to open PDF: {str(e)}", severity="error")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _format_paper_details_rich(self, paper: Paper) -> Text:
        """Format paper details with rich formatting."""
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
            content.append("Website:\n", style="bold cyan")
            content.append(f"{paper.url}\n\n", style="blue underline")
        
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
        if hasattr(paper, 'volume') and paper.volume:
            content.append(f"Volume: {paper.volume}\n", style="dim white")
        if hasattr(paper, 'issue') and paper.issue:
            content.append(f"Issue: {paper.issue}\n", style="dim white")
        if paper.pages:
            content.append(f"Pages: {paper.pages}\n", style="dim white")
        
        # Dates
        content.append(f"\nAdded: {paper.added_date or 'Unknown'}\n", style="dim white")
        content.append(f"Modified: {paper.modified_date or 'Unknown'}\n", style="dim white")
        
        return content

    def _format_paper_details_old(self, papers: List[Paper]) -> str:
        """Format metadata for one or more papers into a string."""
        if not papers:
            return "No papers to display."

        if len(papers) == 1:
            paper = papers[0]
            
            # Get authors
            try:
                if hasattr(paper, 'get_ordered_authors') and callable(paper.get_ordered_authors):
                    authors = ", ".join([a.full_name for a in paper.get_ordered_authors()])
                else:
                    authors = paper.author_names or "Unknown Authors"
            except:
                authors = paper.author_names or "Unknown Authors"
            
            # Get collections
            try:
                if hasattr(paper, "collections") and paper.collections:
                    collections = ", ".join([c.name for c in paper.collections])
                else:
                    collections = ""
            except:
                collections = ""
            
            # Format timestamps
            try:
                added_date_str = (
                    paper.added_date.strftime("%Y-%m-%d %H:%M:%S")
                    if paper.added_date
                    else "N/A"
                )
                modified_date_str = (
                    paper.modified_date.strftime("%Y-%m-%d %H:%M:%S")
                    if paper.modified_date
                    else "N/A"
                )
            except:
                added_date_str = "N/A"
                modified_date_str = "N/A"

            # Choose appropriate label for venue field
            venue_label = "Website:" if paper.paper_type == "preprint" else "Venue:"
            
            # Get venue display
            try:
                venue_display = paper.venue_display if hasattr(paper, 'venue_display') else (paper.venue_full or paper.venue_acronym or "")
            except:
                venue_display = paper.venue_full or paper.venue_acronym or ""

            lines = []
            lines.append(f"Title:        {paper.title}")
            lines.append(f"Authors:      {authors}")
            if paper.year:
                lines.append(f"Year:         {paper.year}")
            lines.append(f"{venue_label:<13} {venue_display}")
            if paper.paper_type:
                lines.append(f"Type:         {paper.paper_type}")
            if collections:
                lines.append(f"Collections:  {collections}")
            if paper.doi:
                lines.append(f"DOI:          {paper.doi}")
            if paper.preprint_id:
                lines.append(f"Preprint ID:  {paper.preprint_id}")
            if hasattr(paper, 'category') and paper.category:
                lines.append(f"Category:     {paper.category}")
            if hasattr(paper, 'volume') and paper.volume:
                lines.append(f"Volume:       {paper.volume}")
            if hasattr(paper, 'issue') and paper.issue:
                lines.append(f"Issue:        {paper.issue}")
            if paper.pages:
                lines.append(f"Pages:        {paper.pages}")
            if paper.url:
                lines.append(f"URL:          {paper.url}")
            if paper.pdf_path:
                lines.append(f"PDF Path:     {paper.pdf_path}")
            lines.append(f"Added:        {added_date_str}")
            lines.append(f"Modified:     {modified_date_str}")
            lines.append("")
            lines.append("Abstract:")
            lines.append("---------")
            lines.append(paper.abstract or "No abstract available.")
            lines.append("")
            lines.append("Notes:")
            lines.append("------")
            lines.append(paper.notes or "No notes available.")
            lines.append("\n")

            return "\n".join(lines)

        # Multiple papers
        output = [f"Displaying common metadata for {len(papers)} selected papers.\n"]

        fields_to_compare = ["year", "paper_type", "venue_full"]
        first_paper = papers[0]

        for field in fields_to_compare:
            try:
                value = getattr(first_paper, field, None)
                is_common = all(getattr(p, field, None) == value for p in papers[1:])
                display_value = value if is_common else "<Multiple Values>"
                output.append(
                    f"{field.replace('_', ' ').title() + ':':<12} {display_value or 'N/A'}"
                )
            except:
                output.append(
                    f"{field.replace('_', ' ').title() + ':':<12} N/A"
                )

        # Special handling for collections (many-to-many)
        try:
            first_collections = set(c.name for c in first_paper.collections) if hasattr(first_paper, 'collections') and first_paper.collections else set()
            is_common_collections = all(
                set(c.name for c in p.collections) == first_collections 
                for p in papers[1:] 
                if hasattr(p, 'collections') and p.collections
            )
            collections_display = (
                ", ".join(sorted(list(first_collections)))
                if is_common_collections and first_collections
                else "<Multiple Values>" if first_collections else "N/A"
            )
        except:
            collections_display = "N/A"
            
        output.append(f"{'Collections:':<12} {collections_display}")

        return "\n".join(output)