"""Paper management commands handler."""

import os
import traceback
from typing import List

from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.containers import Float
from prompt_toolkit.widgets import Button
from prompt_toolkit.widgets import Dialog
from prompt_toolkit.widgets import Label

from ...dialogs import EditDialog
from ...services import LLMSummaryService
from ...services import PDFMetadataExtractionService
from ...services import normalize_paper_data
from .base import BaseCommandHandler


class PaperCommandHandler(BaseCommandHandler):
    """Handler for paper management commands like add, edit, delete, open, detail."""

    def handle_add_command(self, args: List[str]):
        """Handle /add command."""
        try:
            # Simple command-line based add
            if len(args) > 0:
                # Quick add from command line arguments
                if args[0] == "arxiv" and len(args) > 1:
                    self._add_arxiv_paper(args[1])
                elif args[0] == "dblp" and len(args) > 1:
                    self._add_dblp_paper(
                        " ".join(args[1:])
                    )  # Support URLs with parameters
                elif args[0] == "openreview" and len(args) > 1:
                    self._add_openreview_paper(args[1])
                elif args[0] == "doi" and len(args) > 1:
                    self._add_doi_paper(" ".join(args[1:]))
                elif args[0] == "pdf" and len(args) > 1:
                    self._add_pdf_paper(" ".join(args[1:]))
                elif args[0] == "bib" and len(args) > 1:
                    self._add_bib_papers(" ".join(args[1:]))
                elif args[0] == "ris" and len(args) > 1:
                    self._add_ris_papers(" ".join(args[1:]))
                elif args[0] == "manual":
                    self._add_manual_paper()
                else:
                    self.cli.status_bar.set_status(
                        "Usage: /add [arxiv <id>|dblp <url>|openreview <id>|doi <doi>|pdf <path>|bib <path>|ris <path>|manual]",
                        "info",
                    )
            else:
                # Open add dialog when no arguments provided
                self.cli.show_add_dialog()

        except Exception as e:
            self.cli.status_bar.set_error(f"Error adding paper: {e}")

    def handle_edit_command(self, args: List[str] = None):
        """Handle /edit command."""
        papers_to_update = self._get_target_papers()
        if not papers_to_update:
            return

        try:
            # Handle extract-pdf subcommand
            if args and len(args) == 1 and args[0].lower() == "extract-pdf":
                self._handle_extract_pdf_command(papers_to_update)
                return

            # Handle summarize subcommand
            if args and len(args) == 1 and args[0].lower() == "summarize":
                self._handle_summarize_command(papers_to_update)
                return

            # Parse command line arguments for quick update
            if args and len(args) >= 2:
                # Quick update: /edit field value
                field = args[0].lower()
                value = " ".join(args[1:])  # Support values with spaces

                # Extended field list for comprehensive updating
                valid_fields = [
                    "title",
                    "abstract",
                    "notes",
                    "venue_full",
                    "venue_acronym",
                    "year",
                    "paper_type",
                    "doi",
                    "pages",
                    "preprint_id",
                    "url",
                    "category",
                ]
                if field not in valid_fields:
                    self.cli.status_bar.set_error(
                        f"Usage: /edit [field] <value>. Valid fields: title, abstract, etc."
                    )
                    return

                # Convert year to int if needed
                if field == "year":
                    try:
                        value = int(value)
                    except ValueError:
                        self.cli.status_bar.set_error("Year must be a number")
                        return

                # Apply normalization to the update
                temp_data = {field: value}
                normalized_data = normalize_paper_data(temp_data)
                normalized_value = normalized_data.get(field, value)

                updates = {field: normalized_value}
                self.cli.status_bar.set_status(
                    f"Updating {len(papers_to_update)} paper(s)...", "edit"
                )

                # Update papers
                updated_count = 0
                for paper in papers_to_update:
                    try:
                        # Log before and after
                        old_value = getattr(paper, field)
                        updated_paper, error = self.cli.paper_service.update_paper(
                            paper.id, updates
                        )
                        if error:
                            self.cli.status_bar.set_error(f"Update error: {error}")
                            continue
                        self._add_log(
                            "edit",
                            f"Updated '{field}' for paper '{paper.title}'. From '{old_value}' to '{value}'",
                        )
                        updated_count += 1

                        # Trigger auto-sync if enabled
                        self.cli.trigger_auto_sync_if_enabled()
                    except Exception as e:
                        self.cli.status_bar.set_error(
                            f"Error updating paper {paper.id}: {e}"
                        )
                        break  # Show only first error

                if updated_count > 0:
                    self.load_papers()
                    self.cli.status_bar.set_success(
                        f"Updated '{field}' for {updated_count} paper(s)"
                    )

            else:
                # Use enhanced edit dialog for all cases
                self._show_edit_dialog(papers_to_update)

        except Exception as e:
            self.show_error_panel_with_message(
                "Update Error", f"Failed to update papers\n\n{traceback.format_exc()}"
            )

    def handle_delete_command(self):
        """Handle /delete command."""
        papers_to_delete = self._get_target_papers()
        if not papers_to_delete:
            return

        future = self.cli.app.loop.create_future()
        future.add_done_callback(
            lambda future: self.cli.app.layout.container.floats.pop()
        )

        def perform_delete():
            future.set_result(None)
            try:
                paper_ids = [paper.id for paper in papers_to_delete]
                paper_titles = [paper.title for paper in papers_to_delete]
                deleted_count = self.cli.paper_service.delete_papers(paper_ids)
                self.load_papers()
                self._add_log(
                    "delete",
                    f"Deleted {deleted_count} paper(s): {', '.join(paper_titles)}",
                )
                self.cli.status_bar.set_success(f"Deleted {deleted_count} papers")
            except Exception as e:
                self.cli.status_bar.set_error(f"Error during deletion: {e}")

            self.cli.app.invalidate()

        def cancel_delete():
            future.set_result(None)
            self.cli.status_bar.set_error("Deletion cancelled")
            self.cli.app.invalidate()

        paper_titles = [
            paper.title[:70] + "..." if len(paper.title) > 70 else paper.title
            for paper in papers_to_delete
        ]
        dialog_text = (
            f"Are you sure you want to delete {len(papers_to_delete)} paper{'s' if len(papers_to_delete) != 1 else ''}?\n\n"
            + "\n".join(f"• {title}" for title in paper_titles[:5])
            + (
                f"\n... and {len(paper_titles) - 5} more"
                if len(paper_titles) > 5
                else ""
            )
        )

        # Create handlers that clean up properly
        def cleanup_delete():
            if hasattr(self.cli, "_delete_dialog_active"):
                self.cli._delete_dialog_active = False
            perform_delete()

        def cleanup_cancel():
            if hasattr(self.cli, "_delete_dialog_active"):
                self.cli._delete_dialog_active = False
            cancel_delete()

        confirmation_dialog = Dialog(
            title="Confirm Deletion",
            body=Label(text=dialog_text, dont_extend_height=False, wrap_lines=True),
            buttons=[
                Button(text="Yes", handler=cleanup_delete),
                Button(text="No", handler=cleanup_cancel),
            ],
            with_background=False,
            width=80,
        )

        # Create a flag to track if dialog is active
        self.cli._delete_dialog_active = True

        # Add key binding for ESC to default to "No"
        @self.cli.kb.add(
            "escape",
            filter=Condition(lambda: getattr(self.cli, "_delete_dialog_active", False)),
        )
        def _(event):
            self.cli._delete_dialog_active = False
            cancel_delete()

        dialog_float = Float(content=confirmation_dialog)
        self.cli.app.layout.container.floats.append(dialog_float)
        self.cli.app.layout.focus(confirmation_dialog)
        self.cli.app.invalidate()

    def handle_open_command(self):
        """Handle /open command."""
        papers_to_open = self._get_target_papers()
        if not papers_to_open:
            return

        try:
            opened_count = 0
            for paper in papers_to_open:
                if paper.pdf_path:
                    # Resolve PDF path against data directory if it's relative
                    pdf_path = paper.pdf_path
                    if not os.path.isabs(pdf_path):
                        # Get data directory from CLI's db_path
                        data_dir = os.path.dirname(self.cli.db_path)
                        # Always put PDFs in the pdfs/ subdirectory
                        pdf_path = os.path.join(data_dir, "pdfs", pdf_path)

                    success, error_msg = self.cli.system_service.open_pdf(pdf_path)
                    if success:
                        opened_count += 1
                    else:
                        # Show detailed error in error panel instead of just status bar
                        self.show_error_panel_with_message(
                            "PDF Viewer Error",
                            f"Failed to open PDF for: {paper.title}\n\n{error_msg}",
                        )
                        break  # Show only first error
                else:
                    self.cli.status_bar.set_warning(
                        f"No PDF available for: {paper.title}"
                    )
                    break

            if opened_count > 0:
                self.cli.status_bar.set_success(f"Opened {opened_count} PDF(s)")
            elif opened_count == 0 and len(papers_to_open) > 1:
                self.cli.status_bar.set_error(
                    "No PDFs found to open for the selected paper(s)"
                )

        except Exception as e:
            self.cli.status_bar.set_error(f"Error opening PDFs: {e}")

    def handle_detail_command(self):
        """Handle /detail command."""
        papers_to_show = self._get_target_papers()
        if not papers_to_show:
            return

        try:
            details_text = self._format_paper_details(papers_to_show)

            # Update buffer content correctly by bypassing the read-only flag
            doc = Document(details_text, 0)
            self.cli.details_buffer.set_document(doc, bypass_readonly=True)

            self.cli.show_details_panel = True
            self.cli.app.layout.focus(self.cli.details_control)
            self.cli.status_bar.set_status("Details panel opened - Press ESC to close")
        except Exception as e:
            self.show_error_panel_with_message(
                "Detail View Error",
                f"Could not display paper details.\n\n{traceback.format_exc()}",
            )

    def _add_arxiv_paper(self, arxiv_id: str):
        """Add a paper from arXiv using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_arxiv_paper(arxiv_id)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add arXiv Paper Error",
                    f"Failed to add arXiv paper: {arxiv_id}\n\n{error}",
                )
                return

            paper = result["paper"]
            pdf_path = result["pdf_path"]
            pdf_error = result["pdf_error"]

            if pdf_path:
                self._add_log("add_arxiv", f"PDF download successful: {pdf_path}")
                try:
                    updated_paper, update_error = self.cli.paper_service.update_paper(
                        paper.id, {"pdf_path": pdf_path}
                    )
                    if updated_paper:
                        self._add_log(
                            "add_arxiv", f"Database updated with PDF path: {pdf_path}"
                        )
                        # Trigger auto-sync if enabled
                        self.cli.trigger_auto_sync_if_enabled()
                    else:
                        self._add_log(
                            "add_arxiv",
                            f"Failed to update paper PDF path: {update_error}",
                        )
                except Exception as e:
                    self._add_log("add_arxiv", f"Error updating paper PDF path: {e}")
            elif pdf_error:
                self._add_log("add_arxiv", f"PDF download failed: {pdf_error}")

            self._add_log("add_arxiv", f"Added arXiv paper '{paper.title}'")
            self.load_papers()
            self.cli.status_bar.set_status(f"Added arXiv paper: {paper.title}", "add")

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_arxiv",
            initial_message=f"Fetching arXiv paper {arxiv_id}...",
            on_complete=on_complete,
        )

    def _add_dblp_paper(self, dblp_url: str):
        """Add a paper from DBLP using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_dblp_paper(dblp_url)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add DBLP Paper Error",
                    f"Failed to add DBLP paper: {dblp_url}\n\n{error}",
                )
                return

            paper = result["paper"]
            self._add_log("add_dblp", f"Added DBLP paper '{paper.title}'")
            self.load_papers()
            self.cli.status_bar.set_status(f"Added DBLP paper: {paper.title}", "add")

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_dblp",
            initial_message=f"Fetching DBLP paper from {dblp_url}...",
            on_complete=on_complete,
        )

    def _add_openreview_paper(self, openreview_id: str):
        """Add a paper from OpenReview using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_openreview_paper(openreview_id)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add OpenReview Paper Error",
                    f"Failed to add OpenReview paper: {openreview_id}\n\n{error}",
                )
                return

            paper = result["paper"]
            pdf_path = result["pdf_path"]
            pdf_error = result["pdf_error"]

            if pdf_path:
                self._add_log("add_openreview", f"PDF download successful: {pdf_path}")
                try:
                    updated_paper, update_error = self.cli.paper_service.update_paper(
                        paper.id, {"pdf_path": pdf_path}
                    )
                    if updated_paper:
                        self._add_log(
                            "add_openreview",
                            f"Database updated with PDF path: {pdf_path}",
                        )
                        # Trigger auto-sync if enabled
                        self.cli.trigger_auto_sync_if_enabled()
                    else:
                        self._add_log(
                            "add_openreview",
                            f"Failed to update paper PDF path: {update_error}",
                        )
                except Exception as e:
                    self._add_log(
                        "add_openreview", f"Error updating paper PDF path: {e}"
                    )
            elif pdf_error:
                self._add_log("add_openreview", f"PDF download failed: {pdf_error}")

            self._add_log("add_openreview", f"Added OpenReview paper '{paper.title}'")
            self.load_papers()
            self.cli.status_bar.set_status(
                f"Added OpenReview paper: {paper.title}", "add"
            )

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_openreview",
            initial_message=f"Fetching OpenReview paper {openreview_id}...",
            on_complete=on_complete,
        )

    def _add_doi_paper(self, doi: str):
        """Add a paper from DOI using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_doi_paper(doi)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add DOI Paper Error",
                    f"Failed to add DOI paper: {doi}\n\n{error}",
                )
                return

            paper = result["paper"]
            self._add_log("add_doi", f"Added DOI paper '{paper.title}'")
            self.load_papers()
            self.cli.status_bar.set_status(f"Added DOI paper: {paper.title}", "add")

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_doi",
            initial_message=f"Fetching DOI paper {doi}...",
            on_complete=on_complete,
        )

    def _add_pdf_paper(self, pdf_path: str):
        """Add a paper from PDF using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_pdf_paper(pdf_path)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add PDF Paper Error",
                    f"Failed to add PDF paper: {pdf_path}\n\n{error}",
                )
                return

            paper = result["paper"]
            self._add_log("add_pdf", f"Added PDF paper '{paper.title}' from {pdf_path}")
            self.load_papers()
            self.cli.status_bar.set_status(f"Added PDF paper: {paper.title}", "add")

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_pdf",
            initial_message=f"Processing PDF {pdf_path}...",
            on_complete=on_complete,
        )

    def _add_bib_papers(self, bib_path: str):
        """Add papers from BibTeX file using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_bib_papers(bib_path)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add BibTeX Papers Error",
                    f"Failed to process BibTeX file: {bib_path}\n\n{error}",
                )
                return

            papers, errors = result
            success_count = len(papers)
            error_count = len(errors)

            # Log results
            if success_count > 0:
                paper_titles = [p.title for p in papers[:3]]  # Show first 3 titles
                if success_count > 3:
                    paper_titles.append(f"and {success_count - 3} more...")
                titles_str = ", ".join(paper_titles)
                self._add_log("add_bib", f"Added {success_count} papers: {titles_str}")

            if error_count > 0:
                self._add_log("add_bib", f"Errors: {error_count} papers failed to add")
                for error in errors[:5]:  # Show first 5 errors
                    self._add_log("add_bib", f"  {error}")
                if error_count > 5:
                    self._add_log("add_bib", f"  ... and {error_count - 5} more errors")

            self.load_papers()

            # Set status message
            if success_count > 0 and error_count == 0:
                self.cli.status_bar.set_status(
                    f"Added {success_count} papers from BibTeX file", "add"
                )
            elif success_count > 0 and error_count > 0:
                self.cli.status_bar.set_status(
                    f"Added {success_count} papers, {error_count} failed", "edit"
                )
            else:
                self.cli.status_bar.set_status(
                    f"Failed to add papers from BibTeX file", "error"
                )

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_bib",
            initial_message=f"Processing BibTeX file {bib_path}...",
            on_complete=on_complete,
        )

    def _add_ris_papers(self, ris_path: str):
        """Add papers from RIS file using the add paper service."""

        def complete_operation():
            return self.cli.add_paper_service.add_ris_papers(ris_path)

        def on_complete(result, error):
            if error:
                self.show_error_panel_with_message(
                    "Add RIS Papers Error",
                    f"Failed to process RIS file: {ris_path}\n\n{error}",
                )
                return

            papers, errors = result
            success_count = len(papers)
            error_count = len(errors)

            # Log results
            if success_count > 0:
                paper_titles = [p.title for p in papers[:3]]  # Show first 3 titles
                if success_count > 3:
                    paper_titles.append(f"and {success_count - 3} more...")
                titles_str = ", ".join(paper_titles)
                self._add_log("add_ris", f"Added {success_count} papers: {titles_str}")

            if error_count > 0:
                self._add_log("add_ris", f"Errors: {error_count} papers failed to add")
                for error in errors[:5]:  # Show first 5 errors
                    self._add_log("add_ris", f"  {error}")
                if error_count > 5:
                    self._add_log("add_ris", f"  ... and {error_count - 5} more errors")

            self.load_papers()

            # Set status message
            if success_count > 0 and error_count == 0:
                self.cli.status_bar.set_status(
                    f"Added {success_count} papers from RIS file", "add"
                )
            elif success_count > 0 and error_count > 0:
                self.cli.status_bar.set_status(
                    f"Added {success_count} papers, {error_count} failed", "edit"
                )
            else:
                self.cli.status_bar.set_status(
                    f"Failed to add papers from RIS file", "error"
                )

        self.cli.background_service.run_operation(
            operation_func=complete_operation,
            operation_name="add_ris",
            initial_message=f"Processing RIS file {ris_path}...",
            on_complete=on_complete,
        )

    def _add_manual_paper(self):
        """Add a paper manually with user input."""
        try:
            # For now, create a basic manual paper
            # This could be enhanced with a proper input dialog
            self.cli.status_bar.set_status(
                "Manual paper entry - using defaults (enhance with dialog later)",
                "edit",
            )

            paper_data = {
                "title": "Manually Added Paper",
                "abstract": "This paper was added manually via PaperCLI.",
                "year": 2024,
                "venue_full": "User Input",
                "venue_acronym": "UI",
                "paper_type": "journal",
                "notes": "Added manually - please update metadata",
            }

            # Normalize paper data for database storage
            paper_data = normalize_paper_data(paper_data)

            authors = ["Manual User"]
            collections = []

            paper = self.cli.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            # Refresh display
            self.load_papers()
            self._add_log("add_manual", f"Added manual paper '{paper.title}'")
            self.cli.status_bar.set_status(
                f"Added manual paper: {paper.title} (use /update to edit metadata)",
                "add",
            )

        except Exception as e:
            self.show_error_panel_with_message(
                "Add Manual Paper Error",
                f"Failed to add manual paper\n\n{traceback.format_exc()}",
            )

    def _show_edit_dialog(self, papers):
        if not isinstance(papers, list):
            papers = [papers]

        def callback(result):
            if self.cli.edit_float in self.cli.app.layout.container.floats:
                self.cli.app.layout.container.floats.remove(self.cli.edit_float)
            self.cli.edit_dialog = None
            self.cli.edit_float = None
            self.cli.app.layout.focus(self.cli.input_buffer)

            if result:
                try:
                    updated_count = 0
                    for paper in papers:
                        # The result from EditDialog now contains proper model objects for relationships
                        # and can be passed directly to the update service.
                        updated_paper, error = self.cli.paper_service.update_paper(
                            paper.id, result
                        )
                        if error:
                            self.cli.status_bar.set_error(f"Update error: {error}")
                            # Show detailed error for PDF processing issues
                            if "PDF processing failed" in error:
                                self.show_error_panel_with_message(
                                    "PDF Processing Error",
                                    f"Failed to process PDF for '{paper.title}'\n\n{error}",
                                )
                        else:
                            updated_count += 1

                    self.load_papers()
                    if updated_count > 0:
                        self.cli.status_bar.set_success(
                            f"Updated {updated_count} paper(s)."
                        )
                        # Trigger auto-sync if enabled
                        self.cli.trigger_auto_sync_if_enabled()
                except Exception as e:
                    self.show_error_panel_with_message(
                        "Update Error",
                        f"Failed to update paper(s)\n\n{traceback.format_exc()}",
                    )
            else:
                self.cli.status_bar.set_status("Update cancelled.")

            self.cli.app.invalidate()

        read_only_fields = []
        if len(papers) == 1:
            paper = papers[0]
            initial_data = {
                field.name: getattr(paper, field.name)
                for field in paper.__table__.columns
            }
            initial_data["authors"] = paper.get_ordered_authors()
            initial_data["collections"] = paper.collections
        else:
            # For multiple papers, show common values or indicate multiple values
            def get_common_value(field):
                values = {getattr(p, field) for p in papers}
                return values.pop() if len(values) == 1 else ""

            initial_data = {
                "title": f"<Editing {len(papers)} papers>",
                "abstract": f"<Editing {len(papers)} papers>",
                "year": get_common_value("year"),
                "venue_full": get_common_value("venue_full"),
                "venue_acronym": get_common_value("venue_acronym"),
                "volume": get_common_value("volume"),
                "issue": get_common_value("issue"),
                "pages": get_common_value("pages"),
                "doi": get_common_value("doi"),
                "preprint_id": get_common_value("preprint_id"),
                "category": get_common_value("category"),
                "url": get_common_value("url"),
                "pdf_path": get_common_value("pdf_path"),
                "paper_type": get_common_value("paper_type") or "conference",
                "notes": get_common_value("notes"),
                "authors": [],
                "collections": [],
            }
            read_only_fields = ["title", "abstract", "author_names", "collections"]

        self.cli.edit_dialog = EditDialog(
            initial_data,
            callback,
            self._add_log,
            self.show_error_panel_with_message,
            read_only_fields=read_only_fields,
            status_bar=self.cli.status_bar,
        )
        self.cli.edit_float = Float(self.cli.edit_dialog)
        self.cli.app.layout.container.floats.append(self.cli.edit_float)
        self.cli.app.layout.focus(
            self.cli.edit_dialog.get_initial_focus() or self.cli.edit_dialog
        )
        self.cli.app.invalidate()

    def _handle_extract_pdf_command(self, papers):
        """Handle /edit extract-pdf command to extract metadata from PDF(s)."""
        # Filter papers that have PDFs
        papers_with_pdfs = [
            paper
            for paper in papers
            if paper.pdf_path and os.path.exists(paper.pdf_path)
        ]

        if not papers_with_pdfs:
            self.cli.status_bar.set_status("No papers have PDF files to extract from")
            return

        # Create the extraction service and run with confirmation
        extraction_service = PDFMetadataExtractionService(
            paper_service=self.cli.paper_service,
            background_service=self.cli.background_service,
            log_callback=self._add_log,
        )

        # Extract metadata with confirmation (like /edit summary but with confirmation step)
        extraction_service.extract_metadata_with_confirmation(
            papers=papers_with_pdfs,
            operation_prefix="extract_pdf",
            refresh_callback=self.load_papers,  # Pass the refresh callback
        )

    def _handle_summarize_command(self, papers):
        """Handle /edit summarize command to generate LLM summary for paper(s)."""
        summary_service = LLMSummaryService(
            paper_service=self.cli.paper_service,
            background_service=self.cli.background_service,
            log_callback=self._add_log,
        )
        summary_service.generate_summaries(
            papers=papers,
            operation_prefix="summarize",
            on_all_complete=lambda tracking: self.load_papers(),
        )

    def _format_paper_details(self, papers: List) -> str:
        """Format metadata for one or more papers into a string."""
        if not papers:
            return "No papers to display."

        if len(papers) == 1:
            paper = papers[0]
            authors = ", ".join([a.full_name for a in paper.get_ordered_authors()])
            collections = ", ".join([c.name for c in paper.collections])
            # Format timestamps
            added_date_str = (
                paper.added_date.strftime("%Y-%m-%d %H:%M:%S %Z")
                if paper.added_date
                else "N/A"
            )
            modified_date_str = (
                paper.modified_date.strftime("%Y-%m-%d %H:%M:%S %Z")
                if paper.modified_date
                else "N/A"
            )

            # Choose appropriate label for venue field
            venue_label = "Website:" if paper.paper_type == "preprint" else "Venue:"

            lines = []
            lines.append(f"Title:        {paper.title}")
            lines.append(f"Authors:      {authors}")
            if paper.year:
                lines.append(f"Year:         {paper.year}")
            lines.append(f"{venue_label:<13} {paper.venue_display}")
            if paper.paper_type:
                lines.append(f"Type:         {paper.paper_type}")
            if collections:
                lines.append(f"Collections:  {collections}")
            if paper.doi:
                lines.append(f"DOI:          {paper.doi}")
            if paper.preprint_id:
                lines.append(f"Preprint ID:  {paper.preprint_id}")
            if paper.category:
                lines.append(f"Category:     {paper.category}")
            if paper.volume:
                lines.append(f"Volume:       {paper.volume}")
            if paper.issue:
                lines.append(f"Issue:        {paper.issue}")
            if paper.pages:
                lines.append(f"Pages:        {paper.pages}")
            if paper.url:
                lines.append(f"URL:          {paper.url}")
            if paper.pdf_path:
                # Show full absolute path instead of relative path
                from ...services.pdf import PDFManager

                pdf_manager = PDFManager()
                full_path = pdf_manager.get_absolute_path(paper.pdf_path)
                lines.append(f"PDF Path:     {full_path}")
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
            value = getattr(first_paper, field)
            is_common = all(getattr(p, field) == value for p in papers[1:])
            display_value = value if is_common else "<Multiple Values>"
            output.append(
                f"{field.replace('_', ' ').title() + ':':<12} {display_value or 'N/A'}"
            )

        # Special handling for collections (many-to-many)
        first_collections = set(c.name for c in first_paper.collections)
        is_common_collections = all(
            set(c.name for c in p.collections) == first_collections for p in papers[1:]
        )
        collections_display = (
            ", ".join(sorted(list(first_collections)))
            if is_common_collections
            else "<Multiple Values>"
        )
        output.append(f"{'Collections:':<12} {collections_display or 'N/A'}")

        return "\n".join(output)
