from __future__ import annotations

import os
import shutil
import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ng.db.database import get_pdf_directory
from ng.services import (
    MetadataExtractor,
    PaperService,
    PDFManager,
    PDFService,
    SystemService,
    WebpageSnapshotService,
    format_title_by_words,
    normalize_paper_data,
)

if TYPE_CHECKING:
    from ng.db.models import Paper


class AddPaperService:
    """Service for adding papers from various sources."""

    def __init__(
        self,
        paper_service: PaperService,
        metadata_extractor: MetadataExtractor,
        system_service: SystemService,
        app,
    ):
        """Initialize the add paper service."""
        self.paper_service = paper_service
        self.metadata_extractor = metadata_extractor
        self.system_service = system_service
        self.app = app

    # Internal helpers
    def _build_paper_data(
        self, metadata: Dict[str, Any], overrides: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Build and normalize paper data from raw metadata with optional overrides."""
        data: Dict[str, Any] = {
            "title": metadata.get("title", "Unknown Title"),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "unknown"),
            "doi": metadata.get("doi"),
            "url": metadata.get("url"),
            "category": metadata.get("category"),
            "preprint_id": metadata.get("preprint_id"),
            "volume": metadata.get("volume"),
            "issue": metadata.get("issue"),
            "pages": metadata.get("pages"),
        }
        if overrides:
            data.update({k: v for k, v in overrides.items() if v is not None})
        return normalize_paper_data(data)

    def _resolve_path(self, path: str) -> str:
        """Resolve a user-provided file path to an absolute path."""
        return os.path.abspath(os.path.expanduser(path))

    def add_arxiv_paper(self, arxiv_id: str) -> Dict[str, Any]:
        """Add a paper from arXiv."""
        metadata = self.metadata_extractor.extract_from_arxiv(arxiv_id)
        paper_data = self._build_paper_data(
            metadata,
            overrides={
                "paper_type": "preprint",
                "url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            },
        )

        # Add to database first (without PDF)
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        # Download PDF
        pdf_dir = get_pdf_directory()
        pdf_path, pdf_error, download_duration = self.system_service.download_pdf(
            "arxiv", arxiv_id, pdf_dir, paper_data
        )

        return {
            "paper": paper,
            "pdf_path": pdf_path,
            "pdf_error": pdf_error,
            "download_duration": download_duration,
        }

    def add_arxiv_paper_async(self, arxiv_id: str) -> Dict[str, Any]:
        """Add a paper from arXiv (step 1: metadata only, for background processing)."""
        # Extract metadata from arXiv
        metadata = self.metadata_extractor.extract_from_arxiv(arxiv_id)

        # Prepare paper data (without PDF initially)
        paper_data = {
            "title": metadata["title"],
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "preprint"),
            "preprint_id": metadata.get("preprint_id"),
            "category": metadata.get("category"),
            "doi": metadata.get("doi"),
            "url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        }

        paper_data = normalize_paper_data(paper_data)

        # Add to database first (without PDF)
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        return {"paper": paper, "arxiv_id": arxiv_id, "paper_data": paper_data}

    def download_and_update_pdf(
        self, paper_id: int, source: str, identifier: str, paper_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Background task to download PDF and update paper record."""
        try:
            # Log start of download process
            self.app._add_log(
                "pdf_download_start",
                f"Starting PDF download for paper_id={paper_id}, source={source}, identifier={identifier}",
            )

            # Download PDF
            pdf_dir = get_pdf_directory()

            try:
                pdf_path, pdf_error, download_duration = (
                    self.system_service.download_pdf(
                        source, identifier, pdf_dir, paper_data
                    )
                )
                pass
            except Exception as e:
                self.app._add_log(
                    "pdf_download_exception",
                    f"Exception calling system_service.download_pdf: {str(e)}",
                )
                self.app._add_log(
                    "pdf_download_traceback", f"Traceback: {traceback.format_exc()}"
                )
                raise

            # Summarize result in a readable way
            if pdf_path and not pdf_error:
                summary = PDFService(app=self.app).create_download_summary(
                    pdf_path, download_duration
                )
                self.app._add_log("pdf_download_result", summary)
            else:
                self.app._add_log(
                    "pdf_download_error",
                    f"Download failed: {pdf_error or 'Unknown error'}",
                )

            if pdf_path and not pdf_error:
                # Success implied by result; skip extra stage logs

                # Convert absolute path to relative for storage
                relative_pdf_path = os.path.relpath(pdf_path, pdf_dir)

                # Update the paper with PDF path
                update_data = {"pdf_path": relative_pdf_path}

                updated_paper, update_error = self.paper_service.update_paper(
                    paper_id, update_data
                )
                self.app._add_log(
                    "pdf_update_result",
                    f"paper_updated={updated_paper is not None}, error='{update_error}'",
                )

                if update_error:
                    self.app._add_log(
                        "pdf_update_error",
                        f"Database update failed: {update_error}",
                    )
                    return {
                        "success": False,
                        "error": f"PDF downloaded but database update failed: {update_error}",
                    }

                # Completed
                self.app._add_log(
                    "pdf_download_complete",
                    f"Updated paper {paper_id} with PDF path: {relative_pdf_path}",
                )
                return {
                    "success": True,
                    "pdf_path": relative_pdf_path,
                    "paper": updated_paper,
                    "download_duration": download_duration,
                }
            else:
                error_msg = pdf_error or "Unknown PDF download error"
                self.app._add_log(
                    "pdf_download_error", f"PDF download failed: {error_msg}"
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "download_duration": download_duration,
                }

        except Exception as e:
            error_msg = f"Failed to download and update PDF: {str(e)}"
            self.app._add_log(
                "pdf_download_exception",
                f"Exception in download_and_update_pdf: {error_msg}",
            )
            self.app._add_log(
                "pdf_download_traceback", f"Traceback: {traceback.format_exc()}"
            )
            return {"success": False, "error": error_msg, "download_duration": 0.0}

    def add_dblp_paper(self, dblp_url: str) -> Dict[str, Any]:
        """Add a paper from DBLP URL."""
        # Extract metadata from DBLP
        metadata = self.metadata_extractor.extract_from_dblp(dblp_url)

        # Prepare paper data
        paper_data = {
            "title": metadata.get("title", "Unknown Title"),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "conference"),
            "doi": metadata.get("doi"),
            "url": dblp_url,
        }

        paper_data = normalize_paper_data(paper_data)

        # Add to database
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )
        if self.app:
            self.app._add_log(
                "paper_add_dblp",
                f"Added DBLP paper '{paper.title}' (ID {paper.id})",
            )

        return {"paper": paper, "pdf_path": None, "pdf_error": None}

    def add_openreview_paper(self, openreview_id: str) -> Dict[str, Any]:
        """Add a paper from OpenReview."""
        metadata = self.metadata_extractor.extract_from_openreview(openreview_id)
        paper_data = self._build_paper_data(
            metadata,
            overrides={
                "paper_type": metadata.get("paper_type", "conference"),
                "url": metadata.get(
                    "url", f"https://openreview.net/forum?id={openreview_id}"
                ),
            },
        )

        # Add to database
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )
        if self.app:
            self.app._add_log(
                "paper_add_openreview",
                f"Added OpenReview metadata for '{paper.title}' (ID {paper.id})",
            )

        # Download PDF
        pdf_dir = get_pdf_directory()
        pdf_path, pdf_error, download_duration = self.system_service.download_pdf(
            "openreview", openreview_id, pdf_dir, paper_data
        )

        return {
            "paper": paper,
            "pdf_path": pdf_path,
            "pdf_error": pdf_error,
            "download_duration": download_duration,
        }

    def add_openreview_paper_async(self, openreview_id: str) -> Dict[str, Any]:
        """Add a paper from OpenReview (step 1: metadata only, for background processing)."""
        # Extract metadata from OpenReview
        metadata = self.metadata_extractor.extract_from_openreview(openreview_id)

        # Prepare paper data
        paper_data = {
            "title": metadata.get("title", "Unknown Title"),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "conference"),
            "category": metadata.get("category"),
            "url": metadata.get(
                "url", f"https://openreview.net/forum?id={openreview_id}"
            ),
        }

        paper_data = normalize_paper_data(paper_data)

        # Add to database
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        return {
            "paper": paper,
            "openreview_id": openreview_id,
            "paper_data": paper_data,
        }

    def add_pdf_paper_async(self, pdf_path: str) -> Dict[str, Any]:
        """Add a paper from local PDF file (step 1: copy PDF, metadata extraction queued for background)."""
        # Expand user path and resolve relative paths
        pdf_path = os.path.expanduser(pdf_path)
        pdf_path = os.path.abspath(pdf_path)

        if not os.path.exists(pdf_path):
            raise Exception(f"PDF file not found: {pdf_path}")

        if not pdf_path.lower().endswith(".pdf"):
            raise Exception(f"File is not a PDF: {pdf_path}")

        # Copy PDF first with minimal metadata for filename generation
        temp_paper_data = {
            "title": "PDF Paper",
            "authors": ["Unknown"],
            "year": datetime.now().year,
        }

        pdf_manager = PDFManager(app=self.app)
        # Copy PDF to collection directory with timing
        relative_pdf_path, pdf_error = pdf_manager.process_pdf_path(
            pdf_path, temp_paper_data
        )
        copy_duration = 0.0  # process_pdf_path doesn't return duration

        if pdf_error:
            raise Exception(f"Failed to copy PDF: {pdf_error}")

        # Create minimal paper entry first (will be updated with metadata later)
        paper_data = {
            "title": "PDF Paper (extracting metadata...)",
            "abstract": "",
            "authors": ["Unknown"],
            "year": datetime.now().year,
            "venue_full": "",
            "venue_acronym": "",
            "paper_type": "unknown",
            "doi": None,
            "url": None,
            "pdf_path": relative_pdf_path,
        }

        paper_data = normalize_paper_data(paper_data)

        # Add paper to database with minimal info
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        if self.app:
            self.app._add_log(
                "paper_add_pdf_async",
                f"Queued metadata extraction for PDF '{pdf_path}' after adding paper ID {paper.id}",
            )

        return {"paper": paper, "pdf_path": pdf_path, "paper_data": paper_data}

    def extract_and_update_pdf_metadata(
        self, paper_id: int, pdf_path: str
    ) -> Dict[str, Any]:
        """Background task to extract metadata from PDF and update paper record."""
        try:
            # Log start of extraction process
            if self.app:
                self.app._add_log(
                    "pdf_metadata_extraction_start",
                    f"Starting metadata extraction for paper_id={paper_id}, pdf_path={pdf_path}",
                )

            # Extract metadata from PDF (this is the slow LLM operation)
            metadata = self.metadata_extractor.extract_from_pdf(pdf_path)

            # Update paper with extracted metadata
            update_data = {
                "title": metadata.get("title", "Unknown Title"),
                "abstract": metadata.get("abstract", ""),
                "authors": metadata.get("authors", []),
                "year": metadata.get("year"),
                "venue_full": metadata.get("venue_full", ""),
                "venue_acronym": metadata.get("venue_acronym", ""),
                "paper_type": metadata.get("paper_type", "unknown"),
                "doi": metadata.get("doi"),
                "url": metadata.get("url"),
            }

            update_data = normalize_paper_data(update_data)

            if self.app:
                self.app._add_log(
                    "pdf_metadata_update",
                    f"Updating paper {paper_id} with extracted metadata: {list(update_data.keys())}",
                )

            updated_paper, update_error = self.paper_service.update_paper(
                paper_id, update_data
            )

            if update_error:
                if self.app:
                    self.app._add_log(
                        "pdf_metadata_error",
                        f"Failed to update paper with metadata: {update_error}",
                    )
                return {
                    "success": False,
                    "error": f"Metadata extracted but database update failed: {update_error}",
                }

            # Rename PDF file to match extracted metadata
            if updated_paper and updated_paper.pdf_path:
                try:
                    pdf_manager = PDFManager(app=self.app)
                    old_pdf_path = pdf_manager.get_absolute_path(updated_paper.pdf_path)

                    # Generate new filename with extracted metadata
                    new_filename = pdf_manager._generate_pdf_filename(
                        metadata, old_pdf_path
                    )
                    new_pdf_path = os.path.join(pdf_manager.pdf_dir, new_filename)

                    # Only rename if the filename would actually change
                    if old_pdf_path != new_pdf_path and os.path.exists(old_pdf_path):
                        shutil.move(old_pdf_path, new_pdf_path)

                        # Update database with new relative path
                        new_relative_path = pdf_manager.get_relative_path(new_pdf_path)
                        updated_paper, update_error = self.paper_service.update_paper(
                            paper_id, {"pdf_path": new_relative_path}
                        )

                        if self.app:
                            self.app._add_log(
                                "pdf_filename_update",
                                f"Renamed PDF file to match extracted metadata: {new_filename}",
                            )

                except Exception as e:
                    # Don't fail the whole operation if PDF renaming fails
                    if self.app:
                        self.app._add_log(
                            "pdf_rename_warning",
                            f"Failed to rename PDF file: {str(e)}",
                        )

            if self.app:
                self.app._add_log(
                    "pdf_metadata_complete",
                    f"Successfully updated paper {paper_id} with extracted metadata",
                )

            return {
                "success": True,
                "paper": updated_paper,
                "extracted_metadata": metadata,
            }

        except Exception as e:
            error_msg = f"Failed to extract and update PDF metadata: {str(e)}"
            if self.app:
                self.app._add_log(
                    "pdf_metadata_exception",
                    f"Exception in extract_and_update_pdf_metadata: {error_msg}",
                )
                self.app._add_log(
                    "pdf_metadata_traceback", f"Traceback: {traceback.format_exc()}"
                )
            return {"success": False, "error": error_msg}

    def add_bib_papers(self, bib_path: str) -> Tuple[List[Paper], List[str]]:
        """Add papers from .bib file."""
        # Resolve path and do simple validation
        bib_path = self._resolve_path(bib_path)
        if not os.path.exists(bib_path) or not bib_path.lower().endswith(
            (".bib", ".bibtex")
        ):
            raise Exception(f"Invalid BibTeX file: {bib_path}")

        # Extract metadata from BibTeX file
        papers_metadata = self.metadata_extractor.extract_from_bibtex(bib_path)

        added_papers = []
        errors = []

        for metadata in papers_metadata:
            try:
                # Prepare and normalize paper data
                paper_data = self._build_paper_data(metadata)

                # Add to database first
                authors = paper_data.get("authors", [])
                collections = []

                paper = self.paper_service.add_paper_from_metadata(
                    paper_data, authors, collections
                )
                if self.app:
                    self.app._add_log(
                        "paper_add_bib_entry",
                        (
                            "Added paper from BIB entry '"
                            + paper_data.get("title", "Unknown Title")[:80]
                            + f"...' (ID {paper.id})"
                        ),
                    )

                # Try to download or process PDF if URL is provided
                if metadata.get("url"):
                    pdf_manager = PDFManager(app=self.app)

                    try:
                        pdf_path, pdf_error = pdf_manager.process_pdf_path(
                            metadata["url"], paper_data
                        )
                        download_duration = (
                            0.0  # process_pdf_path doesn't return duration
                        )

                        if pdf_path and not pdf_error:
                            # process_pdf_path returns a relative path; ensure we store it as-is
                            relative_pdf_path = pdf_path
                            absolute_pdf_path = pdf_manager.get_absolute_path(
                                relative_pdf_path
                            )

                            update_data = {"pdf_path": relative_pdf_path}
                            updated_paper, update_error = (
                                self.paper_service.update_paper(paper.id, update_data)
                            )

                            if not update_error and self.app:
                                summary = PDFService(
                                    app=self.app
                                ).create_download_summary(
                                    absolute_pdf_path, download_duration
                                )
                                preview = format_title_by_words(
                                    paper_data.get("title", "") or ""
                                )
                                self.app.notify(
                                    f"PDF available for '{preview}': {summary}",
                                    severity="information",
                                )

                    except Exception as pdf_e:
                        # Don't fail the entire paper addition if PDF download fails
                        if self.app:
                            self.app._add_log(
                                "bib_pdf_warning",
                                f"Could not download PDF for '{paper_data['title']}': {str(pdf_e)}",
                            )

                added_papers.append(paper)

            except Exception as e:
                errors.append(
                    f"Failed to add paper '{metadata.get('title', 'Unknown')}': {e}"
                )

        return added_papers, errors

    def add_ris_papers(self, ris_path: str) -> Tuple[List[Paper], List[str]]:
        """Add papers from .ris file."""
        # Resolve path and do simple validation
        ris_path = self._resolve_path(ris_path)
        if not os.path.exists(ris_path) or not ris_path.lower().endswith(
            (".ris", ".txt")
        ):
            raise Exception(f"Invalid RIS file: {ris_path}")

        # Extract metadata from RIS file
        papers_metadata = self.metadata_extractor.extract_from_ris(ris_path)

        added_papers = []
        errors = []

        for metadata in papers_metadata:
            try:
                # Prepare and normalize paper data
                paper_data = self._build_paper_data(metadata)

                # Add to database
                authors = paper_data.get("authors", [])
                collections = []

                paper = self.paper_service.add_paper_from_metadata(
                    paper_data, authors, collections
                )

                added_papers.append(paper)

            except Exception as e:
                errors.append(
                    f"Failed to add paper '{metadata.get('title', 'Unknown')}': {e}"
                )

        return added_papers, errors

    def add_doi_paper(self, doi: str) -> Dict[str, Any]:
        """Add a paper from DOI."""
        # Extract metadata from DOI using Crossref API
        metadata = self.metadata_extractor.extract_from_doi(doi)

        # Prepare and normalize paper data
        paper_data = self._build_paper_data(
            metadata,
            overrides={
                "paper_type": metadata.get("paper_type", "journal"),
                "doi": doi,
                "url": metadata.get("url", f"https://doi.org/{doi}"),
            },
        )

        # Add to database
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        return {"paper": paper, "pdf_path": None, "pdf_error": None}

    def add_manual_paper(self, title: str = "") -> Dict[str, Any]:
        """Add a paper manually with basic defaults."""
        try:
            # Create basic manual paper based on original implementation
            current_year = datetime.now().year
            paper_data = {
                "title": title if title.strip() else "Manually Added Paper",
                "abstract": "This paper was added manually via PaperCLI.",
                "year": current_year,
                "venue_full": "User Input",
                "venue_acronym": "UI",
                "paper_type": "journal",
                "notes": "Added manually - please update metadata using /edit",
            }

            # Normalize paper data for database storage
            paper_data = normalize_paper_data(paper_data)

            authors = ["Manual User"]
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            return {"paper": paper, "pdf_path": None, "pdf_error": None}

        except Exception as e:
            raise Exception(f"Failed to add manual paper: {str(e)}")

    def add_website_paper_async(self, url: str) -> Dict[str, Any]:
        """
        Add a paper from a website URL with HTML snapshot.

        This method snapshots the webpage, extracts metadata using LLM,
        and creates a paper entry with HTML snapshot (no PDF).

        Args:
            url: The URL of the website to snapshot

        Returns:
            Dictionary with paper object and snapshot information
        """
        try:
            # Get directories for snapshots
            pdf_dir = get_pdf_directory()
            data_dir = os.path.dirname(pdf_dir)
            html_snapshot_dir = os.path.join(data_dir, "html_snapshots")

            self.app._add_log(
                "website_paper_start", f"Starting website paper addition for: {url}"
            )

            # First, do a quick fetch to get the page title for the snapshot filename
            # We'll use a simple fetch to get the title before doing the full snapshot
            import requests
            from bs4 import BeautifulSoup

            try:
                response = requests.get(url, timeout=30)
                soup = BeautifulSoup(response.content, "html.parser")
                title_tag = soup.find("title")
                initial_title = (
                    title_tag.get_text(strip=True) if title_tag else "webpage"
                )
            except Exception as e:
                self.app._add_log(
                    "website_title_fetch_warning",
                    f"Could not pre-fetch title: {str(e)}, using 'webpage'",
                )
                initial_title = "webpage"

            # Snapshot the webpage using Playwright (HTML only, no PDF)
            webpage_service = WebpageSnapshotService(app=self.app)

            html_path, html_content = webpage_service.snapshot_webpage(
                url=url,
                title=initial_title,
                html_output_dir=html_snapshot_dir,
            )

            self.app._add_log(
                "website_snapshot_complete",
                f"HTML snapshot created: {os.path.basename(html_path)}",
            )

            # Extract metadata from the HTML content
            metadata = self.metadata_extractor.extract_from_webpage(url, html_content)

            # Convert absolute path to relative path for storage
            relative_html_path = os.path.relpath(html_path, html_snapshot_dir)

            # Build paper data (no PDF for websites)
            paper_data = self._build_paper_data(
                metadata,
                overrides={
                    "paper_type": "website",
                    "url": url,
                    "pdf_path": None,  # Websites don't have PDFs
                    "html_snapshot_path": relative_html_path,
                },
            )

            # Add to database
            authors = paper_data.get("authors", [])
            collections = []

            paper = self.paper_service.add_paper_from_metadata(
                paper_data, authors, collections
            )

            self.app._add_log(
                "website_paper_success",
                f"Website paper added: {paper.title} (ID={paper.id})",
            )

            return {
                "paper": paper,
                "html_path": html_path,
                "pdf_path": None,  # No PDF for websites
                "url": url,
            }

        except Exception as e:
            error_msg = f"Failed to add website paper: {str(e)}"
            self.app._add_log("website_paper_error", error_msg)
            raise Exception(error_msg)
