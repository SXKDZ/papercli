from __future__ import annotations

import os
import threading
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Dict, List

from pluralizer import Pluralizer

from ng.services.metadata import MetadataExtractor
from ng.services.pdf import PDFManager

if TYPE_CHECKING:
    from ng.db.models import Paper
    from ng.services import BackgroundOperationService, PaperService


class LLMSummaryService:
    """Service for generating LLM summaries for multiple papers with queue-based database updates."""

    def __init__(
        self,
        paper_service: PaperService,
        background_service: BackgroundOperationService,
        app=None,
        pdf_dir: str = None,
    ):
        self.paper_service = paper_service
        self.background_service = background_service
        self.app = app
        self.pdf_manager = PDFManager()
        self.metadata_extractor = MetadataExtractor(
            pdf_manager=self.pdf_manager, app=self.app
        )
        self._pluralizer = Pluralizer()

    def _filter_papers_with_pdfs(self, papers: List[Paper]) -> List[Paper]:
        """Filter papers that have accessible PDF files (resolving relative paths)."""
        # Normalize to list
        if not isinstance(papers, list):
            papers = [papers]

        papers_with_pdfs = []
        for p in papers:
            if p.pdf_path:
                absolute_path = self.pdf_manager.get_absolute_path(p.pdf_path)
                if os.path.exists(absolute_path):
                    papers_with_pdfs.append(p)

        return papers_with_pdfs

    def generate_summaries(
        self,
        papers: List[Paper],
        on_all_complete: Callable = None,
        operation_prefix: str = "summary",
    ) -> Dict[str, Any] | None:
        """
        Generate summaries for one or more papers with batched database updates.

        Args:
            papers: Single Paper object or list of Paper objects
            on_all_complete: Callback when all summaries are complete (optional)
            operation_prefix: Prefix for operation names and logs

        Returns:
            dict: Tracking info with completed/total counts and queue, or None if no valid papers
        """
        # Filter papers that have PDFs
        papers_with_pdfs = self._filter_papers_with_pdfs(papers)

        if not papers_with_pdfs:
            if self.app:
                self.app._add_log(
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
        if self.background_service.app:
            if tracking["total"] == 1:
                title = papers_with_pdfs[0].title[:50]
                self.background_service.app.notify(
                    f"Generating summary for '{title}'...", severity="information"
                )
            else:
                self.background_service.app.notify(
                    f"Generating {self._pluralizer.pluralize('summary', tracking['total'], True)}...",
                    severity="information",
                )

        # Start all summary operations
        for paper in papers_with_pdfs:
            self._start_paper_summary(paper, tracking)

        return tracking

    def _start_paper_summary(self, paper: Paper, tracking: Dict[str, Any]):
        """Start summary generation for a single paper."""
        generate_summary_func = partial(
            self._generate_summary, tracking["operation_prefix"]
        )
        on_complete_func = lambda result, error: self._on_summary_complete(
            paper, tracking, result, error
        )

        self.background_service.run_operation(
            operation_func=partial(generate_summary_func, paper),
            operation_name=f"{tracking['operation_prefix']}_{paper.id}",
            initial_message=None,
            on_complete=on_complete_func,
        )

    def _generate_summary(self, operation_prefix: str, current_paper: Paper):
        """Generate summary for a single paper."""
        if self.app:
            self.app._add_log(
                f"{operation_prefix}_starting_{current_paper.id}",
                f"Starting summary for paper ID {current_paper.id}: '{current_paper.title[:50]}...'",
            )

        summary = self.metadata_extractor.generate_paper_summary(current_paper.pdf_path)

        if not summary:
            return None

        return {
            "paper_id": current_paper.id,
            "summary": summary,
            "paper_title": current_paper.title,
        }

    def _on_summary_complete(
        self,
        current_paper: Paper,
        tracking: Dict[str, Any],
        result: Dict[str, Any] | None,
        error: Exception | None,
    ):
        """Handle completion of a single paper summary."""
        tracking["completed"] += 1

        if error:
            tracking["failed"].append((current_paper.id, str(error)))
            if self.app:
                self.app._add_log(
                    f"{tracking['operation_prefix']}_error_{current_paper.id}",
                    f"Failed to generate summary for '{current_paper.title[:50]}...': {error}",
                )
        elif result is None:
            tracking["failed"].append((current_paper.id, "Empty response"))
            if self.app:
                self.app._add_log(
                    f"{tracking['operation_prefix']}_error_{current_paper.id}",
                    f"Failed to generate summary for '{current_paper.title[:50]}...': Empty response",
                )
        else:
            tracking["queue"].append(
                (result["paper_id"], result["summary"], result["paper_title"])
            )
            if self.app:
                self.app._add_log(
                    tracking["operation_prefix"],
                    f"Successfully generated summary for '{result['paper_title']}'",
                )

        self._check_completion(tracking)

    def _check_completion(self, tracking: Dict[str, Any]):
        """Check if all summaries are complete and process the queue."""
        if tracking["completed"] < tracking["total"]:
            # Still in progress
            if self.background_service.app:
                total_text = self._pluralizer.pluralize(
                    "summary", tracking["total"], True
                )
                completed = tracking["completed"]
                total = tracking["total"]
                status_msg = (
                    f"Generating {total_text}... ({completed}/{total} completed)"
                )
                self.background_service.app.notify(status_msg, severity="information")
            return

        # All operations are complete, now process results
        success_count = len(tracking["queue"])
        # Note: we don't need failed_count here; it's used in _finalize_status

        if success_count > 0:
            # Process successful summaries
            self._process_summary_queue(tracking)
        else:
            # No successful summaries, just show final status
            self._finalize_status(tracking)

    def _process_summary_queue(self, tracking: Dict[str, Any]):
        """Process the queue of successfully generated summaries."""
        if self.app:
            queue_size = len(tracking['queue'])
            item_text = self._pluralizer.pluralize("summary", queue_size, True)
            self.app._add_log(
                f"{tracking['operation_prefix']}_queue_processing",
                f"Processing queue with {item_text} to save",
            )

        # Process in background
        threading.Thread(
            target=lambda: self._process_queue_worker(tracking), daemon=True
        ).start()

    def _process_queue_worker(self, tracking: Dict[str, Any]):
        """Worker method to process the summary queue."""
        for paper_id, summary, paper_title in tracking["queue"]:
            try:
                if self.app:
                    self.app._add_log(
                        f"{tracking['operation_prefix']}_save_attempt_{paper_id}",
                        f"Attempting to save summary for paper ID {paper_id}: {paper_title[:50]}...",
                    )

                updated_paper, error_msg = self.paper_service.update_paper(
                    paper_id, {"notes": summary}
                )

                if error_msg:
                    if self.app:
                        self.app._add_log(
                            f"{tracking['operation_prefix']}_save_error_{paper_id}",
                            f"Failed to save summary for {paper_title[:50]}...: {error_msg}",
                        )
                else:
                    if self.app:
                        self.app._add_log(
                            f"{tracking['operation_prefix']}_save_success_{paper_id}",
                            f"Successfully saved summary for {paper_title[:50]}...",
                        )
            except Exception as e:
                if self.app:
                    self.app._add_log(
                        f"{tracking['operation_prefix']}_save_exception_{paper_id}",
                        f"Exception saving summary for {paper_title[:50]}...: {e}",
                    )

        # Schedule UI update after processing the whole queue
        if self.background_service.app:
            self.background_service.app.call_from_thread(
                lambda: self._finalize_status(tracking)
            )

    def _finalize_status(self, tracking: Dict[str, Any]):
        """Set the final status message based on the outcome."""
        success_count = len(tracking["queue"])
        failed_count = len(tracking["failed"])
        total_count = tracking["total"]

        # Call completion callback first to refresh the UI
        if tracking["on_all_complete"]:
            tracking["on_all_complete"](tracking)

        # Then set the status message
        if self.background_service.app:
            if total_count == 1:
                if success_count == 1:
                    self.background_service.app.notify(
                        "Summary generated and saved successfully",
                        severity="information",
                    )
                else:
                    self.background_service.app.notify(
                        "Failed to generate summary", severity="error"
                    )
            else:
                if success_count > 0 and failed_count > 0:
                    self.background_service.app.notify(
                        f"Completed: {self._pluralizer.pluralize('summary', success_count, True)} succeeded, "
                        f"{self._pluralizer.pluralize('summary', failed_count, True)} failed",
                        severity="warning",
                    )
                elif success_count > 0:
                    all_text = self._pluralizer.pluralize(
                        "summary", success_count, True
                    )
                    self.background_service.app.notify(
                        f"All {all_text} generated and saved successfully",
                        severity="information",
                    )
                elif failed_count > 0:
                    failed_text = self._pluralizer.pluralize(
                        "summary", failed_count, True
                    )
                    self.background_service.app.notify(
                        f"Failed to generate {failed_text}",
                        severity="error",
                    )
                else:
                    self.background_service.app.notify(
                        "Summary generation finished with no results",
                        severity="information",
                    )
