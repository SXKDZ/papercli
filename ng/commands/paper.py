from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from pluralizer import Pluralizer

from ng.commands import CommandHandler
from ng.db.models import Paper
from ng.dialogs import AddDialog, ConfirmDialog, DetailDialog, EditDialog
from ng.services import AddPaperService, PaperService, PDFService, ValidationService
from ng.services.background import BackgroundOperationService

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp

_pluralizer = Pluralizer()


class PaperCommandHandler(CommandHandler):
    """Handler for paper-related commands like add, edit, delete, open, detail."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.paper_service = PaperService()
        self.add_paper_service = AddPaperService(
            paper_service=self.paper_service,
            metadata_extractor=self.app.metadata_extractor,  # Assuming metadata_extractor is on app
            system_service=self.app.system_service,  # Assuming system_service is on app
            app=self.app,
        )
        self.background_service = BackgroundOperationService(self.app)

    def _get_target_papers(self) -> List[Paper]:
        """Helper to get selected papers from the main app's paper list."""
        return self.app.screen.query_one("#paper-list-view").get_selected_papers()

    def _validate_input_for_source(self, source: str, path_id: str) -> bool:
        """Helper to validate input for a given source and show error if invalid."""
        is_valid, error_message = ValidationService.validate_input(source, path_id)
        if not is_valid:
            self.app.notify(f"Validation Error: {error_message}", severity="error")
            return False
        return True

    async def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        if not args:
            # Show the add dialog if no arguments are provided
            def add_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    source = result.get("source", "").strip()
                    path_id = result.get("path_id", "").strip()

                    if not source:
                        self.app.notify("Source is required", severity="error")
                        return

                    # Determine the type of source and call appropriate add command
                    try:

                        if source.lower() == "arxiv":
                            # Use async approach: add paper first, then download PDF in background
                            try:
                                result = self.add_paper_service.add_arxiv_paper_async(
                                    path_id
                                )
                                if result and result.get("paper"):
                                    paper = result["paper"]
                                    self.app.notify(
                                        f"Added arXiv paper: {path_id}",
                                        severity="information",
                                    )
                                    self.app.load_papers()  # Reload papers to show new entry

                                    # Start background PDF download
                                    def pdf_download_task():
                                        return self.add_paper_service.download_and_update_pdf(
                                            paper.id,
                                            "arxiv",
                                            path_id,
                                            result["paper_data"],
                                        )

                                    def on_pdf_complete(download_result, error):
                                        if error:
                                            self.app.notify(
                                                f"PDF download failed for {path_id}: {error}",
                                                severity="error",
                                            )
                                        elif download_result and download_result.get(
                                            "success"
                                        ):
                                            try:
                                                pdf_service = PDFService(app=self.app)
                                                pdf_path = download_result.get(
                                                    "pdf_path", ""
                                                )
                                                download_duration = download_result.get(
                                                    "download_duration", 0.0
                                                )
                                                if pdf_path and download_duration > 0:
                                                    import os

                                                    from ng.db.database import (
                                                        get_pdf_directory,
                                                    )

                                                    pdf_dir = get_pdf_directory()
                                                    abs_pdf_path = os.path.join(
                                                        pdf_dir, pdf_path
                                                    )
                                                    summary = pdf_service.create_download_summary(
                                                        abs_pdf_path,
                                                        download_duration,
                                                    )
                                                    self.app.notify(
                                                        f"arXiv PDF {path_id}: {summary}",
                                                        severity="information",
                                                    )
                                                else:
                                                    self.app.notify(
                                                        f"PDF downloaded for arXiv: {path_id}",
                                                        severity="information",
                                                    )
                                            except Exception:

                                                self.app.notify(
                                                    f"PDF downloaded for arXiv: {path_id}",
                                                    severity="information",
                                                )
                                            self.app.load_papers()  # Reload to show PDF indicator
                                        else:
                                            error_msg = (
                                                download_result.get(
                                                    "error", "Unknown error"
                                                )
                                                if download_result
                                                else "Unknown error"
                                            )
                                            self.app.notify(
                                                f"PDF download failed for {path_id}: {error_msg}",
                                                severity="warning",
                                            )

                                    self.background_service.run_operation(
                                        pdf_download_task,
                                        f"arxiv_pdf_download_{path_id}",
                                        f"Downloading PDF for arXiv: {path_id}...",
                                        on_pdf_complete,
                                    )
                                else:
                                    self.app.notify(
                                        f"Failed to add arXiv paper: {path_id} - No paper created",
                                        severity="error",
                                    )
                            except Exception as e:
                                self.app.notify(
                                    f"Error processing arXiv paper {path_id}: {str(e)}",
                                    severity="error",
                                )
                        elif source.lower() == "dblp":
                            result = self.add_paper_service.add_dblp_paper(path_id)
                            self.app.notify(
                                f"Successfully added DBLP paper: {path_id}",
                                severity="information",
                            )
                        elif source.lower() == "openreview":
                            # Use async approach: add paper first, then download PDF in background
                            try:
                                result = (
                                    self.add_paper_service.add_openreview_paper_async(
                                        path_id
                                    )
                                )
                                if result and result.get("paper"):
                                    paper = result["paper"]
                                    self.app.notify(
                                        f"Added OpenReview paper: {path_id}",
                                        severity="information",
                                    )
                                    self.app.load_papers()  # Reload papers to show new entry

                                    # Start background PDF download
                                    def pdf_download_task():
                                        return self.add_paper_service.download_and_update_pdf(
                                            paper.id,
                                            "openreview",
                                            path_id,
                                            result["paper_data"],
                                        )

                                    def on_pdf_complete(download_result, error):
                                        if error:
                                            self.app.notify(
                                                f"PDF download failed for {path_id}: {error}",
                                                severity="error",
                                            )
                                        elif download_result and download_result.get(
                                            "success"
                                        ):
                                            # Use PDFService to create detailed download summary for OpenReview
                                            try:
                                                from ng.services.pdf import PDFService

                                                pdf_service = PDFService(app=self.app)
                                                pdf_path = download_result.get(
                                                    "pdf_path", ""
                                                )
                                                download_duration = download_result.get(
                                                    "download_duration", 0.0
                                                )
                                                if pdf_path and download_duration > 0:
                                                    import os

                                                    from ng.db.database import (
                                                        get_pdf_directory,
                                                    )

                                                    pdf_dir = get_pdf_directory()
                                                    abs_pdf_path = os.path.join(
                                                        pdf_dir, pdf_path
                                                    )
                                                    summary = pdf_service.create_download_summary(
                                                        abs_pdf_path,
                                                        download_duration,
                                                    )
                                                    self.app.notify(
                                                        f"OpenReview PDF {path_id}: {summary}",
                                                        severity="information",
                                                    )
                                                else:
                                                    self.app.notify(
                                                        f"PDF downloaded for OpenReview: {path_id}",
                                                        severity="information",
                                                    )
                                            except Exception:
                                                self.app.notify(
                                                    f"PDF downloaded for OpenReview: {path_id}",
                                                    severity="information",
                                                )
                                            self.app.load_papers()  # Reload to show PDF indicator
                                        else:
                                            error_msg = (
                                                download_result.get(
                                                    "error", "Unknown error"
                                                )
                                                if download_result
                                                else "Unknown error"
                                            )
                                            self.app.notify(
                                                f"PDF download failed for {path_id}: {error_msg}",
                                                severity="warning",
                                            )

                                    self.background_service.run_operation(
                                        pdf_download_task,
                                        f"openreview_pdf_download_{path_id}",
                                        f"Downloading PDF for OpenReview: {path_id}...",
                                        on_pdf_complete,
                                    )
                                else:
                                    self.app.notify(
                                        f"Failed to add OpenReview paper: {path_id} - No paper created",
                                        severity="error",
                                    )
                            except Exception as e:
                                self.app.notify(
                                    f"Error processing OpenReview paper {path_id}: {str(e)}",
                                    severity="error",
                                )
                        elif source.lower() == "doi":
                            result = self.add_paper_service.add_doi_paper(path_id)
                            self.app.notify(
                                f"Successfully added DOI paper: {path_id}",
                                severity="information",
                            )
                        elif source.lower() == "bib":
                            result = self.add_paper_service.add_bib_papers(path_id)
                            self.app.notify(
                                f"Successfully added papers from BibTeX: {path_id}",
                                severity="information",
                            )
                        elif source.lower() == "ris":
                            result = self.add_paper_service.add_ris_papers(path_id)
                            self.app.notify(
                                f"Successfully added papers from RIS: {path_id}",
                                severity="information",
                            )
                        elif source.lower() == "pdf":
                            result = self.add_paper_service.add_pdf_paper(path_id)
                            self.app.notify(
                                f"Successfully added PDF paper: {path_id}",
                                severity="information",
                            )
                        elif source.lower() == "manual":
                            # Manual entry opens the add dialog with manual mode
                            result = self.add_paper_service.add_manual_paper(
                                path_id or ""
                            )
                            self.app.notify(
                                "Successfully added manual paper entry",
                                severity="information",
                            )
                        else:
                            self.app.notify(
                                f"Unknown source: {source}", severity="error"
                            )
                            return

                    except Exception as e:
                        self.app.notify(
                            f"Error adding paper: {str(e)}", severity="error"
                        )
                        # Also log the error for debugging
                        self.app._add_log(
                            "add_paper_error",
                            f"Failed to add {source} paper {path_id}: {str(e)}",
                        )
                else:
                    # Dialog was cancelled
                    self.app.notify("Closed add dialog", severity="information")

            add_dialog = AddDialog(add_dialog_callback, self.app)
            await self.app.push_screen(add_dialog)
        else:
            # Handle direct add command: /add <source> [path_id]
            source = args[0].lower()
            path_id = args[1] if len(args) > 1 else None

            try:
                # Validate input first
                if not self._validate_input_for_source(source, path_id):
                    return

                if source == "arxiv":
                    # Use async approach: add paper first, then download PDF in background
                    result = self.add_paper_service.add_arxiv_paper_async(path_id)
                    if result and result.get("paper"):
                        paper = result["paper"]
                        self.app.notify(
                            f"Added arXiv paper: {path_id}",
                            severity="information",
                        )
                        self.app.load_papers()  # Reload papers to show new entry

                        # Start background PDF download
                        def pdf_download_task():
                            return self.add_paper_service.download_and_update_pdf(
                                paper.id, "arxiv", path_id, result["paper_data"]
                            )

                        def on_pdf_complete(download_result, error):
                            if error:
                                self.app.notify(
                                    f"PDF download failed for {path_id}: {error}",
                                    severity="error",
                                )
                            elif download_result and download_result.get("success"):
                                self.app.notify(
                                    f"PDF downloaded for: {path_id}",
                                    severity="information",
                                )
                                self.app.load_papers()  # Reload to show PDF indicator
                            else:
                                error_msg = (
                                    download_result.get("error", "Unknown error")
                                    if download_result
                                    else "Unknown error"
                                )
                                self.app.notify(
                                    f"PDF download failed for {path_id}: {error_msg}",
                                    severity="warning",
                                )

                        self.background_service.run_operation(
                            pdf_download_task,
                            f"arxiv_pdf_download_{path_id}",
                            f"Downloading PDF for arXiv: {path_id}...",
                            on_pdf_complete,
                        )
                    else:
                        self.app.notify(
                            f"Failed to add arXiv paper: {path_id} - No paper created",
                            severity="error",
                        )
                elif source == "dblp":
                    result = self.add_paper_service.add_dblp_paper(path_id)
                    self.app.notify(
                        f"Successfully added DBLP paper: {path_id}",
                        severity="information",
                    )
                elif source == "openreview":
                    # Use async approach: add paper first, then download PDF in background
                    result = self.add_paper_service.add_openreview_paper_async(path_id)
                    if result and result.get("paper"):
                        paper = result["paper"]
                        self.app.notify(
                            f"Added OpenReview paper: {path_id}",
                            severity="information",
                        )
                        self.app.load_papers()  # Reload papers to show new entry

                        # Start background PDF download
                        def pdf_download_task():
                            return self.add_paper_service.download_and_update_pdf(
                                paper.id, "openreview", path_id, result["paper_data"]
                            )

                        def on_pdf_complete(download_result, error):
                            if error:
                                self.app.notify(
                                    f"PDF download failed for {path_id}: {error}",
                                    severity="error",
                                )
                            elif download_result and download_result.get("success"):
                                self.app.notify(
                                    f"PDF downloaded for: {path_id}",
                                    severity="information",
                                )
                                self.app.load_papers()  # Reload to show PDF indicator
                            else:
                                error_msg = (
                                    download_result.get("error", "Unknown error")
                                    if download_result
                                    else "Unknown error"
                                )
                                self.app.notify(
                                    f"PDF download failed for {path_id}: {error_msg}",
                                    severity="warning",
                                )

                        self.background_service.run_operation(
                            pdf_download_task,
                            f"openreview_pdf_download_{path_id}",
                            f"Downloading PDF for OpenReview: {path_id}...",
                            on_pdf_complete,
                        )
                    else:
                        self.app.notify(
                            f"Failed to add OpenReview paper: {path_id} - No paper created",
                            severity="error",
                        )
                elif source == "doi":
                    result = self.add_paper_service.add_doi_paper(path_id)
                    self.app.notify(
                        f"Successfully added DOI paper: {path_id}",
                        severity="information",
                    )
                elif source == "bib":
                    result = self.add_paper_service.add_bib_papers(path_id)
                    self.app.notify(
                        f"Successfully added papers from BibTeX: {path_id}",
                        severity="information",
                    )
                elif source == "ris":
                    result = self.add_paper_service.add_ris_papers(path_id)
                    self.app.notify(
                        f"Successfully added papers from RIS: {path_id}",
                        severity="information",
                    )
                elif source == "pdf":
                    result = self.add_paper_service.add_pdf_paper(path_id)
                    self.app.notify(
                        f"Successfully added PDF paper: {path_id}",
                        severity="information",
                    )
                elif source == "manual":
                    result = self.add_paper_service.add_manual_paper(path_id or "")
                    self.app.notify(
                        "Successfully added manual paper entry",
                        severity="information",
                    )
                else:
                    self.app.notify(f"Unknown source: {source}", severity="error")
                    return

            except Exception as e:
                self.app.notify(f"Error adding paper: {str(e)}", severity="error")
                # Also log the error for debugging
                self.app._add_log(
                    "add_paper_error",
                    f"Failed to add {source} paper {path_id}: {str(e)}",
                )

    async def handle_edit_command(self, args: List[str]):
        """Handle /edit command."""
        papers_to_edit = self._get_target_papers()
        if not papers_to_edit:
            self.app.notify(
                "No papers selected or under cursor to edit", severity="warning"
            )
            return

        if len(papers_to_edit) > 1:
            self.app.notify(
                (
                    "Editing multiple papers is not yet supported. "
                    "Please select only one paper"
                ),
                severity="warning",
            )
            return

        paper = papers_to_edit[0]

        # Prepare paper data for the dialog using PaperService method
        paper_data = self.paper_service.prepare_paper_data_for_edit(paper)

        # Use PaperService edit callback method
        edit_dialog_callback = self.paper_service.create_edit_callback(
            self.app, paper.id
        )

        await self.app.push_screen(
            EditDialog(
                paper_data=paper_data,
                callback=edit_dialog_callback,
                error_display_callback=lambda title, message: None,  # Temporarily disable error panel callback
                app=self.app,
            )
        )

    async def handle_delete_command(self):
        """Handle /delete command."""
        papers_to_delete = self._get_target_papers()
        if not papers_to_delete:
            self.app.notify(
                "No papers selected or under cursor to delete", severity="warning"
            )
            return

        paper_titles = [p.title for p in papers_to_delete]
        pluralized_papers = _pluralizer.pluralize("paper", len(papers_to_delete), True)
        confirm_message = f"Are you sure you want to delete {pluralized_papers}?\n\n"
        confirm_message += "\n".join([f"- {title}" for title in paper_titles[:5]])
        if len(paper_titles) > 5:
            confirm_message += f"\n...and {len(paper_titles) - 5} more."

        def confirm_callback(confirmed: bool):
            if confirmed:
                try:
                    paper_ids = [p.id for p in papers_to_delete]
                    deleted_count = self.paper_service.delete_papers(paper_ids)
                    self.app.load_papers()  # Reload papers to reflect changes
                    self.app.notify(
                        f"Successfully deleted {_pluralizer.pluralize('paper', deleted_count, True)}",
                        severity="information",
                    )
                except Exception as e:
                    self.app.notify(f"Failed to delete papers: {e}", severity="error")

        # Use the proper confirmation dialog
        await self.app.push_screen(
            ConfirmDialog("Confirm Deletion", confirm_message, confirm_callback)
        )

    async def handle_open_command(self):
        """Handle /open command."""
        papers_to_open = self._get_target_papers()
        if not papers_to_open:
            self.app.notify(
                "No papers selected or under cursor to open", severity="warning"
            )
            return

        for paper in papers_to_open:
            if paper.pdf_path:
                full_pdf_path = self.app.system_service.pdf_manager.get_absolute_path(
                    paper.pdf_path
                )
                success, error_message = self.app.system_service.open_pdf(full_pdf_path)
                if success:
                    self.app.notify(
                        f"Opened PDF for '{paper.title}'", severity="information"
                    )
                else:
                    self.app.notify(
                        (
                            f"Failed to open PDF for '{paper.title}': "
                            f"{error_message}"
                        ),
                        severity="error",
                    )
            else:
                self.app.notify(
                    f"No PDF path found for '{paper.title}'", severity="warning"
                )

    async def handle_detail_command(self):
        """Handle /detail command."""
        papers_to_detail = self._get_target_papers()
        if not papers_to_detail:
            self.app.notify(
                "No papers selected or under cursor to show details",
                severity="warning",
            )
            return

        # Show details for the first selected paper (or current paper under cursor)
        paper_to_show = papers_to_detail[0]  # Take the first paper
        await self.app.push_screen(DetailDialog(paper_to_show, None))
