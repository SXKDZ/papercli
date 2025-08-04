"""Service for adding papers from various sources."""

import os
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from ..db.database import get_pdf_directory
from ..db.models import Paper
from .metadata import MetadataExtractor
from .paper import PaperService
from .system import SystemService
from .utils import normalize_paper_data


class AddPaperService:
    """Service for adding papers from various sources."""

    def __init__(
        self,
        paper_service: PaperService,
        metadata_extractor: MetadataExtractor,
        system_service: SystemService,
    ):
        """Initialize the add paper service."""
        self.paper_service = paper_service
        self.metadata_extractor = metadata_extractor
        self.system_service = system_service

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
        pdf_path, pdf_error = self.system_service.download_pdf(
            "arxiv", arxiv_id, pdf_dir, paper_data
        )

        return {"paper": paper, "pdf_path": pdf_path, "pdf_error": pdf_error}

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
        pdf_path, pdf_error = self.system_service.download_pdf(
            "openreview", openreview_id, pdf_dir, paper_data
        )

        return {"paper": paper, "pdf_path": pdf_path, "pdf_error": pdf_error}

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
            "pdf_path": pdf_path,
        }

        paper_data = normalize_paper_data(paper_data)

        # Extract normalized authors
        authors = paper_data.get("authors", [])
        collections = []

        paper = self.paper_service.add_paper_from_metadata(
            paper_data, authors, collections
        )

        return {"paper": paper, "pdf_path": pdf_path, "pdf_error": None}

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
