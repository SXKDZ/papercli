"""LLM services - AI-powered paper summarization and PDF metadata extraction."""

import os
import threading
from functools import partial

from prompt_toolkit.application import get_app
from prompt_toolkit.layout.containers import Float
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Dialog, TextArea

from ..services.author_service import AuthorService
from ..services.utils import compare_extracted_metadata_with_paper


class LLMSummaryService:
    """Service for generating LLM summaries for multiple papers with queue-based database updates."""

    def __init__(self, paper_service, background_service, log_callback=None):
        self.paper_service = paper_service
        self.background_service = background_service
        self.log_callback = log_callback

    def generate_summaries(
        self, papers, on_all_complete=None, operation_prefix="summary"
    ):
        """
        Generate summaries for one or more papers with batched database updates.

        Args:
            papers: Single Paper object or list of Paper objects
            on_all_complete: Callback when all summaries are complete (optional)
            operation_prefix: Prefix for operation names and logs

        Returns:
            dict: Tracking info with completed/total counts and queue, or None if no valid papers
        """
        # Normalize to list
        if not isinstance(papers, list):
            papers = [papers]

        # Filter papers that have PDFs
        papers_with_pdfs = [
            p for p in papers if p.pdf_path and os.path.exists(p.pdf_path)
        ]

        if not papers_with_pdfs:
            if self.log_callback:
                self.log_callback(
                    f"{operation_prefix}_no_pdfs", "No papers with PDFs found"
                )
            return None

        # Initialize tracking
        tracking = {
            "completed": 0,
            "total": len(papers_with_pdfs),
            "queue": [],  # Will hold (paper_id, summary, paper_title) tuples
            "failed": [],  # Will hold (paper_id, error_message) tuples
            "papers": papers_with_pdfs,
            "on_all_complete": on_all_complete,
            "operation_prefix": operation_prefix,
        }

        # Set initial status
        if self.background_service.status_bar:
            if tracking["total"] == 1:
                title = papers_with_pdfs[0].title[:50]
                self.background_service.status_bar.set_status(
                    f"Generating summary for '{title}'...", "loading"
                )
            else:
                self.background_service.status_bar.set_status(
                    f"Generating summaries for {tracking['total']} papers...", "loading"
                )

        # Start all summary operations
        for paper in papers_with_pdfs:
            self._start_paper_summary(paper, tracking)

        return tracking

    def _start_paper_summary(self, paper, tracking):
        """Start summary generation for a single paper."""

        def generate_summary(current_paper):
            if self.log_callback:
                self.log_callback(
                    f"{tracking['operation_prefix']}_starting_{current_paper.id}",
                    f"Starting summary for paper ID {current_paper.id}: '{current_paper.title[:50]}...'",
                )

            # Import MetadataExtractor here to avoid circular imports
            from .metadata_service import MetadataExtractor

            extractor = MetadataExtractor(log_callback=self.log_callback)
            summary = extractor.generate_paper_summary(current_paper.pdf_path)

            if not summary:
                raise Exception("Failed to generate summary - empty response")

            return {
                "paper_id": current_paper.id,
                "summary": summary,
                "paper_title": current_paper.title,
            }

        def on_summary_complete(current_paper, tracking, result, error):
            tracking["completed"] += 1

            if error:
                # Add to failed queue for detailed error tracking
                tracking["failed"].append((current_paper.id, str(error)))
                if self.log_callback:
                    self.log_callback(
                        f"{tracking['operation_prefix']}_error_{current_paper.id}",
                        f"Failed to generate summary for '{current_paper.title[:50]}...': {error}",
                    )
            else:
                # Add to success queue
                tracking["queue"].append(
                    (result["paper_id"], result["summary"], result["paper_title"])
                )
                if self.log_callback:
                    self.log_callback(
                        tracking["operation_prefix"],
                        f"Successfully generated summary for '{result['paper_title']}'",
                    )

            self._check_completion(tracking)

        self.background_service.run_operation(
            operation_func=partial(generate_summary, paper),
            operation_name=f"{tracking['operation_prefix']}_{paper.id}",
            initial_message=None,  # Don't override the main status
            on_complete=partial(on_summary_complete, paper, tracking),
        )

    def _check_completion(self, tracking):
        """Check if all summaries are complete and process the queue."""
        if tracking["completed"] < tracking["total"]:
            # Still in progress
            if self.background_service.status_bar:
                status_msg = f"Generating summaries... ({tracking['completed']}/{tracking['total']} completed)"
                self.background_service.status_bar.set_status(status_msg, "loading")
            return

        # All operations are complete, now process results
        success_count = len(tracking["queue"])
        failed_count = len(tracking["failed"])

        if success_count > 0:
            # Process successful summaries
            self._process_summary_queue(tracking)
        else:
            # No successful summaries, just show final status
            self._finalize_status(tracking)

    def _process_summary_queue(self, tracking):
        """Process the queue of successfully generated summaries."""
        if self.log_callback:
            self.log_callback(
                f"{tracking['operation_prefix']}_queue_processing",
                f"Processing queue with {len(tracking['queue'])} summaries to save",
            )

        def process_queue():
            for paper_id, summary, paper_title in tracking["queue"]:
                try:
                    updated_paper, error_msg = self.paper_service.update_paper(
                        paper_id, {"notes": summary}
                    )
                    if error_msg:
                        if self.log_callback:
                            self.log_callback(
                                f"{tracking['operation_prefix']}_save_error_{paper_id}",
                                f"Failed to save summary for {paper_title[:50]}...: {error_msg}",
                            )
                except Exception as e:
                    if self.log_callback:
                        self.log_callback(
                            f"{tracking['operation_prefix']}_save_exception_{paper_id}",
                            f"Exception saving summary for {paper_title[:50]}...: {e}",
                        )

            # Schedule UI update after processing the whole queue
            get_app().loop.call_soon_threadsafe(lambda: self._finalize_status(tracking))

        # Process in background
        threading.Thread(target=process_queue, daemon=True).start()

    def _finalize_status(self, tracking):
        """Set the final status message based on the outcome."""
        success_count = len(tracking["queue"])
        failed_count = len(tracking["failed"])
        total_count = tracking["total"]

        # Call completion callback first to refresh the UI
        if tracking["on_all_complete"]:
            tracking["on_all_complete"](tracking)

        # Then set the status bar message
        if self.background_service.status_bar:
            if total_count == 1:
                if success_count == 1:
                    self.background_service.status_bar.set_success(
                        "Summary generated and saved successfully"
                    )
                else:
                    self.background_service.status_bar.set_error(
                        "Failed to generate summary"
                    )
            else:
                if success_count > 0 and failed_count > 0:
                    self.background_service.status_bar.set_warning(
                        f"Completed: {success_count} succeeded, {failed_count} failed"
                    )
                elif success_count > 0:
                    self.background_service.status_bar.set_success(
                        f"All {success_count} summaries generated and saved successfully"
                    )
                elif failed_count > 0:
                    self.background_service.status_bar.set_error(
                        f"Failed to generate summaries for all {failed_count} papers"
                    )
                else:
                    self.background_service.status_bar.set_status(
                        "Summary generation finished with no results"
                    )

        get_app().invalidate()


