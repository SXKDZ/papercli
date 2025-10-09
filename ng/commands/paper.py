from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List

from pluralizer import Pluralizer

from ng.commands import CommandHandler
from ng.db.models import Paper
from ng.dialogs import AddDialog, ConfirmDialog, DetailDialog, EditDialog
from ng.services import AddPaperService, PaperService, PDFService, validation
from ng.services.background import BackgroundOperationService
from ng.services.pdf import PDFDownloadHandler, PDFDownloadTaskFactory

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp

_pluralizer = Pluralizer()


class PaperCommandHandler(CommandHandler):
    """Handler for paper-related commands like add, edit, delete, open, detail."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.paper_service = PaperService(app=self.app)
        self.add_paper_service = AddPaperService(
            paper_service=self.paper_service,
            metadata_extractor=self.app.metadata_extractor,
            system_service=self.app.system_service,
            app=self.app,
        )
        self.background_service = BackgroundOperationService(self.app)
        self.pdf_service = PDFService(app=self.app)
        self.pdf_download_handler = PDFDownloadHandler(self.app, self.pdf_service)

    def _validate_input_for_source(self, source: str, path_id: str) -> bool:
        """Helper to validate input for a given source and show error if invalid."""
        is_valid, error_message = validation.validate_input(source, path_id)
        if not is_valid:
            self.app.notify(f"Validation Error: {error_message}", severity="error")
            return False
        return True

    def _handle_async_paper_with_pdf(
        self, source: str, path_id: str, add_method: callable
    ) -> bool:
        """Handle async paper addition with PDF download for sources like arXiv and OpenReview."""
        try:
            result = add_method(path_id)
            if result and result.get("paper"):
                paper = result["paper"]
                self.app.notify(
                    f"Added {source.title()} paper: {path_id}",
                    severity="information",
                )
                self.app.load_papers()  # Reload papers to show new entry

                # Start background PDF download
                download_task = PDFDownloadTaskFactory.create_download_task(
                    self.add_paper_service,
                    paper.id,
                    source,
                    path_id,
                    result["paper_data"],
                )

                completion_callback = (
                    self.pdf_download_handler.create_download_completion_callback(
                        path_id, source
                    )
                )

                self.background_service.run_operation(
                    download_task,
                    f"{source}_pdf_download_{path_id}",
                    f"Downloading PDF for {source.title()}: {path_id}...",
                    completion_callback,
                )
                return True
            else:
                self.app.notify(
                    f"Failed to add {source.title()} paper: {path_id} - No paper created",
                    severity="error",
                )
                return False
        except Exception as e:
            self.app.notify(
                f"Error processing {source.title()} paper {path_id}: {str(e)}",
                severity="error",
            )
            return False

    def _handle_sync_paper(
        self, source: str, path_id: str, add_method: callable
    ) -> bool:
        """Handle synchronous paper addition for sources like DBLP, DOI, etc."""
        try:
            add_method(path_id)
            self.app.notify(
                f"Successfully added {source.upper()} paper: {path_id}",
                severity="information",
            )
            return True
        except Exception as e:
            self.app.notify(f"Error adding paper: {str(e)}", severity="error")
            return False

    def _handle_async_pdf_paper(self, source: str, path_id: str) -> bool:
        """Handle async PDF paper addition with background metadata extraction."""
        try:
            result = self.add_paper_service.add_pdf_paper_async(path_id)
            if result and result.get("paper"):
                paper = result["paper"]
                self.app.notify(
                    f"Added PDF paper: {path_id}",
                    severity="information",
                )
                self.app.load_papers()  # Reload papers to show new entry

                # Start background metadata extraction
                extraction_task = (
                    PDFDownloadTaskFactory.create_metadata_extraction_task(
                        self.add_paper_service,
                        paper.id,
                        result["pdf_path"],
                    )
                )

                def metadata_completion_callback(extracted_result, error):
                    if error:
                        self.app.notify(
                            f"Failed to extract metadata from PDF: {error}",
                            severity="warning",
                        )
                        return

                    if not extracted_result or not extracted_result.get("success"):
                        error_msg = (
                            extracted_result.get("error", "Unknown error")
                            if extracted_result
                            else "Unknown error"
                        )
                        self.app.notify(
                            f"Failed to extract metadata from PDF: {error_msg}",
                            severity="warning",
                        )
                        return

                    # Success - metadata extracted and paper updated
                    self.app.notify(
                        f"PDF metadata extraction completed for: {path_id}",
                        severity="information",
                    )
                    self.app.load_papers()  # Reload to show updated metadata

                self.background_service.run_operation(
                    extraction_task,
                    f"pdf_metadata_extraction_{paper.id}",
                    f"Extracting metadata from PDF: {path_id}...",
                    metadata_completion_callback,
                )
                return True
            else:
                self.app.notify(
                    f"Failed to add PDF paper: {path_id} - No paper created",
                    severity="error",
                )
                return False
        except Exception as e:
            self.app.notify(
                f"Error processing PDF paper {path_id}: {str(e)}",
                severity="error",
            )
            return False

    def _add_paper_by_source(self, source: str, path_id: str) -> bool:
        """Consolidated method to add papers by source type."""
        source_lower = source.lower()
        if source_lower == "arxiv":
            return self._handle_async_paper_with_pdf(
                source_lower, path_id, self.add_paper_service.add_arxiv_paper_async
            )
        elif source_lower == "openreview":
            return self._handle_async_paper_with_pdf(
                source_lower, path_id, self.add_paper_service.add_openreview_paper_async
            )
        elif source_lower == "website":
            # Run website addition in background to avoid freezing the UI
            def operation():
                return self.add_paper_service.add_website_paper_async(path_id)

            def on_complete(result, error):
                if error:
                    self.app.notify(
                        f"Error adding website: {str(error)}", severity="error"
                    )
                    return
                if not result or not result.get("paper"):
                    self.app.notify(
                        f"Failed to add website: {path_id} - No paper created",
                        severity="error",
                    )
                    return
                paper = result["paper"]
                self.app.notify(
                    f"Successfully added website: {paper.title}",
                    severity="information",
                )
                self.app.load_papers()

            self.background_service.run_operation(
                operation,
                f"website_add_{path_id}",
                f"Adding website: {path_id}...",
                on_complete,
            )
            return True
        elif source_lower == "dblp":
            return self._handle_sync_paper(
                source_lower, path_id, self.add_paper_service.add_dblp_paper
            )
        elif source_lower == "doi":
            return self._handle_sync_paper(
                source_lower, path_id, self.add_paper_service.add_doi_paper
            )
        elif source_lower == "bib":
            return self._handle_sync_paper(
                source_lower, path_id, self.add_paper_service.add_bib_papers
            )
        elif source_lower == "ris":
            return self._handle_sync_paper(
                source_lower, path_id, self.add_paper_service.add_ris_papers
            )
        elif source_lower == "pdf":
            return self._handle_async_pdf_paper(source_lower, path_id)
        elif source_lower == "manual":
            try:
                self.add_paper_service.add_manual_paper(path_id or "")
                self.app.notify(
                    "Successfully added manual paper entry",
                    severity="information",
                )
                return True
            except Exception as e:
                self.app.notify(f"Error adding paper: {str(e)}", severity="error")
                return False
        else:
            self.app.notify(f"Unknown source: {source}", severity="error")
            return False

    def _handle_add_dialog_result(self, result: Dict[str, Any] | None):
        """Handle the result from the add dialog."""
        if not result:
            self.app.notify("Closed add dialog", severity="information")
            return

        source = result.get("source", "").strip()
        path_id = result.get("path_id", "").strip()

        if not source:
            self.app.notify("Source is required", severity="error")
            return

        # Use consolidated add method
        success = self._add_paper_by_source(source, path_id)
        if success:
            self.app.load_papers()  # Reload papers to reflect changes

    async def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        if not args:
            # Show the add dialog if no arguments are provided
            add_dialog = AddDialog(self._handle_add_dialog_result, self.app)
            await self.app.push_screen(add_dialog)
        else:
            # Handle direct add command: /add <source> [path_id]
            source = args[0].lower()
            path_id = args[1] if len(args) > 1 else None

            # Validate input first
            if not self._validate_input_for_source(source, path_id):
                return

            # Use consolidated add method
            success = self._add_paper_by_source(source, path_id)
            if success:
                self.app.load_papers()  # Reload papers to reflect changes

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

    async def handle_open_command(self, args: List[str] = None):
        """Handle /open command - opens HTML for websites, PDF for others."""
        papers_to_open = self._get_target_papers()
        if not papers_to_open:
            self.app.notify(
                "No papers selected or under cursor to open", severity="warning"
            )
            return

        for paper in papers_to_open:
            # For website papers, always open HTML (no PDF support)
            is_website = paper.paper_type == "website"
            has_pdf = bool(paper.pdf_path)
            has_html = bool(
                hasattr(paper, "html_snapshot_path") and paper.html_snapshot_path
            )

            # Website papers: always open HTML
            if is_website:
                if has_html:
                    await self._open_html_file(paper)
                else:
                    self.app.notify(
                        f"No HTML snapshot available for '{paper.title}'",
                        severity="warning",
                    )
            # Non-website papers: open PDF
            elif has_pdf:
                await self._open_pdf_file(paper)
            else:
                self.app.notify(
                    f"No file available to open for '{paper.title}'",
                    severity="warning",
                )

    async def _open_pdf_file(self, paper: Paper):
        """Open PDF file for a paper."""
        full_pdf_path = self.app.system_service.pdf_manager.get_absolute_path(
            paper.pdf_path
        )
        success, error_message = self.app.system_service.open_pdf(full_pdf_path)
        if success:
            self.app.notify(f"Opened PDF for '{paper.title}'", severity="information")
        else:
            self.app.notify(
                f"Failed to open PDF for '{paper.title}': {error_message}",
                severity="error",
            )

    async def _open_html_file(self, paper: Paper):
        """Open HTML snapshot file for a paper."""
        import os
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = os.path.dirname(db_manager.db_path)
        html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
        html_absolute_path = os.path.join(html_snapshot_dir, paper.html_snapshot_path)

        success, error_message = self.app.system_service.open_file(
            html_absolute_path, "HTML snapshot"
        )
        if success:
            self.app.notify(
                f"Opened HTML snapshot for '{paper.title}'", severity="information"
            )
        else:
            self.app.notify(
                f"Failed to open HTML snapshot for '{paper.title}': {error_message}",
                severity="error",
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
