from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ng.db.database import get_pdf_directory
from ng.services.metadata import MetadataExtractor
from ng.services.paper import PaperService
from ng.services.system import SystemService
from ng.services.utils import normalize_paper_data

if TYPE_CHECKING:
    from ng.db.models import Paper


class AddPaperService:
    """Service for adding papers from various sources."""

    def __init__(
        self,
        paper_service: PaperService,
        metadata_extractor: MetadataExtractor,
        system_service: SystemService,
        app=None,
    ):
        """Initialize the add paper service."""
        self.paper_service = paper_service
        self.metadata_extractor = metadata_extractor
        self.system_service = system_service
        self.app = app

    def add_arxiv_paper(self, arxiv_id: str) -> Dict[str, Any]:
        """Add a paper from arXiv."""
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
            if self.app:
                self.app._add_log(
                    "pdf_download_start",
                    f"Starting PDF download for paper_id={paper_id}, source={source}, identifier={identifier}",
                )
                self.app._add_log(
                    "pdf_download_stage", "Stage 1/5: Initializing download process"
                )

            # Download PDF
            pdf_dir = get_pdf_directory()
            if self.app:
                self.app._add_log("pdf_download_debug", f"PDF directory: {pdf_dir}")
                self.app._add_log(
                    "pdf_download_debug",
                    f"Paper data keys: {list(paper_data.keys()) if paper_data else 'None'}",
                )
                self.app._add_log(
                    "pdf_download_stage",
                    "Stage 2/5: Calling SystemService to download PDF",
                )
                self.app._add_log(
                    "pdf_download_debug",
                    f"About to call system_service.download_pdf with source='{source}', identifier='{identifier}'",
                )

            try:
                pdf_path, pdf_error, download_duration = (
                    self.system_service.download_pdf(
                        source, identifier, pdf_dir, paper_data
                    )
                )
                if self.app:
                    self.app._add_log(
                        "pdf_download_debug",
                        f"system_service.download_pdf returned successfully",
                    )
            except Exception as e:
                if self.app:
                    self.app._add_log(
                        "pdf_download_exception",
                        f"Exception calling system_service.download_pdf: {str(e)}",
                    )
                    import traceback

                    self.app._add_log(
                        "pdf_download_traceback", f"Traceback: {traceback.format_exc()}"
                    )
                raise

            if self.app:
                self.app._add_log(
                    "pdf_download_result",
                    f"Download result: pdf_path='{pdf_path}', pdf_error='{pdf_error}', duration={download_duration:.2f}s",
                )

            if pdf_path and not pdf_error:
                if self.app:
                    self.app._add_log(
                        "pdf_download_success",
                        f"PDF downloaded successfully to: {pdf_path}",
                    )
                    self.app._add_log(
                        "pdf_download_stage",
                        "Stage 3/5: PDF download completed, processing path",
                    )

                # Convert absolute path to relative for storage
                relative_pdf_path = os.path.relpath(pdf_path, pdf_dir)
                if self.app:
                    self.app._add_log(
                        "pdf_download_debug", f"Relative PDF path: {relative_pdf_path}"
                    )
                    self.app._add_log(
                        "pdf_download_stage",
                        "Stage 4/5: Updating database with PDF path",
                    )

                # Update the paper with PDF path
                update_data = {"pdf_path": relative_pdf_path}
                if self.app:
                    self.app._add_log(
                        "pdf_update_start",
                        f"Updating paper {paper_id} with update_data: {update_data}",
                    )

                updated_paper, update_error = self.paper_service.update_paper(
                    paper_id, update_data
                )
                if self.app:
                    self.app._add_log(
                        "pdf_update_result",
                        f"Database update result: paper={updated_paper is not None}, error='{update_error}'",
                    )

                if update_error:
                    if self.app:
                        self.app._add_log(
                            "pdf_update_error",
                            f"Database update failed: {update_error}",
                        )
                    return {
                        "success": False,
                        "error": f"PDF downloaded but database update failed: {update_error}",
                    }

                if self.app:
                    self.app._add_log(
                        "pdf_download_stage",
                        "Stage 5/5: Process completed successfully",
                    )
                    self.app._add_log(
                        "pdf_download_complete",
                        f"Successfully updated paper {paper_id} with PDF path: {relative_pdf_path}",
                    )
                return {
                    "success": True,
                    "pdf_path": relative_pdf_path,
                    "paper": updated_paper,
                    "download_duration": download_duration,
                }
            else:
                error_msg = pdf_error or "Unknown PDF download error"
                if self.app:
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
            if self.app:
                import traceback

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

        return {"paper": paper, "pdf_path": None, "pdf_error": None}

    def add_openreview_paper(self, openreview_id: str) -> Dict[str, Any]:
        """Add a paper from OpenReview."""
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

    def add_pdf_paper(self, pdf_path: str) -> Dict[str, Any]:
        """Add a paper from local PDF file."""
        # Expand user path and resolve relative paths
        pdf_path = os.path.expanduser(pdf_path)
        pdf_path = os.path.abspath(pdf_path)

        if not os.path.exists(pdf_path):
            raise Exception(f"PDF file not found: {pdf_path}")

        if not pdf_path.lower().endswith(".pdf"):
            raise Exception(f"File is not a PDF: {pdf_path}")

        # Extract metadata from PDF
        metadata = self.metadata_extractor.extract_from_pdf(pdf_path)

        # Create paper data first for PDF filename generation
        temp_paper_data = {
            "title": metadata.get("title", "Unknown Title"),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
        }

        # Use new PDFService for enhanced copy functionality
        from ng.services.pdf import PDFService

        pdf_service = PDFService(app=self.app)

        # Copy PDF to collection directory with timing
        relative_pdf_path, pdf_error, copy_duration = (
            pdf_service.copy_local_pdf_to_collection(pdf_path, temp_paper_data)
        )

        if pdf_error:
            raise Exception(f"Failed to process PDF: {pdf_error}")

        # Prepare paper data
        paper_data = {
            "title": metadata.get("title", "Unknown Title"),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "unknown"),
            "doi": metadata.get("doi"),
            "url": metadata.get("url"),
            "pdf_path": relative_pdf_path,
        }

        paper_data = normalize_paper_data(paper_data)

        # Extract normalized authors
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        return {
            "paper": paper,
            "pdf_path": relative_pdf_path,
            "pdf_error": None,
            "copy_duration": copy_duration,
        }

    def add_bib_papers(self, bib_path: str) -> Tuple[List[Paper], List[str]]:
        """Add papers from .bib file."""
        # Expand user path and resolve relative paths
        bib_path = os.path.expanduser(bib_path)
        bib_path = os.path.abspath(bib_path)

        if not os.path.exists(bib_path):
            raise Exception(f"BibTeX file not found: {bib_path}")

        if not bib_path.lower().endswith((".bib", ".bibtex")):
            raise Exception(f"File is not a BibTeX file: {bib_path}")

        # Extract metadata from BibTeX file
        papers_metadata = self.metadata_extractor.extract_from_bibtex(bib_path)

        added_papers = []
        errors = []

        for metadata in papers_metadata:
            try:
                # Prepare paper data
                paper_data = {
                    "title": metadata.get("title", "Unknown Title"),
                    "abstract": metadata.get("abstract", ""),
                    "authors": metadata.get("authors", ""),
                    "year": metadata.get("year"),
                    "venue_full": metadata.get("venue_full", ""),
                    "venue_acronym": metadata.get("venue_acronym", ""),
                    "paper_type": metadata.get("paper_type", "unknown"),
                    "doi": metadata.get("doi"),
                    "url": metadata.get("url"),
                    "volume": metadata.get("volume"),
                    "issue": metadata.get("issue"),
                    "pages": metadata.get("pages"),
                }

                # Normalize paper data for database storage
                paper_data = normalize_paper_data(paper_data)

                # Add to database first
                authors = paper_data.get("authors", [])
                collections = []

                paper = self.paper_service.add_paper_from_metadata(
                    paper_data, authors, collections
                )

                # Try to download PDF if URL is provided and looks like a PDF
                if metadata.get("url"):
                    from ng.services.pdf import PDFService

                    pdf_service = PDFService(app=self.app)

                    try:
                        pdf_path, pdf_error, download_duration = (
                            pdf_service.download_pdf_from_website_url(
                                metadata["url"], paper_data
                            )
                        )

                        if pdf_path and not pdf_error:
                            # Convert to relative path and update paper
                            pdf_dir = get_pdf_directory()
                            relative_pdf_path = os.path.relpath(pdf_path, pdf_dir)

                            update_data = {"pdf_path": relative_pdf_path}
                            updated_paper, update_error = (
                                self.paper_service.update_paper(paper.id, update_data)
                            )

                            if not update_error and self.app:
                                summary = pdf_service.create_download_summary(
                                    pdf_path, download_duration
                                )
                                self.app.notify(
                                    f"PDF downloaded for '{paper_data['title'][:50]}...': {summary}",
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
        # Expand user path and resolve relative paths
        ris_path = os.path.expanduser(ris_path)
        ris_path = os.path.abspath(ris_path)

        if not os.path.exists(ris_path):
            raise Exception(f"RIS file not found: {ris_path}")

        if not ris_path.lower().endswith((".ris", ".txt")):
            raise Exception(f"File is not a RIS file: {ris_path}")

        # Extract metadata from RIS file
        papers_metadata = self.metadata_extractor.extract_from_ris(ris_path)

        added_papers = []
        errors = []

        for metadata in papers_metadata:
            try:
                # Prepare paper data
                paper_data = {
                    "title": metadata.get("title", "Unknown Title"),
                    "abstract": metadata.get("abstract", ""),
                    "authors": metadata.get("authors", ""),
                    "year": metadata.get("year"),
                    "venue_full": metadata.get("venue_full", ""),
                    "venue_acronym": metadata.get("venue_acronym", ""),
                    "paper_type": metadata.get("paper_type", "unknown"),
                    "doi": metadata.get("doi"),
                    "url": metadata.get("url"),
                    "volume": metadata.get("volume"),
                    "issue": metadata.get("issue"),
                    "pages": metadata.get("pages"),
                }

                # Normalize paper data for database storage
                paper_data = normalize_paper_data(paper_data)

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

        # Prepare paper data
        paper_data = {
            "title": metadata.get("title", "Unknown Title"),
            "abstract": metadata.get("abstract", ""),
            "authors": metadata.get("authors", ""),
            "year": metadata.get("year"),
            "venue_full": metadata.get("venue_full", ""),
            "venue_acronym": metadata.get("venue_acronym", ""),
            "paper_type": metadata.get("paper_type", "journal"),
            "doi": doi,
            "url": metadata.get("url", f"https://doi.org/{doi}"),
            "volume": metadata.get("volume"),
            "issue": metadata.get("issue"),
            "pages": metadata.get("pages"),
        }
        paper_data = normalize_paper_data(paper_data)

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
