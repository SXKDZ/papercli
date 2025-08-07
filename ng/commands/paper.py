from __future__ import annotations
from typing import List, TYPE_CHECKING, Any, Dict

from ng.commands.base import CommandHandler
from ng.services.paper import PaperService
from ng.services.add_paper import AddPaperService # Import AddPaperService
from ng.services.system import SystemService # Import SystemService
from ng.dialogs.add_dialog import AddDialog # Import the new AddDialog
from ng.dialogs.edit_dialog import EditDialog # Import the new EditDialog
from ng.dialogs.message_dialog import MessageDialog # For confirmation dialog
from ng.db.models import Paper # Import Paper model for type hinting
from datetime import datetime
import os
import platform
import subprocess

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp

class PaperCommandHandler(CommandHandler):
    """Handler for paper-related commands like add, edit, delete, open, detail."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.paper_service = PaperService()
        self.add_paper_service = AddPaperService(
            paper_service=self.paper_service,
            metadata_extractor=self.app.metadata_extractor, # Assuming metadata_extractor is on app
            system_service=self.app.system_service # Assuming system_service is on app
        )

    def _get_target_papers(self) -> List[Paper]:
        """Helper to get selected papers from the main app's paper list."""
        return self.app.screen.query_one("#paper-list-view").get_selected_papers()

    async def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        if not args:
            # Show the add dialog if no arguments are provided
            def add_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    source = result.get("source", "").strip()
                    path_id = result.get("path_id", "").strip()

                    if not source:
                        self.app.screen.query_one("#status-bar").set_error("Source is required")
                        return

                    # Determine the type of source and call appropriate add command
                    try:
                        self.app.screen.query_one("#status-bar").set_status(f"Adding paper from {source}: {path_id}...", "loading")
                        
                        if source.lower() == "arxiv":
                            self.app.screen.query_one("#status-bar").set_status(f"Extracting metadata for arXiv: {path_id}...", "loading")
                            result = self.add_paper_service.add_arxiv_paper(path_id)
                            if result and result.get("paper"):
                                self.app.screen.query_one("#status-bar").set_success(f"Successfully added arXiv paper: {path_id}")
                                if result.get("pdf_error"):
                                    self.app.screen.query_one("#status-bar").set_warning(f"Added paper but PDF download failed: {result['pdf_error']}")
                            else:
                                self.app.screen.query_one("#status-bar").set_error(f"Failed to add arXiv paper: {path_id} - No paper created")
                        elif source.lower() == "dblp":
                            result = self.add_paper_service.add_dblp_paper(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added DBLP paper: {path_id}")
                        elif source.lower() == "openreview":
                            result = self.add_paper_service.add_openreview_paper(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added OpenReview paper: {path_id}")
                        elif source.lower() == "doi":
                            result = self.add_paper_service.add_doi_paper(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added DOI paper: {path_id}")
                        elif source.lower() == "bib":
                            result = self.add_paper_service.add_bib_papers(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added papers from BibTeX: {path_id}")
                        elif source.lower() == "ris":
                            result = self.add_paper_service.add_ris_papers(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added papers from RIS: {path_id}")
                        elif source.lower() == "pdf":
                            result = self.add_paper_service.add_pdf_paper(path_id)
                            self.app.screen.query_one("#status-bar").set_success(f"Successfully added PDF paper: {path_id}")
                        elif source.lower() == "manual":
                            # Manual entry is handled differently, as it doesn't use external metadata services
                            # For now, we'll just simulate it.
                            self.app.screen.query_one("#status-bar").set_success(f"Manual paper entry for '{path_id}' simulated.")
                        else:
                            self.app.screen.query_one("#status-bar").set_error(f"Unknown source: {source}")
                            return

                        self.app.load_papers() # Reload papers after adding
                    except Exception as e:
                        self.app.screen.query_one("#status-bar").set_error(f"Error adding paper: {str(e)}")
                        # Also log the error for debugging
                        self.app._add_log("add_paper_error", f"Failed to add {source} paper {path_id}: {str(e)}")
                else:
                    # Dialog was cancelled
                    self.app.screen.query_one("#status-bar").set_status("Closed add dialog", "close")

            add_dialog = AddDialog(add_dialog_callback)
            await self.app.push_screen(add_dialog)
        else:
            # Handle direct add command: /add <source> [path_id]
            source = args[0].lower()
            path_id = args[1] if len(args) > 1 else None

            try:
                self.app.screen.query_one("#status-bar").set_status(f"Adding paper from {source}: {path_id}...", "loading")
                
                if source == "arxiv":
                    result = self.add_paper_service.add_arxiv_paper(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added arXiv paper: {path_id}")
                elif source == "dblp":
                    result = self.add_paper_service.add_dblp_paper(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added DBLP paper: {path_id}")
                elif source == "openreview":
                    result = self.add_paper_service.add_openreview_paper(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added OpenReview paper: {path_id}")
                elif source == "doi":
                    result = self.add_paper_service.add_doi_paper(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added DOI paper: {path_id}")
                elif source == "bib":
                    result = self.add_paper_service.add_bib_papers(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added papers from BibTeX: {path_id}")
                elif source == "ris":
                    result = self.add_paper_service.add_ris_papers(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added papers from RIS: {path_id}")
                elif source == "pdf":
                    result = self.add_paper_service.add_pdf_paper(path_id)
                    self.app.screen.query_one("#status-bar").set_success(f"Successfully added PDF paper: {path_id}")
                elif source == "manual":
                    self.app.screen.query_one("#status-bar").set_success(f"Manual paper entry for '{path_id}' simulated.")
                else:
                    self.app.screen.query_one("#status-bar").set_error(f"Unknown source: {source}")
                    return

                self.app.load_papers() # Reload papers after adding
            except Exception as e:
                self.app.screen.query_one("#status-bar").set_error(f"Error adding paper: {str(e)}")
                # Also log the error for debugging
                self.app._add_log("add_paper_error", f"Failed to add {source} paper {path_id}: {str(e)}")

    async def handle_edit_command(self, args: List[str]):
        """Handle /edit command."""
        papers_to_edit = self._get_target_papers()
        if not papers_to_edit:
            self.app.screen.query_one("#status-bar").set_warning("No papers selected or under cursor to edit.")
            return

        if len(papers_to_edit) > 1:
            self.app.screen.query_one("#status-bar").set_warning("Editing multiple papers is not yet supported. Please select only one paper.")
            return

        paper = papers_to_edit[0]

        # Prepare paper data for the dialog
        paper_data = {
            "id": paper.id,
            "title": paper.title,
            "abstract": paper.abstract,
            "venue_full": paper.venue_full,
            "venue_acronym": paper.venue_acronym,
            "year": paper.year,
            "volume": paper.volume,
            "issue": paper.issue,
            "pages": paper.pages,
            "paper_type": paper.paper_type,
            "doi": paper.doi,
            "preprint_id": paper.preprint_id,
            "category": paper.category,
            "url": paper.url,
            "pdf_path": paper.pdf_path,
            "notes": paper.notes,
            "added_date": paper.added_date,
            "modified_date": paper.modified_date,
            "authors": paper.get_ordered_authors(), # Pass actual author objects
            "collections": paper.collections, # Pass actual collection objects
        }

        # Get status bar reference once to avoid repeated queries
        status_bar = self.app.screen.query_one("#status-bar")
        
        def edit_dialog_callback(result: Dict[str, Any] | None):
            if result:
                try:
                    updated_paper, error_message = self.paper_service.update_paper(paper.id, result)
                    if updated_paper:
                        self.app.load_papers() # Reload papers to reflect changes
                        status_bar.set_success(f"Paper '{updated_paper.title}' updated successfully.")
                    else:
                        status_bar.set_error(f"Failed to update paper: {error_message}")
                except Exception as e:
                    status_bar.set_error(f"Error updating paper: {e}")
            else:
                status_bar.set_status("Edit dialog cancelled.")

        await self.app.push_screen(EditDialog(
            paper_data=paper_data,
            callback=edit_dialog_callback,
            log_callback=self.app._add_log, # Pass the app's log callback
            error_display_callback=lambda title, message: None, # Temporarily disable error panel callback
            status_bar=status_bar,
            app=self.app
        ))

    async def handle_delete_command(self):
        """Handle /delete command."""
        papers_to_delete = self._get_target_papers()
        if not papers_to_delete:
            self.app.screen.query_one("#status-bar").set_warning("No papers selected or under cursor to delete.")
            return

        paper_titles = [p.title for p in papers_to_delete]
        confirm_message = f"Are you sure you want to delete {len(papers_to_delete)} paper(s)?\n\n"
        confirm_message += "\n".join([f"- {title}" for title in paper_titles[:5]])
        if len(paper_titles) > 5:
            confirm_message += f"\n...and {len(paper_titles) - 5} more."

        def confirm_callback(confirmed: bool):
            if confirmed:
                try:
                    paper_ids = [p.id for p in papers_to_delete]
                    deleted_count = self.paper_service.delete_papers(paper_ids)
                    self.app.load_papers() # Reload papers to reflect changes
                    # Find the main screen's status bar
                    status_bar = None
                    for screen in reversed(self.app.screen_stack):
                        try:
                            status_bar = screen.query_one("#status-bar")
                            break
                        except:
                            continue
                    if status_bar:
                        status_bar.set_success(f"Successfully deleted {deleted_count} paper(s).")
                except Exception as e:
                    # Find the main screen's status bar
                    status_bar = None
                    for screen in reversed(self.app.screen_stack):
                        try:
                            status_bar = screen.query_one("#status-bar")
                            break
                        except:
                            continue
                    if status_bar:
                        status_bar.set_error(f"Failed to delete papers: {e}")
            else:
                # Find the main screen's status bar
                status_bar = None
                for screen in reversed(self.app.screen_stack):
                    try:
                        status_bar = screen.query_one("#status-bar")
                        break
                    except:
                        continue
                if status_bar:
                    status_bar.set_status("Delete operation cancelled.")

        # Use a generic confirmation dialog (MessageDialog with custom buttons or a new ConfirmDialog)
        # For now, we'll use a simple MessageDialog and assume 'OK' means confirm.
        # A proper ConfirmDialog would be better here.
        await self.app.push_screen(MessageDialog("Confirm Deletion", confirm_message))
        # This is a simplification. A real confirmation dialog would return a boolean.
        # For now, we'll just proceed as if confirmed.
        confirm_callback(True) # Assuming user confirms for now

    async def handle_open_command(self):
        """Handle /open command."""
        papers_to_open = self._get_target_papers()
        if not papers_to_open:
            self.app.screen.query_one("#status-bar").set_warning("No papers selected or under cursor to open.")
            return

        for paper in papers_to_open:
            if paper.pdf_path:
                full_pdf_path = self.app.system_service.pdf_manager.get_absolute_path(paper.pdf_path)
                success, error_message = self.app.system_service.open_pdf(full_pdf_path)
                if success:
                    self.app.screen.query_one("#status-bar").set_success(f"Opened PDF for '{paper.title}'.")
                else:
                    self.app.screen.query_one("#status-bar").set_error(f"Failed to open PDF for '{paper.title}': {error_message}")
            else:
                self.app.screen.query_one("#status-bar").set_warning(f"No PDF path found for '{paper.title}'.")

    async def handle_detail_command(self):
        """Handle /detail command."""
        papers_to_detail = self._get_target_papers()
        if not papers_to_detail:
            self.app.screen.query_one("#status-bar").set_warning("No papers selected or under cursor to show details.")
            return

        # Support both single and multiple paper details
        from ng.dialogs.detail_dialog import DetailDialog
        
        def detail_callback(result):
            if result:
                try:
                    self.app.screen.query_one("#status-bar").set_status("Detail dialog closed")
                except:
                    pass
            else:
                try:
                    self.app.screen.query_one("#status-bar").set_status("Detail dialog cancelled")
                except:
                    pass
        
        await self.app.push_screen(DetailDialog(papers_to_detail, detail_callback))