class PDFMetadataExtractionService:
    """Service for extracting metadata from PDF files for multiple papers."""

    def __init__(self, paper_service, background_service, log_callback=None):
        self.paper_service = paper_service
        self.background_service = background_service
        self.log_callback = log_callback

    def extract_metadata(
        self, papers, on_all_complete=None, operation_prefix="extract_pdf"
    ):
        """
        Extract metadata from PDF files for one or more papers.

        Args:
            papers: Single Paper object or list of Paper objects
            on_all_complete: Callback when all extractions are complete (optional)
            operation_prefix: Prefix for operation names and logs

        Returns:
            dict: Tracking info with completed/total counts and results, or None if no valid papers
        """
        # Normalize to list
        if not isinstance(papers, list):
            papers = [papers]

        # Filter papers that have PDFs
        papers_with_pdfs = [
            p for p in papers if p.pdf_path and os.path.exists(p.pdf_path)
        ]

        if not papers_with_pdfs:
            if self.log_callback:
                self.log_callback(
                    f"{operation_prefix}_no_pdfs", "No papers with PDFs found"
                )
            return None

        # Initialize tracking
        tracking = {
            "completed": 0,
            "total": len(papers_with_pdfs),
            "results": [],  # Will hold (paper_id, extracted_data, paper_title) tuples
            "papers": papers_with_pdfs,
            "on_all_complete": on_all_complete,
            "operation_prefix": operation_prefix,
        }

        # Set initial status
        if self.background_service.status_bar:
            if tracking["total"] == 1:
                title = papers_with_pdfs[0].title[:50]
                self.background_service.status_bar.set_status(
                    f"Extracting metadata from '{title}'...", "loading"
                )
            else:
                self.background_service.status_bar.set_status(
                    f"Extracting metadata from {tracking['total']} PDFs...", "loading"
                )

        # Start all extraction operations
        for paper in papers_with_pdfs:
            self._start_paper_extraction(paper, tracking)

        return tracking

    def extract_metadata_with_confirmation(
        self, papers, operation_prefix="extract_pdf", refresh_callback=None
    ):
        """
        Extract metadata from PDFs with confirmation dialog, similar to /edit summary pattern.

        Args:
            papers: Single Paper object or list of Paper objects
            operation_prefix: Prefix for operation names and logs
        """
        # Normalize to list
        if not isinstance(papers, list):
            papers = [papers]

        # Filter papers that have PDFs
        papers_with_pdfs = [
            p for p in papers if p.pdf_path and os.path.exists(p.pdf_path)
        ]

        if not papers_with_pdfs:
            if self.log_callback:
                self.log_callback(
                    f"{operation_prefix}_no_pdfs", "No papers with PDFs found"
                )
            return

        def extract_and_show_confirmation():
            """Extract metadata and show confirmation dialog."""
            all_results = []
            all_changes = []

            for paper in papers_with_pdfs:
                try:
                    # Import MetadataExtractor here to avoid circular imports
                    from ..services import MetadataExtractor

                    extractor = MetadataExtractor(log_callback=self.log_callback)
                    extracted_data = extractor.extract_from_pdf(paper.pdf_path)

                    if extracted_data:
                        # Compare with current paper data
                        paper_changes = compare_extracted_metadata_with_paper(
                            extracted_data, paper
                        )

                        if paper_changes:
                            all_results.append((paper.id, extracted_data, paper.title))
                            all_changes.append(
                                f"Paper: {paper.title[:50]}{'...' if len(paper.title) > 50 else ''}"
                            )
                            all_changes.extend(
                                [f"  {change}" for change in paper_changes]
                            )
                            all_changes.append("")  # Empty line between papers

                except Exception as e:
                    if self.log_callback:
                        self.log_callback(
                            "extract_error",
                            f"Failed to extract from {paper.title}: {e}",
                        )
                    # Display error in status bar
                    if self.background_service.status_bar:
                        self.background_service.status_bar.set_error(
                            f"Error extracting from {paper.title}..."
                        )
                    return  # Stop further processing

            # Show confirmation dialog if there are changes
            if not all_changes:
                if self.background_service.status_bar:
                    self.background_service.status_bar.set_status(
                        "No changes found in PDFs"
                    )
                return

            changes_text = "\n".join(all_changes)

            def apply_updates():
                """Apply the extracted metadata to database."""
                updated_count = 0
                for paper_id, extracted_data, paper_title in all_results:
                    try:
                        paper = self.paper_service.get_paper_by_id(paper_id)
                        if paper and extracted_data:
                            update_data = self._prepare_update_data(extracted_data)
                            if update_data:
                                self.paper_service.update_paper(paper_id, update_data)
                                updated_count += 1

                                if self.log_callback:
                                    fields_updated = list(update_data.keys())
                                    self.log_callback(
                                        "extract_pdf_update",
                                        f"Updated '{paper_title}' with: {', '.join(fields_updated)}",
                                    )
                    except Exception as e:
                        if self.log_callback:
                            self.log_callback(
                                "extract_pdf_error",
                                f"Failed to update '{paper_title}': {e}",
                            )

                # Set final status
                if self.background_service.status_bar:
                    if updated_count == 0:
                        self.background_service.status_bar.set_status(
                            "PDF metadata extracted but no database updates needed"
                        )
                    elif updated_count == 1:
                        self.background_service.status_bar.set_success(
                            "PDF metadata extraction completed - 1 paper updated"
                        )
                    else:
                        self.background_service.status_bar.set_success(
                            f"PDF metadata extraction completed - {updated_count} papers updated"
                        )

            # Create confirmation dialog with scrollable textarea
            changes_textarea = TextArea(
                text=changes_text,
                read_only=True,
                scrollbar=True,
                multiline=True,
                height=Dimension(min=10, max=25),  # Set height on TextArea instead
                width=Dimension(min=80, preferred=100),
            )

            def cleanup_and_apply():
                apply_updates()
                # Clean up dialog
                if (
                    hasattr(self, "_confirmation_float")
                    and self._confirmation_float in get_app().layout.container.floats
                ):
                    get_app().layout.container.floats.remove(self._confirmation_float)
                # Refresh papers display
                if refresh_callback:
                    refresh_callback()

            def cleanup_and_cancel():
                # Clean up dialog
                if (
                    hasattr(self, "_confirmation_float")
                    and self._confirmation_float in get_app().layout.container.floats
                ):
                    get_app().layout.container.floats.remove(self._confirmation_float)
                if self.background_service.status_bar:
                    self.background_service.status_bar.set_status(
                        "PDF extraction cancelled"
                    )

            dialog = Dialog(
                title="Confirm PDF Metadata Extraction",
                body=changes_textarea,
                buttons=[
                    Button(text="Apply", handler=cleanup_and_apply),
                    Button(text="Cancel", handler=cleanup_and_cancel),
                ],
                with_background=False,
            )

            # Show dialog
            app = get_app()
            self._confirmation_float = Float(content=dialog)
            app.layout.container.floats.append(self._confirmation_float)
            app.layout.focus(dialog)
            app.invalidate()

        # Run extraction in background
        self.background_service.run_operation(
            operation_func=extract_and_show_confirmation,
            operation_name=f"{operation_prefix}_confirmation",
            initial_message="Extracting metadata from PDFs...",
            on_complete=lambda result, error: None,
        )

    def _prepare_update_data(self, extracted_data):
        """Prepare update data from extracted metadata."""
        update_data = {}

        field_mapping = {
            "title": "title",
            "authors": "authors",
            "abstract": "abstract",
            "year": "year",
            "venue_full": "venue_full",
            "venue_acronym": "venue_acronym",
            "doi": "doi",
            "url": "url",
            "category": "category",
            "paper_type": "paper_type",
        }

        for extracted_field, paper_field in field_mapping.items():
            if extracted_field in extracted_data and extracted_data[extracted_field]:
                if extracted_field == "authors" and isinstance(
                    extracted_data[extracted_field], list
                ):
                    # Convert author names to Author objects
                    author_service = AuthorService()
                    author_objects = []
                    for author_name in extracted_data[extracted_field]:
                        author = author_service.get_or_create_author(
                            author_name.strip()
                        )
                        author_objects.append(author)
                    update_data[paper_field] = author_objects
                else:
                    update_data[paper_field] = extracted_data[extracted_field]

        return update_data

    def _start_paper_extraction(self, paper, tracking):
        """Start PDF metadata extraction for a single paper."""

        def extract_metadata(current_paper):
            if self.log_callback:
                self.log_callback(
                    f"{tracking['operation_prefix']}_starting_{current_paper.id}",
                    f"Starting PDF extraction for paper ID {current_paper.id}: '{current_paper.title[:50]}...'",
                )

            # Import MetadataExtractor here to avoid circular imports
            from .metadata_service import MetadataExtractor

            extractor = MetadataExtractor(log_callback=self.log_callback)
            extracted_data = extractor.extract_from_pdf(current_paper.pdf_path)

            return {
                "paper_id": current_paper.id,
                "extracted_data": extracted_data,
                "paper_title": current_paper.title,
            }

        def on_extraction_complete(current_paper, tracking, result, error):
            if error:
                tracking["completed"] += 1
                if self.log_callback:
                    self.log_callback(
                        f"{tracking['operation_prefix']}_error_{current_paper.id}",
                        f"Failed to extract metadata for '{current_paper.title[:50]}...': {error}",
                    )
                self._check_completion(tracking)
                return

            # Add to results
            tracking["results"].append(
                (result["paper_id"], result["extracted_data"], result["paper_title"])
            )

            if self.log_callback:
                self.log_callback(
                    tracking["operation_prefix"],
                    f"Successfully extracted metadata for '{result['paper_title']}'",
                )

            tracking["completed"] += 1
            self._check_completion(tracking)

        self.background_service.run_operation(
            operation_func=partial(extract_metadata, paper),
            operation_name=f"{tracking['operation_prefix']}_{paper.id}",
            initial_message=None,  # Don't override the main status
            on_complete=partial(on_extraction_complete, paper, tracking),
        )

    def _check_completion(self, tracking):
        """Check if all extractions are complete and process results."""
        # Update status
        if tracking["completed"] >= tracking["total"]:
            # All completed
            if self.background_service.status_bar:
                if tracking["total"] == 1:
                    self.background_service.status_bar.set_success(
                        "PDF metadata extraction completed"
                    )
                else:
                    self.background_service.status_bar.set_success(
                        f"All {tracking['total']} PDF extractions completed"
                    )

            # Call completion callback
            if tracking["on_all_complete"]:
                tracking["on_all_complete"](tracking)
        else:
            # Still in progress
            if self.background_service.status_bar:
                if tracking["total"] == 1:
                    self.background_service.status_bar.set_status(
                        "Extracting PDF metadata...", "loading"
                    )
                else:
                    self.background_service.status_bar.set_status(
                        f"Extracting metadata... ({tracking['completed']}/{tracking['total']} completed)",
                        "loading",
                    )
