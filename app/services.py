"""
Service classes for PaperCLI business logic.
"""

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import threading
import traceback
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import partial
from typing import Any, Dict, List, Optional

import bibtexparser
import PyPDF2
import pyperclip
import requests
import rispy
from fuzzywuzzy import fuzz
from openai import OpenAI
from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.containers import Float
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Dialog, TextArea
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import joinedload
from titlecase import titlecase

from .database import get_db_manager, get_db_session, get_pdf_directory
from .models import Author, Collection, Paper, PaperAuthor


def fix_broken_lines(text: str) -> str:
    """Fix broken lines in text - join lines that are not proper sentence endings."""
    if not text:
        return text
    # Join lines unless next line starts with capital letter
    text = re.sub(r"\n(?![A-Z])", " ", text)
    # Normalize multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compare_extracted_metadata_with_paper(extracted_data, paper, paper_service=None):
    """
    Compare extracted PDF metadata with current paper data and return list of changes.

    Args:
        extracted_data: Dictionary of extracted metadata from PDF
        paper: Paper object or paper data dict
        paper_service: Optional PaperService to fetch fresh paper data

    Returns:
        List of change strings in format "field_name: 'old_value' → 'new_value'"
    """
    # Get fresh paper data if we have a paper ID and service
    if paper_service and hasattr(paper, "id"):
        fresh_paper = paper_service.get_paper_by_id(paper.id)
        if fresh_paper:
            paper = fresh_paper

    field_mapping = {
        "title": "title",
        "authors": "author_names",
        "abstract": "abstract",
        "year": "year",
        "venue_full": "venue_full",
        "venue_acronym": "venue_acronym",
        "doi": "doi",
        "url": "url",
        "category": "category",
    }

    changes = []

    for extracted_field, paper_field in field_mapping.items():
        if extracted_field in extracted_data and extracted_data[extracted_field]:
            value = extracted_data[extracted_field]

            # Convert extracted value to string format
            if extracted_field == "authors" and isinstance(value, list):
                value = ", ".join(value)
            elif extracted_field == "year" and isinstance(value, int):
                value = str(value)

            # Get current value from paper
            if paper_field == "author_names":
                current_value = ""
                try:
                    if (
                        hasattr(paper, "paper_authors")
                        and paper.paper_authors is not None
                    ):
                        # Paper model object - use paper_authors to avoid lazy loading issues
                        current_value = (
                            ", ".join(
                                [
                                    paper_author.author.full_name
                                    for paper_author in paper.paper_authors
                                ]
                            )
                            if paper.paper_authors
                            else ""
                        )
                    elif hasattr(paper, "authors") and paper.authors is not None:
                        # Paper model object with authors relationship
                        current_value = (
                            ", ".join([author.full_name for author in paper.authors])
                            if paper.authors
                            else ""
                        )
                    elif hasattr(paper, "get"):
                        # Paper data dict (from edit dialog)
                        authors = paper.get("authors", [])
                        if isinstance(authors, list):
                            # Try both 'full_name' and 'name' attributes for compatibility
                            current_value = ", ".join(
                                [
                                    getattr(a, "full_name", getattr(a, "name", str(a)))
                                    for a in authors
                                ]
                            )
                        else:
                            current_value = str(authors) if authors else ""
                except (AttributeError, Exception) as e:
                    # If we can't access the authors due to session issues, skip this comparison
                    if hasattr(paper, "title"):
                        paper_title = getattr(paper, "title", "Unknown")
                    else:
                        paper_title = str(paper)[:50]
                    print(
                        f"[Session Error] Could not access authors for paper '{paper_title}': {e}"
                    )
                    current_value = ""
            else:
                # Regular field access
                if hasattr(paper, paper_field):
                    # Paper model object
                    current_value = getattr(paper, paper_field, "") or ""
                else:
                    # Paper data dict
                    current_value = paper.get(paper_field, "") or ""

                # Convert to string for comparison
                if current_value is None:
                    current_value = ""
                else:
                    current_value = str(current_value)

            # Compare and record changes
            if str(value) != str(current_value):
                changes.append(f"{paper_field}: '{current_value}' → '{value}'")

    return changes


class PaperService:
    """Service for managing papers."""

    def get_all_papers(self) -> List[Paper]:
        """Get all papers ordered by added date (newest first)."""
        with get_db_session() as session:

            # Eagerly load relationships to avoid detached instance errors
            papers = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .order_by(Paper.added_date.desc())
                .all()
            )

            # Force load all relationships while in session
            for paper in papers:
                _ = paper.paper_authors  # Force load paper_authors
                _ = paper.collections  # Force load collections

            # Expunge all objects to make them detached but accessible
            session.expunge_all()

            return papers

    def get_paper_by_id(self, paper_id: int) -> Optional[Paper]:
        """Get paper by ID."""
        with get_db_session() as session:

            paper = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .filter(Paper.id == paper_id)
                .first()
            )

            if paper:
                # Force load relationships while in session
                _ = paper.paper_authors
                # Force load authors within each paper_author
                for paper_author in paper.paper_authors:
                    _ = paper_author.author
                _ = paper.collections

                # Expunge to make detached but accessible
                session.expunge_all()

            return paper

    def add_paper(self, paper_data: Dict[str, Any]) -> Paper:
        """Add a new paper."""
        with get_db_session() as session:
            paper = Paper(**paper_data)
            session.add(paper)
            session.commit()
            session.refresh(paper)
            return paper

    def update_paper(
        self, paper_id: int, paper_data: Dict[str, Any]
    ) -> tuple[Optional[Paper], str]:
        """Update an existing paper.

        Returns:
            tuple[Optional[Paper], str]: (updated_paper, error_message)
            If successful: (paper, "")
            If error: (None, error_message) or (paper, pdf_error_message)
        """
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if not paper:
                return None, f"Paper with ID {paper_id} not found"

            pdf_error = ""

            try:
                # Handle PDF path processing if present
                if "pdf_path" in paper_data and paper_data["pdf_path"]:
                    pdf_manager = PDFManager()

                    # Create paper data for filename generation
                    current_paper_data = {
                        "title": paper_data.get("title", paper.title),
                        "authors": (
                            [author.full_name for author in paper.get_ordered_authors()]
                            if paper.paper_authors
                            else []
                        ),
                        "year": paper_data.get("year", paper.year),
                    }

                    new_pdf_path, error = pdf_manager.process_pdf_path(
                        paper_data["pdf_path"], current_paper_data, paper.pdf_path
                    )

                    if error:
                        pdf_error = f"PDF processing failed: {error}"
                        # Remove pdf_path from update data to prevent invalid path from being saved
                        paper_data.pop("pdf_path")
                        # Return immediately with the PDF error
                        return None, pdf_error
                    else:
                        paper_data["pdf_path"] = new_pdf_path

                # Handle relationships by merging the detached objects from the dialog
                # into the current session. This avoids primary key conflicts.
                if "authors" in paper_data:
                    authors = paper_data.pop("authors")
                    # Delete existing paper_authors manually to avoid cascade issues
                    session.query(PaperAuthor).filter(
                        PaperAuthor.paper_id == paper.id
                    ).delete()
                    session.flush()  # Ensure deletions are committed before adding new ones

                    # Add authors in order with position tracking
                    for position, author in enumerate(authors):
                        merged_author = session.merge(author)
                        paper_author = PaperAuthor(
                            paper_id=paper.id, author=merged_author, position=position
                        )
                        session.add(paper_author)

                if "collections" in paper_data:
                    collections = paper_data.pop("collections")
                    paper.collections = [
                        session.merge(collection) for collection in collections
                    ]

                # Update remaining attributes
                for key, value in paper_data.items():
                    if hasattr(paper, key):
                        setattr(paper, key, value)

                paper.modified_date = datetime.now()
                session.commit()
                session.refresh(paper)

                # Force load relationships before expunging
                _ = paper.paper_authors  # Force load paper_authors
                for pa in paper.paper_authors:
                    _ = pa.author  # Force load each author
                    _ = pa.position  # Force load position
                _ = paper.collections  # Force load collections

                # Expunge to follow the detached object pattern used elsewhere in the app
                session.expunge(paper)

                return paper, pdf_error

            except Exception as e:
                session.rollback()
                return None, f"Failed to update paper: {str(e)}"

    def delete_paper(self, paper_id: int) -> bool:
        """Delete a paper."""
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if paper:
                session.delete(paper)
                session.commit()
                return True
            return False

    def delete_papers(self, paper_ids: List[int]) -> int:
        """Delete multiple papers. Returns count of deleted papers."""
        with get_db_session() as session:
            papers_to_delete = (
                session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
            )
            if not papers_to_delete:
                return 0

            for paper in papers_to_delete:
                if paper.pdf_path and os.path.exists(paper.pdf_path):
                    try:
                        os.remove(paper.pdf_path)
                    except Exception:
                        # Log this error, but don't prevent db deletion
                        pass
                session.delete(paper)

            session.commit()
            return len(papers_to_delete)

    def add_paper_from_metadata(
        self,
        paper_data: Dict[str, Any],
        authors: List[str],
        collections: List[str] = None,
    ) -> Paper:
        """Add paper with authors and collections."""
        with get_db_session() as session:

            # Check for existing paper by preprint ID, DOI, or title
            existing_paper = None
            if paper_data.get("preprint_id"):
                existing_paper = (
                    session.query(Paper)
                    .filter(Paper.preprint_id == paper_data["preprint_id"])
                    .first()
                )
            elif paper_data.get("doi"):
                existing_paper = (
                    session.query(Paper).filter(Paper.doi == paper_data["doi"]).first()
                )
            elif paper_data.get("title"):
                existing_paper = (
                    session.query(Paper)
                    .filter(Paper.title == paper_data["title"])
                    .first()
                )

            if existing_paper:
                raise Exception(
                    f"Paper already exists in database (ID: {existing_paper.id})"
                )

            # Create paper
            paper = Paper()
            for key, value in paper_data.items():
                if hasattr(paper, key) and value is not None:
                    setattr(paper, key, value)

            session.add(paper)
            session.flush()  # Get the paper ID without committing

            # Add authors with position tracking
            for position, author_name in enumerate(authors):
                author = (
                    session.query(Author)
                    .filter(Author.full_name == author_name)
                    .first()
                )
                if not author:
                    author = Author(full_name=author_name)
                    session.add(author)
                    session.flush()  # Ensure author has an ID

                paper_author = PaperAuthor(
                    paper=paper, author=author, position=position
                )
                session.add(paper_author)

            # Add collections
            if collections:
                for collection_name in collections:
                    collection = (
                        session.query(Collection)
                        .filter(Collection.name == collection_name)
                        .first()
                    )
                    if not collection:
                        collection = Collection(name=collection_name)
                        session.add(collection)
                        session.flush()  # Ensure collection has an ID

                    # Double-check for existing association in the database

                    existing_association = session.execute(
                        text(
                            "SELECT 1 FROM paper_collections WHERE paper_id = :paper_id AND collection_id = :collection_id"
                        ),
                        {"paper_id": paper.id, "collection_id": collection.id},
                    ).first()

                    if not existing_association and collection not in paper.collections:
                        paper.collections.append(collection)

            session.commit()
            session.refresh(paper)

            # Create a new query with eager loading to get a properly attached instance
            paper_with_relationships = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .filter(Paper.id == paper.id)
                .first()
            )

            # Force load all relationships while still in session
            _ = paper_with_relationships.paper_authors
            _ = paper_with_relationships.collections

            # Expunge to make detached but accessible
            session.expunge_all()

            return paper_with_relationships


class AuthorService:
    """Service for managing authors."""

    def get_or_create_author(self, full_name: str, **kwargs) -> Author:
        """Get existing author or create new one."""
        with get_db_session() as session:
            author = session.query(Author).filter(Author.full_name == full_name).first()
            if not author:
                author = Author(full_name=full_name, **kwargs)
                session.add(author)
                session.commit()
                session.refresh(author)
            return author


class CollectionService:
    """Service for managing collections."""

    def get_all_collections(self) -> List[Collection]:
        """Get all collections with their papers loaded."""
        with get_db_session() as session:
            collections = session.query(Collection).order_by(Collection.name).all()
            # Force load all attributes and relationships
            for collection in collections:
                _ = collection.name  # Ensure name is loaded
                _ = collection.description  # Ensure description is loaded
                _ = collection.papers  # Force load papers relationship
                # Also force load paper details to prevent lazy loading issues
                for paper in collection.papers:
                    _ = paper.title
                    _ = paper.paper_authors  # Force load paper_authors too
            session.expunge_all()
            return collections

    def get_or_create_collection(
        self, name: str, description: str = None
    ) -> Collection:
        """Get existing collection or create new one."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter(Collection.name == name).first()
            )
            if not collection:
                collection = Collection(name=name, description=description)
                session.add(collection)
                session.commit()
                session.refresh(collection)
            return collection

    def manage_papers_in_collection(
        self, paper_ids: List[int], collection_name: str, operation: str
    ) -> tuple[int, list[str]]:
        """Add or remove papers from a collection.

        Args:
            paper_ids: List of paper IDs to process
            collection_name: Name of the collection
            operation: "add" or "remove"

        Returns:
            tuple[int, list[str]]: (count, errors) where count is papers processed and errors is list of error messages
        """
        if operation not in ["add", "remove"]:
            return 0, [f"Invalid operation: {operation}. Use 'add' or 'remove'."]

        if not paper_ids:
            return 0, ["No paper IDs provided."]

        with get_db_session() as session:
            # Get or create collection for add operation
            collection = (
                session.query(Collection)
                .filter(Collection.name == collection_name)
                .first()
            )

            if not collection:
                if operation == "add":
                    collection = Collection(name=collection_name)
                    session.add(collection)
                    session.flush()
                else:
                    return 0, [f"Collection '{collection_name}' not found."]

            papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
            if not papers:
                return 0, ["No valid papers found with provided IDs."]

            count = 0
            errors = []

            for paper in papers:
                if operation == "add":
                    if collection not in paper.collections:
                        paper.collections.append(collection)
                        count += 1
                else:  # remove
                    if collection in paper.collections:
                        paper.collections.remove(collection)
                        count += 1
                    else:
                        errors.append(
                            f"Paper '{paper.title[:30]}...' not in collection: {collection_name}"
                        )

            if count > 0:
                session.commit()

            return count, errors

    def add_paper_to_collection(self, paper_id: int, collection_name: str) -> bool:
        """Add single paper to collection."""
        count, errors = self.manage_papers_in_collection(
            [paper_id], collection_name, "add"
        )
        return count > 0

    def add_papers_to_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> int:
        """Add multiple papers to collection."""
        count, _ = self.manage_papers_in_collection(paper_ids, collection_name, "add")
        return count

    def remove_papers_from_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> tuple[int, list[str]]:
        """Remove multiple papers from collection."""
        return self.manage_papers_in_collection(paper_ids, collection_name, "remove")

    def remove_paper_from_collection(self, paper_id: int, collection_name: str) -> bool:
        """Remove single paper from collection."""
        count, _ = self.manage_papers_in_collection(
            [paper_id], collection_name, "remove"
        )
        return count > 0

    def update_collection_name(self, old_name: str, new_name: str) -> bool:
        """Update collection name."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter(Collection.name == old_name).first()
            )
            if not collection:
                return False

            # Check if new name already exists
            existing = (
                session.query(Collection).filter(Collection.name == new_name).first()
            )
            if existing and existing.id != collection.id:
                return False

            collection.name = new_name
            session.commit()
            return True

    def create_collection(self, name: str, description: str = None) -> Collection:
        """Create a new collection."""
        with get_db_session() as session:
            # Check if collection already exists
            existing = session.query(Collection).filter(Collection.name == name).first()
            if existing:
                return None

            collection = Collection(name=name, description=description)
            session.add(collection)
            session.commit()
            session.refresh(collection)

            # Force load attributes before expunging
            _ = collection.name
            _ = collection.description
            _ = collection.papers
            session.expunge(collection)
            return collection

    def purge_empty_collections(self) -> int:
        """Delete all collections that have no papers. Returns number of collections deleted."""
        with get_db_session() as session:
            # Find collections with no papers
            empty_collections = (
                session.query(Collection).filter(~Collection.papers.any()).all()
            )

            count = len(empty_collections)

            # Delete empty collections
            for collection in empty_collections:
                session.delete(collection)

            session.commit()
            return count


class SearchService:
    """Service for searching and filtering papers."""

    def search_papers(self, query: str, fields: List[str] = None) -> List[Paper]:
        """Search papers by query in specified fields with fuzzy matching."""
        if fields is None:
            fields = ["title", "abstract", "authors", "venue"]

        with get_db_session() as session:
            conditions = []

            if "title" in fields:
                conditions.append(Paper.title.ilike(f"%{query}%"))
            if "abstract" in fields:
                conditions.append(Paper.abstract.ilike(f"%{query}%"))
            if "venue" in fields:
                conditions.append(
                    or_(
                        Paper.venue_full.ilike(f"%{query}%"),
                        Paper.venue_acronym.ilike(f"%{query}%"),
                    )
                )
            if "notes" in fields:
                conditions.append(Paper.notes.ilike(f"%{query}%"))

            # Search in authors requires join
            if "authors" in fields:
                papers_by_author = (
                    session.query(Paper)
                    .join(Paper.paper_authors)
                    .join(PaperAuthor.author)
                    .filter(Author.full_name.ilike(f"%{query}%"))
                    .all()
                )
                # Add author search results
                paper_ids = [p.id for p in papers_by_author]
                if paper_ids:
                    conditions.append(Paper.id.in_(paper_ids))

            if conditions:
                papers = (
                    session.query(Paper)
                    .options(
                        joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                        joinedload(Paper.collections),
                    )
                    .filter(or_(*conditions))
                    .order_by(Paper.added_date.desc())
                    .all()
                )

                # Force load relationships
                for paper in papers:
                    _ = paper.paper_authors
                    _ = paper.collections

                # Expunge to make detached but accessible
                session.expunge_all()
                return papers
            return []

    def fuzzy_search_papers(self, query: str, threshold: int = 60) -> List[Paper]:
        """Fuzzy search papers using edit distance."""
        with get_db_session() as session:
            # Eagerly load all papers with relationships
            all_papers = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .all()
            )

            scored_papers = []

            for paper in all_papers:
                # Force load relationships while in session
                _ = paper.paper_authors
                _ = paper.collections

                # Calculate fuzzy match scores
                title_score = fuzz.partial_ratio(query.lower(), paper.title.lower())
                ordered_authors = paper.get_ordered_authors()
                author_score = max(
                    [
                        fuzz.partial_ratio(query.lower(), author.full_name.lower())
                        for author in ordered_authors
                    ]
                    or [0]
                )
                venue_score = max(
                    [
                        (
                            fuzz.partial_ratio(query.lower(), paper.venue_full.lower())
                            if paper.venue_full
                            else 0
                        ),
                        (
                            fuzz.partial_ratio(
                                query.lower(), paper.venue_acronym.lower()
                            )
                            if paper.venue_acronym
                            else 0
                        ),
                    ]
                )

                # Use the highest score
                max_score = max(title_score, author_score, venue_score)

                if max_score >= threshold:
                    scored_papers.append((paper, max_score))

            # Sort by score (highest first)
            scored_papers.sort(key=lambda x: x[1], reverse=True)

            # Expunge to make detached but accessible
            session.expunge_all()
            return [paper for paper, score in scored_papers]

    def filter_papers(self, filters: Dict[str, Any]) -> List[Paper]:
        """Filter papers by various criteria."""
        with get_db_session() as session:
            query = session.query(Paper).options(
                joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                joinedload(Paper.collections),
            )

            if "year" in filters:
                query = query.filter(Paper.year == filters["year"])

            if "year_range" in filters:
                start, end = filters["year_range"]
                query = query.filter(and_(Paper.year >= start, Paper.year <= end))

            if "paper_type" in filters:
                query = query.filter(Paper.paper_type == filters["paper_type"])

            if "venue" in filters:
                query = query.filter(
                    or_(
                        Paper.venue_full.ilike(f'%{filters["venue"]}%'),
                        Paper.venue_acronym.ilike(f'%{filters["venue"]}%'),
                    )
                )

            if "collection" in filters:
                query = query.join(Paper.collections).filter(
                    Collection.name == filters["collection"]
                )

            if "author" in filters:
                query = (
                    query.join(Paper.paper_authors)
                    .join(PaperAuthor.author)
                    .filter(Author.full_name.ilike(f'%{filters["author"]}%'))
                )

            papers = query.order_by(Paper.added_date.desc()).all()

            # Force load relationships while in session
            for paper in papers:
                _ = paper.paper_authors
                _ = paper.collections

            # Expunge to make detached but accessible
            session.expunge_all()
            return papers


class MetadataExtractor:
    """Service for extracting metadata from various sources."""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def extract_from_arxiv(self, arxiv_id: str) -> Dict[str, Any]:
        """Extract metadata from arXiv."""
        # Clean arXiv ID
        arxiv_id = re.sub(r"arxiv[:\s]*", "", arxiv_id, flags=re.IGNORECASE)
        arxiv_id = re.sub(r"[^\d\.]", "", arxiv_id)

        try:
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)

            # Define namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # Find the entry
            entry = root.find(".//atom:entry", ns)
            if entry is None:
                raise Exception("Paper not found on arXiv")

            # Extract title
            title_elem = entry.find("atom:title", ns)
            title = (
                title_elem.text.strip() if title_elem is not None else "Unknown Title"
            )
            # Fix broken lines and apply titlecase to arXiv titles
            title = fix_broken_lines(title)
            title = titlecase(title)

            # Extract abstract
            summary_elem = entry.find("atom:summary", ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else ""
            # Fix broken lines in abstract
            abstract = fix_broken_lines(abstract)

            # Extract authors
            authors = []
            for author in entry.findall("atom:author", ns):
                name_elem = author.find("atom:name", ns)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())

            # Extract publication date
            published_elem = entry.find("atom:published", ns)
            year = None
            if published_elem is not None:
                published_date = published_elem.text
                year_match = re.search(r"(\d{4})", published_date)
                if year_match:
                    year = int(year_match.group(1))

            # Extract arXiv category
            category = None
            category_elem = entry.find("atom:category", ns)
            if category_elem is not None:
                category = category_elem.get("term")

            # Extract DOI if available
            doi = None
            doi_elem = entry.find("atom:id", ns)
            if doi_elem is not None:
                doi_match = re.search(r"doi:(.+)", doi_elem.text)
                if doi_match:
                    doi = doi_match.group(1)

            return {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "preprint_id": f"arXiv {arxiv_id}",  # Store as "arXiv 2505.15134"
                "category": category,
                "doi": doi,
                "paper_type": "preprint",
                "venue_full": "arXiv",
                "venue_acronym": None,  # No acronym for arXiv papers
            }

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch arXiv metadata: {e}")
        except ET.ParseError as e:
            raise Exception(f"Failed to parse arXiv response: {e}")

    def extract_from_dblp(self, dblp_url: str) -> Dict[str, Any]:
        """Extract metadata from DBLP URL using BibTeX endpoint and LLM processing."""
        try:
            # Convert DBLP HTML URL to BibTeX URL
            bib_url = self._convert_dblp_url_to_bib(dblp_url)

            # Fetch BibTeX data
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(bib_url, headers=headers, timeout=30)
            response.raise_for_status()

            bibtex_content = response.text.strip()
            if not bibtex_content:
                raise Exception("Empty BibTeX response")

            # Parse BibTeX using bibtexparser
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_database = bibtexparser.loads(bibtex_content, parser=parser)

            if not bib_database.entries:
                raise Exception("No entries found in BibTeX data")

            entry = bib_database.entries[0]  # Take the first entry

            # Get venue field based on entry type
            venue_field = ""
            paper_type = "conference"
            if "booktitle" in entry:
                venue_field = entry["booktitle"]
                paper_type = "conference"
            elif "journal" in entry:
                venue_field = entry["journal"]
                paper_type = "journal"

            # Extract venue names using LLM
            venue_info = self._extract_venue_with_llm(venue_field)

            # Parse authors
            authors = []
            if "author" in entry:
                # Split by 'and' and clean up, handling multiline authors
                author_text = re.sub(
                    r"\s+", " ", entry["author"]
                )  # Normalize whitespace
                for author in author_text.split(" and "):
                    author = author.strip()
                    if author:
                        authors.append(author)

            # Extract year
            year = None
            if "year" in entry:
                try:
                    year = int(entry["year"])
                except ValueError:
                    pass

            # Extract and clean title
            title = entry.get("title", "Unknown Title")
            title = fix_broken_lines(title)  # Fix any line breaks in title
            title = titlecase(title)  # Apply title case

            # Extract and clean abstract if present (though DBLP usually doesn't have abstracts)
            abstract = ""
            if "abstract" in entry:
                abstract = fix_broken_lines(entry["abstract"])

            # Build result
            result = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "venue_full": venue_info.get("venue_full", venue_field),
                "venue_acronym": venue_info.get("venue_acronym", ""),
                "paper_type": paper_type,
                "url": entry.get(
                    "url", dblp_url
                ),  # Use BibTeX URL if available, fallback to DBLP URL
                "pages": entry.get("pages"),
                "doi": entry.get("doi"),
                "volume": entry.get("volume"),
                "issue": entry.get("number"),
            }

            return result

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch DBLP metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process DBLP metadata: {e}")

    def _convert_dblp_url_to_bib(self, dblp_url: str) -> str:
        """Convert DBLP HTML URL to BibTeX URL."""
        # Handle both .html and regular DBLP URLs
        if ".html" in dblp_url:
            # Remove .html and any query parameters, then add .bib
            base_url = dblp_url.split(".html")[0]
            bib_url = f"{base_url}.bib?param=1"
        else:
            # Direct DBLP record URL
            bib_url = f"{dblp_url}.bib?param=1"

        return bib_url

    def _extract_venue_with_llm(self, venue_field: str) -> Dict[str, str]:
        """Extract venue name and acronym using LLM."""
        if not venue_field:
            return {"venue_full": "", "venue_acronym": ""}

        # Initialize chat service if not available
        client = OpenAI()

        try:
            prompt = f"""Given this conference/journal venue field from a DBLP BibTeX entry: "{venue_field}"

Please extract:
1. venue_full: The full venue name following these guidelines:
   - For journals: Use full journal name (e.g., "Journal of Chemical Information and Modeling")
   - For conferences: Use full name without "Proceedings of" or ordinal numbers (e.g., "International Conference on Machine Learning" for Proceedings of the 41st International Conference on Machine Learning)
2. venue_acronym: The abbreviation following these guidelines:
   - For journals: Use ISO 4 abbreviated format with periods (e.g., "J. Chem. Inf. Model." for Journal of Chemical Information and Modeling)
   - For conferences: Use common name (e.g., "NeurIPS" for Conference on Neural Information Processing Systems, not "NIPS")

Respond in this exact JSON format:
{{"venue_full": "...", "venue_acronym": "..."}} """

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts venue information from academic paper titles.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.1,
            )

            response_text = response.choices[0].message.content.strip()

            # Clean up markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            response_text = response_text.strip()

            # Try to parse JSON response
            try:
                venue_info = json.loads(response_text)
                return {
                    "venue_full": venue_info.get("venue_full", venue_field),
                    "venue_acronym": venue_info.get("venue_acronym", ""),
                }
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                return {
                    "venue_full": venue_field,
                    "venue_acronym": self._extract_acronym_fallback(venue_field),
                }

        except Exception as e:
            # Fallback on any error
            return {
                "venue_full": venue_field,
                "venue_acronym": self._extract_acronym_fallback(venue_field),
            }

    def _extract_acronym_fallback(self, venue_field: str) -> str:
        """Fallback method to extract acronym without LLM."""
        if not venue_field:
            return ""

        # Common conference acronyms
        acronym_map = {
            "international conference on machine learning": "ICML",
            "neural information processing systems": "NeurIPS",
            "international conference on learning representations": "ICLR",
            "ieee conference on computer vision and pattern recognition": "CVPR",
            "international conference on computer vision": "ICCV",
            "european conference on computer vision": "ECCV",
            "conference on empirical methods in natural language processing": "EMNLP",
            "annual meeting of the association for computational linguistics": "ACL",
            "international joint conference on artificial intelligence": "IJCAI",
            "aaai conference on artificial intelligence": "AAAI",
        }

        venue_lower = venue_field.lower()
        for full_name, acronym in acronym_map.items():
            if full_name in venue_lower:
                return acronym

        # Extract first letters of significant words
        words = re.findall(r"\b[A-Z][a-z]*", venue_field)
        if words:
            return "".join(word[0].upper() for word in words[:4])

        return ""

    def extract_from_openreview(self, openreview_id: str) -> Dict[str, Any]:
        """Extract metadata from OpenReview paper ID."""
        try:
            # Clean OpenReview ID - extract just the ID part
            if openreview_id.startswith("https://openreview.net/forum?id="):
                openreview_id = openreview_id.split("id=")[1]
            elif openreview_id.startswith("https://openreview.net/pdf?id="):
                openreview_id = openreview_id.split("id=")[1]

            # Remove any additional parameters
            openreview_id = openreview_id.split("&")[0].split("#")[0]

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            # Try newer API v2 format first
            api_url_v2 = f"https://api2.openreview.net/notes?forum={openreview_id}&limit=1000&details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags"

            try:
                response = requests.get(api_url_v2, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                if data.get("notes") and len(data["notes"]) > 0:
                    return self._parse_openreview_v2_response(data, openreview_id)
            except (requests.RequestException, KeyError):
                pass  # Fall back to older API format

            # Try older API format if v2 fails
            api_url_v1 = f"https://api.openreview.net/notes?forum={openreview_id}&trash=true&details=replyCount%2Cwritable%2Crevisions%2Coriginal%2Coverwriting%2Cinvitation%2Ctags&limit=1000&offset=0"

            response = requests.get(api_url_v1, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data.get("notes") or len(data["notes"]) == 0:
                raise Exception("Paper not found on OpenReview")

            return self._parse_openreview_v1_response(data, openreview_id)

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch OpenReview metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process OpenReview metadata: {e}")

    def _parse_openreview_v2_response(
        self, data: Dict[str, Any], openreview_id: str
    ) -> Dict[str, Any]:
        """Parse OpenReview API v2 response."""
        # Find the main submission note (where id equals forum)
        note = None
        for n in data["notes"]:
            if n.get("id") == n.get("forum"):
                note = n
                break

        if not note:
            # Fallback to first note if main submission not found
            note = data["notes"][0]

        content = note.get("content", {})

        # Extract title
        title = content.get("title", {}).get("value", "Unknown Title")
        title = fix_broken_lines(title)
        title = titlecase(title)

        # Extract abstract
        abstract = content.get("abstract", {}).get("value", "")
        if abstract:
            abstract = fix_broken_lines(abstract)

        # Extract authors
        authors = []
        authors_data = content.get("authors", {}).get("value", [])
        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]

        # Extract venue information using LLM
        venue_info = content.get("venue", {}).get("value", "")
        venue_data = self._extract_venue_with_llm(venue_info)

        # Extract year from venue or other sources
        year = None
        if venue_info:
            year_match = re.search(r"(\d{4})", venue_info)
            if year_match:
                year = int(year_match.group(1))

        return {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "venue_full": venue_data.get("venue_full", venue_info),
            "venue_acronym": venue_data.get("venue_acronym", ""),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }

    def _parse_openreview_v1_response(
        self, data: Dict[str, Any], openreview_id: str
    ) -> Dict[str, Any]:
        """Parse OpenReview API v1 response."""
        # Find the main submission note (where id equals forum)
        note = None
        for n in data["notes"]:
            if n.get("id") == n.get("forum"):
                note = n
                break

        if not note:
            # Fallback to first note if main submission not found
            note = data["notes"][0]

        content = note.get("content", {})

        # Extract title (v1 format may have direct string values)
        title = content.get("title", "Unknown Title")
        if isinstance(title, dict):
            title = title.get("value", "Unknown Title")
        title = fix_broken_lines(title)
        title = titlecase(title)

        # Extract abstract
        abstract = content.get("abstract", "")
        if isinstance(abstract, dict):
            abstract = abstract.get("value", "")
        if abstract:
            abstract = fix_broken_lines(abstract)

        # Extract authors
        authors = []
        authors_data = content.get("authors", [])
        if isinstance(authors_data, dict):
            authors_data = authors_data.get("value", [])
        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]

        # Extract venue information using LLM
        venue_info = content.get("venue", "")
        if isinstance(venue_info, dict):
            venue_info = venue_info.get("value", "")
        venue_data = self._extract_venue_with_llm(venue_info)

        # Extract year from venue or other sources
        year = None
        if venue_info:
            year_match = re.search(r"(\d{4})", venue_info)
            if year_match:
                year = int(year_match.group(1))

        return {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "venue_full": venue_data.get("venue_full", venue_info),
            "venue_acronym": venue_data.get("venue_acronym", ""),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }

    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Extract metadata from PDF file using LLM analysis of first two pages."""
        try:

            # Extract text from first two pages
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if len(pdf_reader.pages) == 0:
                    raise Exception("PDF file is empty")

                # Extract text from first 1-2 pages
                pages_to_extract = min(2, len(pdf_reader.pages))
                text_content = ""

                for i in range(pages_to_extract):
                    page = pdf_reader.pages[i]
                    text_content += page.extract_text() + "\n\n"

                if not text_content.strip():
                    raise Exception("Could not extract text from PDF")

            # Use LLM to extract metadata
            client = OpenAI()

            prompt = f"""
            Extract the following metadata from this academic paper text. Return your response as a JSON object with these exact keys:
            
            - title: The paper title
            - authors: List of author names as strings
            - abstract: The abstract text (if available)
            - year: Publication year as integer (if available)
            - venue_full: Full venue/conference/journal name following these guidelines:
              * For journals: Use full journal name (e.g., "Journal of Chemical Information and Modeling")
              * For conferences: Use full name without "Proceedings of" or ordinal numbers (e.g., "International Conference on Machine Learning" for Proceedings of the 41st International Conference on Machine Learning)
            - venue_acronym: Venue abbreviation following these guidelines:
              * For journals: Use ISO 4 abbreviated format with periods (e.g., "J. Chem. Inf. Model." for Journal of Chemical Information and Modeling)
              * For conferences: Use common name (e.g., "NeurIPS" for Conference on Neural Information Processing Systems, not "NIPS")
            - paper_type: One of "conference", "journal", "workshop", "preprint", "other"
            - doi: DOI (if available)
            - url: URL of the PDF to the paper itself mentioned (if available, not the link to the supplementary material or the code repository)
            - category: Subject category like "cs.LG" (if available)
            
            If any field is not available, use null for that field.
            
            Paper text:
            {text_content[:8000]}
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert at extracting metadata from academic papers. Always respond with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )

            # Parse the JSON response
            response_content = response.choices[0].message.content.strip()

            # Clean up potential markdown code blocks
            if response_content.startswith("```json"):
                response_content = response_content[7:]
            if response_content.startswith("```"):
                response_content = response_content[3:]
            if response_content.endswith("```"):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            if not response_content:
                raise Exception("Empty response from LLM")

            try:
                metadata = json.loads(response_content)
            except json.JSONDecodeError as e:
                # Fallback: create basic metadata from extracted text
                if self.log_callback:
                    self.log_callback(
                        "pdf_extraction_warning",
                        f"LLM JSON parsing failed: {e}. Response: {response_content[:500]}...",
                    )

                # Extract basic info from text using regex as fallback
                title_match = re.search(
                    r"^(.+?)(?:\n|$)", text_content.strip(), re.MULTILINE
                )
                title = title_match.group(1).strip() if title_match else "Unknown Title"

                # Basic year extraction
                year_match = re.search(r"\b(19|20)\d{2}\b", text_content)
                year = int(year_match.group()) if year_match else None

                metadata = {
                    "title": title,
                    "authors": [],
                    "abstract": "",
                    "year": year,
                    "venue_full": "",
                    "venue_acronym": "",
                    "paper_type": "conference",
                    "doi": "",
                    "url": "",
                    "category": "",
                }

            # Clean up author names if they're strings
            if isinstance(metadata.get("authors"), list):
                metadata["authors"] = [
                    name.strip()
                    for name in metadata["authors"]
                    if name and name.strip()
                ]
            elif isinstance(metadata.get("authors"), str):
                # Split comma-separated authors
                metadata["authors"] = [
                    name.strip()
                    for name in metadata["authors"].split(",")
                    if name.strip()
                ]
            else:
                metadata["authors"] = []

            return metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from PDF: {e}")

    def generate_paper_summary(self, pdf_path: str) -> str:
        """Generate an academic summary of the paper using LLM analysis of the full text."""
        try:
            # Extract text from all pages (or first 10 pages to avoid token limits)
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if len(pdf_reader.pages) == 0:
                    return ""

                # Extract text from first 10 pages to stay within token limits
                pages_to_extract = min(10, len(pdf_reader.pages))
                full_text = ""

                for i in range(pages_to_extract):
                    page = pdf_reader.pages[i]
                    full_text += page.extract_text() + "\n\n"

                if not full_text.strip():
                    return ""

            # Use LLM to generate academic summary
            client = OpenAI()

            prompt = f"""You are an excellent academic paper reviewer. You conduct paper summarization on the full paper text provided, with following instructions:

IMPORTANT: Only include information that is explicitly present in the paper text. Do not hallucinate or make up information. If a section is not applicable (e.g., a theory paper may not have experiments), clearly state "Not applicable" or "Not described in the provided text".

Motivation: Explain the motivation behind this research - what problem or gap in knowledge motivated the authors to conduct this study. Only include if explicitly mentioned.

Objective: Begin by clearly stating the primary objective of the research presented in the academic paper. Describe the core idea or hypothesis that underpins the study in simple, accessible language.

Technical Approach: Provide a detailed explanation of the methodology used in the research. Focus on describing how the study was conducted, including any specific techniques, models, or algorithms employed. Only describe what is actually present in the text.

Distinctive Features: Identify and elaborate on what sets this research apart from other studies in the same field. Only mention features that are explicitly highlighted by the authors.

Experimental Setup and Results: Describe the experimental design and data collection process used in the study. Summarize the results obtained or key findings. If this is a theoretical paper without experiments, state "Not applicable - theoretical work".

Advantages and Limitations: Concisely discuss the strengths of the proposed approach and limitations mentioned by the authors. Only include what is explicitly stated in the paper.

Conclusion: Sum up the key points made about the paper's technical approach, its uniqueness, and its comparative advantages and limitations. Base this only on information present in the text.

Please provide your analysis in clear, readable text format (not markdown). Use the exact headers provided above. Be honest about missing information rather than making assumptions.

Paper text:
{full_text[:16000]}"""  # Limit to ~16k characters to avoid token limits

            # Log the LLM request
            if self.log_callback:
                self.log_callback(
                    "llm_summarization_request",
                    f"Requesting paper summary for PDF: {pdf_path}",
                )
                self.log_callback(
                    "llm_summarization_prompt",
                    f"Prompt sent to gpt-4o:\n{prompt[:500]}...",
                )

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert academic paper reviewer specializing in technical paper analysis and summarization. You are extremely careful to only report information that is explicitly present in the provided text and never hallucinate or make assumptions.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=8000,
                temperature=0.1,
            )

            summary_response = response.choices[0].message.content.strip()

            # Log the LLM response
            if self.log_callback:
                self.log_callback(
                    "llm_summarization_response",
                    f"GPT-4o response received ({len(summary_response)} chars)",
                )
                self.log_callback(
                    "llm_summarization_content",
                    f"Generated summary:\n{summary_response}",
                )

            return summary_response

        except Exception as e:
            if self.log_callback:
                self.log_callback(
                    "paper_summary_error", f"Failed to generate paper summary: {e}"
                )
            return ""  # Return empty string if summarization fails, don't break the workflow

    def extract_from_bibtex(self, bib_path: str) -> List[Dict[str, Any]]:
        """Extract metadata from BibTeX file."""
        try:

            with open(bib_path, "r", encoding="utf-8") as file:
                bib_database = bibtexparser.load(file)

            papers_metadata = []

            for entry in bib_database.entries:
                # Extract common BibTeX fields
                metadata = {
                    "title": entry.get("title", "").replace("{", "").replace("}", ""),
                    "abstract": entry.get("abstract", ""),
                    "year": (
                        int(entry.get("year"))
                        if entry.get("year", "").isdigit()
                        else None
                    ),
                    "venue_full": entry.get("booktitle") or entry.get("journal", ""),
                    "venue_acronym": "",
                    "paper_type": self._infer_paper_type_from_bibtex(entry),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "category": "",
                    "pdf_path": None,
                    "preprint_id": entry.get("eprint", ""),
                    "volume": entry.get("volume", ""),
                    "issue": entry.get("number", ""),
                    "pages": entry.get("pages", ""),
                }

                # Extract authors
                authors_str = entry.get("author", "")
                if authors_str:
                    # Split by "and" and clean up
                    authors = [author.strip() for author in authors_str.split(" and ")]
                    metadata["authors"] = authors
                else:
                    metadata["authors"] = []

                papers_metadata.append(metadata)

            return papers_metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from BibTeX file: {e}")

    def extract_from_ris(self, ris_path: str) -> List[Dict[str, Any]]:
        """Extract metadata from RIS file."""
        try:
            with open(ris_path, "r", encoding="utf-8") as file:
                entries = rispy.load(file)

            papers_metadata = []

            for entry in entries:
                # Extract common RIS fields
                metadata = {
                    "title": entry.get("title", "") or entry.get("primary_title", ""),
                    "abstract": entry.get("abstract", ""),
                    "year": int(entry.get("year")) if entry.get("year") else None,
                    "venue_full": entry.get("journal_name", "")
                    or entry.get("secondary_title", ""),
                    "venue_acronym": entry.get("alternate_title1", ""),
                    "paper_type": self._infer_paper_type_from_ris(entry),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "category": "",
                    "pdf_path": None,
                    "preprint_id": "",
                    "volume": entry.get("volume", ""),
                    "issue": entry.get("number", ""),
                    "pages": entry.get("start_page", "")
                    + (
                        "-" + entry.get("end_page", "") if entry.get("end_page") else ""
                    ),
                }

                # Extract authors
                authors = entry.get("authors", []) or entry.get("first_authors", [])
                if authors:
                    metadata["authors"] = [
                        (
                            f"{author.get('given', '')} {author.get('family', '')}".strip()
                            if isinstance(author, dict)
                            else str(author)
                        )
                        for author in authors
                    ]
                else:
                    metadata["authors"] = []

                papers_metadata.append(metadata)

            return papers_metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from RIS file: {e}")

    def _infer_paper_type_from_bibtex(self, entry: Dict[str, str]) -> str:
        """Infer paper type from BibTeX entry type."""
        entry_type = entry.get("ENTRYTYPE", "").lower()

        if entry_type in ["article"]:
            return "journal"
        elif entry_type in ["inproceedings", "conference"]:
            return "conference"
        elif entry_type in ["inbook", "incollection"]:
            return "workshop"
        elif entry_type in ["misc", "unpublished"]:
            return "preprint"
        else:
            return "other"

    def _infer_paper_type_from_ris(self, entry: Dict[str, Any]) -> str:
        """Infer paper type from RIS entry type."""
        type_of_reference = entry.get("type_of_reference", "").upper()

        if type_of_reference in ["JOUR"]:
            return "journal"
        elif type_of_reference in ["CONF", "CPAPER"]:
            return "conference"
        elif type_of_reference in ["CHAP", "BOOK"]:
            return "workshop"
        elif type_of_reference in ["UNPB", "MANSCPT"]:
            return "preprint"
        else:
            return "other"


class ExportService:
    """Service for exporting papers to various formats."""

    def export_to_bibtex(self, papers: List[Paper]) -> str:
        """Export papers to BibTeX format."""
        entries = []

        for paper in papers:
            # Generate BibTeX key
            ordered_authors = paper.get_ordered_authors()
            first_author = (
                ordered_authors[0].full_name.split()[-1]
                if ordered_authors
                else "Unknown"
            )
            year = paper.year or "Unknown"
            key = f"{first_author}{year}"

            # Determine entry type
            entry_type = "article" if paper.paper_type == "journal" else "inproceedings"

            entry = f"@{entry_type}{{{key},\n"
            entry += f"  title = {{{paper.title}}},\n"

            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                authors = " and ".join([author.full_name for author in ordered_authors])
                entry += f"  author = {{{authors}}},\n"

            if paper.venue_full:
                if paper.paper_type == "journal":
                    entry += f"  journal = {{{paper.venue_full}}},\n"
                else:
                    entry += f"  booktitle = {{{paper.venue_full}}},\n"

            if paper.year:
                entry += f"  year = {{{paper.year}}},\n"

            if paper.pages:
                entry += f"  pages = {{{paper.pages}}},\n"

            if paper.doi:
                entry += f"  doi = {{{paper.doi}}},\n"

            entry += "}\n"
            entries.append(entry)

        return "\n".join(entries)

    def export_to_markdown(self, papers: List[Paper]) -> str:
        """Export papers to Markdown format."""
        content = "# Paper List\n\n"

        for paper in papers:
            content += f"## {paper.title}\n\n"

            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                authors = ", ".join([author.full_name for author in ordered_authors])
                content += f"**Authors:** {authors}\n\n"

            if paper.venue_display:
                content += f"**Venue:** {paper.venue_display}\n\n"

            if paper.year:
                content += f"**Year:** {paper.year}\n\n"

            if paper.abstract:
                content += f"**Abstract:** {paper.abstract}\n\n"

            if paper.notes:
                content += f"**Notes:** {paper.notes}\n\n"

            content += "---\n\n"

        return content

    def export_to_html(self, papers: List[Paper]) -> str:
        """Export papers to HTML format."""
        html = """<!DOCTYPE html>\n<html>\n<head>\n    <title>Paper List</title>\n    <style>\n        body { font-family: Arial, sans-serif; margin: 20px; }\n        .paper { margin-bottom: 30px; padding: 20px; border: 1px solid #ddd; }\n        .title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }\n        .authors { font-style: italic; margin-bottom: 5px; }\n        .venue { color: #666; margin-bottom: 5px; }\n        .abstract { margin-top: 10px; }\n        .notes { margin-top: 10px; font-style: italic; }\n    </style>\n</head>\n<body>\n    <h1>Paper List</h1>\n"""

        for paper in papers:
            html += f'    <div class="paper">\n'
            html += f'        <div class="title">{paper.title}</div>\n'

            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                authors = ", ".join([author.full_name for author in ordered_authors])
                html += f'        <div class="authors">{authors}</div>\n'

            if paper.venue_display and paper.year:
                html += f'        <div class="venue">{paper.venue_display}, {paper.year}</div>\n'

            if paper.abstract:
                html += f'        <div class="abstract"><strong>Abstract:</strong> {paper.abstract}</div>\n'

            if paper.notes:
                html += f'        <div class="notes"><strong>Notes:</strong> {paper.notes}</div>\n'

            html += "    </div>\n"

        html += """</body>\n</html>"""

        return html

    def export_to_json(self, papers: List[Paper]) -> str:
        """Export papers to JSON format."""
        paper_list = []

        for paper in papers:
            ordered_authors = paper.get_ordered_authors()
            paper_dict = {
                "title": paper.title,
                "authors": [author.full_name for author in ordered_authors],
                "year": paper.year,
                "venue_full": paper.venue_full,
                "venue_acronym": paper.venue_acronym,
                "paper_type": paper.paper_type,
                "abstract": paper.abstract,
                "notes": paper.notes,
                "doi": paper.doi,
                "preprint_id": paper.preprint_id,
                "category": paper.category,
                "url": paper.url,
                "collections": [collection.name for collection in paper.collections],
                "added_date": (
                    paper.added_date.isoformat() if paper.added_date else None
                ),
                "modified_date": (
                    paper.modified_date.isoformat() if paper.modified_date else None
                ),
                "pdf_path": paper.pdf_path,
            }
            paper_list.append(paper_dict)

        return json.dumps(paper_list, indent=2)


class ChatService:
    """Service for chat functionality."""

    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def open_chat_interface(self, papers: List[Paper], provider: str = "claude"):
        """Open specified LLM provider in browser and show PDF files in Finder/File Explorer."""
        try:
            # Open provider-specific homepage in browser
            provider_urls = {
                "claude": "https://claude.ai",
                "chatgpt": "https://chat.openai.com",
                "gemini": "https://gemini.google.com",
            }

            url = provider_urls.get(provider, "https://claude.ai")
            webbrowser.open(url)

            # Open PDF files in Finder/File Explorer
            system = platform.system()
            opened_files = []
            failed_files = []

            for paper in papers:
                if paper.pdf_path and os.path.exists(paper.pdf_path):
                    try:
                        if system == "Darwin":  # macOS
                            subprocess.run(["open", "-R", paper.pdf_path], check=True)
                        elif system == "Windows":
                            subprocess.run(
                                ["explorer", "/select,", paper.pdf_path], check=True
                            )
                        elif system == "Linux":
                            # For Linux, open the directory containing the file
                            pdf_dir = os.path.dirname(paper.pdf_path)
                            subprocess.run(["xdg-open", pdf_dir], check=True)

                        opened_files.append(paper.title)
                    except Exception as e:
                        error_msg = f"{paper.title}: {str(e)}"
                        failed_files.append(error_msg)
                        if self.log_callback:
                            self.log_callback(
                                "chat_pdf_error",
                                f"Failed to open PDF for {paper.title}: {traceback.format_exc()}",
                            )

            # Prepare result message
            result_parts = []
            provider_name = provider.title()
            if opened_files:
                result_parts.append(
                    f"Opened {provider_name} and {len(opened_files)} PDF file(s)"
                )
            else:
                result_parts.append(
                    f"Opened {provider_name} (no local PDF files found)"
                )

            if failed_files:
                result_parts.append(f"Failed to open {len(failed_files)} file(s)")
                # Return error details for logging by CLI
                return {
                    "success": True,
                    "message": "; ".join(result_parts),
                    "errors": failed_files,
                }

            return {"success": True, "message": result_parts[0], "errors": []}

        except Exception as e:
            return {
                "success": False,
                "message": f"Error opening chat interface: {str(e)}",
                "errors": [],
            }


class SystemService:
    """Service for system integrations."""

    def open_pdf(self, pdf_path: str) -> tuple[bool, str]:
        """Open PDF file in system default viewer. Returns (success, error_message)."""
        try:
            if not os.path.exists(pdf_path):
                return False, f"PDF file not found: {pdf_path}"

            # Cross-platform PDF opening
            if os.name == "nt":  # Windows
                os.startfile(pdf_path)
            elif os.name == "posix":  # macOS and Linux
                if os.uname().sysname == "Darwin":  # macOS
                    result = subprocess.run(
                        ["open", pdf_path], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return False, f"Failed to open PDF: {result.stderr}"
                else:  # Linux
                    # Check if xdg-open is available
                    try:
                        result = subprocess.run(
                            ["which", "xdg-open"], capture_output=True, text=True
                        )
                        if result.returncode != 0:
                            return (
                                False,
                                "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                            )

                        result = subprocess.run(
                            ["xdg-open", pdf_path], capture_output=True, text=True
                        )
                        if result.returncode != 0:
                            return False, f"Failed to open PDF: {result.stderr}"
                    except FileNotFoundError:
                        return (
                            False,
                            "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                        )

            return True, ""

        except Exception as e:
            return False, f"Error opening PDF: {str(e)}"

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to system clipboard."""
        try:
            # Try using pyperclip if available
            try:
                pyperclip.copy(text)
                return True
            except ImportError:
                pass

            # Fallback to system commands
            if os.name == "nt":  # Windows
                subprocess.run(["clip"], input=text.encode(), check=True)
            elif os.name == "posix":  # macOS and Linux
                if os.uname().sysname == "Darwin":  # macOS
                    subprocess.run(["pbcopy"], input=text.encode(), check=True)
                else:  # Linux
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode(),
                        check=True,
                    )

            return True

        except Exception as e:
            # Return False and let the caller handle the error message
            return False

    def download_pdf(
        self,
        source: str,
        identifier: str,
        download_dir: str,
        paper_data: Dict[str, Any] = None,
    ) -> tuple[Optional[str], str]:
        """Download PDF from various sources (arXiv, OpenReview, etc.).

        Returns:
            tuple[Optional[str], str]: (pdf_path, error_message)
            If successful: (path, "")
            If error: (None, error_message)
        """
        try:
            # Create download directory
            os.makedirs(download_dir, exist_ok=True)

            # Generate URL based on source
            if source == "arxiv":
                # Clean arXiv ID
                clean_id = re.sub(r"arxiv[:\s]*", "", identifier, flags=re.IGNORECASE)
                clean_id = re.sub(r"[^\d\.]", "", clean_id)
                pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
            elif source == "openreview":
                pdf_url = f"https://openreview.net/pdf?id={identifier}"
            else:
                return None, f"Unsupported source: {source}"

            # Use PDFManager to handle everything
            pdf_manager = PDFManager()
            filename = pdf_manager._generate_pdf_filename(paper_data, pdf_url)
            filepath = os.path.join(download_dir, filename)

            pdf_path, error_msg = pdf_manager._download_pdf_from_url(pdf_url, filepath)

            if error_msg:
                return None, error_msg

            return pdf_path, ""

        except Exception as e:
            return None, f"Error downloading PDF: {str(e)}\n{traceback.format_exc()}"


class PDFManager:
    """Service for managing PDF files with smart naming and handling."""

    def __init__(self):
        self.pdf_dir = None
        self.pdf_dir = get_pdf_directory()

    def _generate_pdf_filename(self, paper_data: Dict[str, Any], pdf_path: str) -> str:
        """Generate a smart filename for the PDF based on paper metadata."""
        # Extract first author last name
        authors = paper_data.get("authors", [])
        if authors and isinstance(authors[0], str):
            first_author = authors[0]
            # Extract last name (assume last word is surname)
            author_lastname = first_author.split()[-1].lower()
            # Remove non-alphanumeric characters
            author_lastname = re.sub(r"[^\w]", "", author_lastname)
        else:
            author_lastname = "unknown"

        # Extract year
        year = paper_data.get("year", "nodate")

        # Extract first significant word from title
        title = paper_data.get("title", "untitled")
        # Split into words and find first significant word (length > 3, not common words)
        common_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "day",
            "get",
            "has",
            "him",
            "his",
            "how",
            "its",
            "may",
            "new",
            "now",
            "old",
            "see",
            "two",
            "who",
            "boy",
            "did",
            "man",
            "run",
            "say",
            "she",
            "too",
            "use",
        }
        words = re.findall(r"\b[a-zA-Z]+\b", title.lower())
        first_word = "untitled"
        for word in words:
            if len(word) > 3 and word not in common_words:
                first_word = word
                break

        # Generate short hash from file content or path
        try:
            if os.path.exists(pdf_path):
                # Hash from file content
                with open(pdf_path, "rb") as f:
                    content = f.read(8192)  # Read first 8KB for hash
                    file_hash = hashlib.md5(content).hexdigest()[:6]
            else:
                # Hash from URL or path string
                file_hash = hashlib.md5(pdf_path.encode()).hexdigest()[:6]
        except Exception:
            # Fallback to random hash
            file_hash = secrets.token_hex(3)

        # Combine all parts
        filename = f"{author_lastname}{year}{first_word}_{file_hash}.pdf"

        # Ensure filename is filesystem-safe
        filename = re.sub(r"[^\w\-._]", "", filename)

        return filename

    def process_pdf_path(
        self, pdf_input: str, paper_data: Dict[str, Any], old_pdf_path: str = None
    ) -> tuple[str, str]:
        """
        Process PDF input (local file, URL, or invalid) and return the final path.

        Returns:
            tuple[str, str]: (final_pdf_path, error_message)
            If successful: (path, "")
            If error: ("", error_message)
        """
        if not pdf_input or not pdf_input.strip():
            return "", "PDF path cannot be empty"

        pdf_input = pdf_input.strip()

        # Determine input type
        is_url = pdf_input.startswith(("http://", "https://"))
        is_local_file = os.path.exists(pdf_input) and os.path.isfile(pdf_input)

        if not is_url and not is_local_file:
            return (
                "",
                f"Invalid PDF input: '{pdf_input}' is neither a valid file path nor a URL",
            )

        try:
            # Generate target filename
            target_filename = self._generate_pdf_filename(paper_data, pdf_input)
            target_path = os.path.join(self.pdf_dir, target_filename)

            if is_local_file:
                # Copy local file to PDF directory
                # Check if source and destination are the same file
                if os.path.abspath(pdf_input) == os.path.abspath(target_path):
                    # File is already in the right place, no need to copy
                    return target_path, ""

                shutil.copy2(pdf_input, target_path)

                # Clean up old PDF only after successful copy
                if (
                    old_pdf_path
                    and os.path.exists(old_pdf_path)
                    and old_pdf_path != target_path
                ):
                    try:
                        os.remove(old_pdf_path)
                    except Exception:
                        pass  # Don't fail if cleanup fails

                return target_path, ""

            elif is_url:
                # Download URL to PDF directory
                new_path, error = self._download_pdf_from_url(pdf_input, target_path)

                if not error:
                    # Clean up old PDF only after successful download
                    if (
                        old_pdf_path
                        and os.path.exists(old_pdf_path)
                        and old_pdf_path != target_path
                    ):
                        try:
                            os.remove(old_pdf_path)
                        except Exception:
                            pass  # Don't fail if cleanup fails

                return new_path, error

        except Exception as e:
            return "", f"Error processing PDF: {str(e)}"

    def _download_pdf_from_url(self, url: str, target_path: str) -> tuple[str, str]:
        """Download PDF from URL to target path."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            response.raise_for_status()

            # Check if content is actually a PDF
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type:
                # Check first few bytes for PDF signature
                first_chunk = next(response.iter_content(chunk_size=1024), b"")
                if not first_chunk.startswith(b"%PDF"):
                    # Provide more detailed error information
                    content_preview = first_chunk[:100].decode("utf-8", errors="ignore")
                    return (
                        "",
                        f"URL does not point to a valid PDF file.\nContent-Type: {content_type}\nContent preview: {content_preview}...",
                    )

            # Download the file
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return target_path, ""

        except requests.RequestException as e:
            return "", f"Failed to download PDF from URL: {str(e)}"
        except Exception as e:
            return "", f"Error saving PDF file: {str(e)}"


class DatabaseHealthService:
    """Service for diagnosing and fixing database health issues."""

    def __init__(self):
        self.issues_found = []
        self.fixes_applied = []

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Run comprehensive database and system diagnostics."""
        self.issues_found = []
        self.fixes_applied = []

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "database_checks": self._check_database_health(),
            "orphaned_records": self._check_orphaned_records(),
            "orphaned_pdfs": self._check_orphaned_pdfs(),
            "system_checks": self._check_system_health(),
            "terminal_checks": self._check_terminal_setup(),
            "issues_found": self.issues_found,
            "fixes_applied": self.fixes_applied,
            "recommendations": [],
        }

        # Add recommendations based on findings
        report["recommendations"] = self._generate_recommendations(report)

        return report

    def _check_database_health(self) -> Dict[str, Any]:
        """Check database integrity and structure."""
        checks = {
            "database_exists": False,
            "tables_exist": False,
            "table_counts": {},
            "foreign_key_constraints": True,
            "database_size": 0,
        }

        try:
            with get_db_session() as session:
                # Check if database file exists
                db_manager = get_db_manager()
                db_path = db_manager.db_path
                checks["database_exists"] = os.path.exists(db_path)

                if checks["database_exists"]:
                    checks["database_size"] = os.path.getsize(db_path)

                # Check if tables exist and get counts
                try:
                    checks["table_counts"]["papers"] = session.query(Paper).count()
                    checks["table_counts"]["authors"] = session.query(Author).count()
                    checks["table_counts"]["collections"] = session.query(
                        Collection
                    ).count()
                    checks["tables_exist"] = True
                except Exception as e:
                    self.issues_found.append(f"Database tables missing or corrupt: {e}")
                    checks["tables_exist"] = False

                # Check foreign key constraints
                try:
                    result = session.execute(
                        text("PRAGMA foreign_key_check")
                    ).fetchall()
                    if result:
                        checks["foreign_key_constraints"] = False
                        self.issues_found.append(
                            f"Foreign key constraint violations found: {len(result)} issues"
                        )
                except Exception as e:
                    self.issues_found.append(f"Could not check foreign keys: {e}")

        except Exception as e:
            self.issues_found.append(f"Database connection failed: {e}")

        return checks

    def _check_orphaned_records(self) -> Dict[str, Any]:
        """Check for orphaned records in association tables."""
        orphaned = {"paper_collections": [], "paper_authors": [], "summary": {}}

        try:
            with get_db_session() as session:
                # Check orphaned paper_collections
                orphaned_pc = session.execute(
                    text(
                        """
                    SELECT pc.paper_id, pc.collection_id 
                    FROM paper_collections pc
                    LEFT JOIN papers p ON pc.paper_id = p.id
                    LEFT JOIN collections c ON pc.collection_id = c.id
                    WHERE p.id IS NULL OR c.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_collections"] = [
                    (row[0], row[1]) for row in orphaned_pc
                ]
                orphaned["summary"]["orphaned_paper_collections"] = len(orphaned_pc)

                # Check orphaned paper_authors
                orphaned_pa = session.execute(
                    text(
                        """
                    SELECT pa.paper_id, pa.author_id 
                    FROM paper_authors pa
                    LEFT JOIN papers p ON pa.paper_id = p.id
                    LEFT JOIN authors a ON pa.author_id = a.id
                    WHERE p.id IS NULL OR a.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_authors"] = [(row[0], row[1]) for row in orphaned_pa]
                orphaned["summary"]["orphaned_paper_authors"] = len(orphaned_pa)

                if orphaned_pc:
                    self.issues_found.append(
                        f"Found {len(orphaned_pc)} orphaned paper-collection associations"
                    )
                if orphaned_pa:
                    self.issues_found.append(
                        f"Found {len(orphaned_pa)} orphaned paper-author associations"
                    )

        except Exception as e:
            self.issues_found.append(f"Could not check orphaned records: {e}")

        return orphaned

    def _check_system_health(self) -> Dict[str, Any]:
        """Check system and environment health."""
        checks = {
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "dependencies": {},
            "disk_space": {},
            "permissions": {},
        }

        # Check required dependencies
        required_deps = ["sqlalchemy", "prompt_toolkit", "requests", "rich"]
        for dep in required_deps:
            try:
                __import__(dep)
                checks["dependencies"][dep] = "✓ Available"
            except ImportError:
                checks["dependencies"][dep] = "✗ Missing"
                self.issues_found.append(f"Missing required dependency: {dep}")

        # Check disk space
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            if os.path.exists(papercli_dir):
                statvfs = os.statvfs(papercli_dir)
                free_space = statvfs.f_frsize * statvfs.f_bavail
                checks["disk_space"]["free_bytes"] = free_space
                checks["disk_space"]["free_mb"] = free_space // (1024 * 1024)

                if free_space < 100 * 1024 * 1024:  # Less than 100MB
                    self.issues_found.append(
                        "Low disk space: less than 100MB available"
                    )
        except Exception:
            checks["disk_space"]["error"] = "Could not check disk space"

        # Check directory permissions
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            checks["permissions"]["papercli_dir_writable"] = os.access(
                papercli_dir, os.W_OK
            )
            if not checks["permissions"]["papercli_dir_writable"]:
                self.issues_found.append("PaperCLI directory is not writable")
        except Exception:
            checks["permissions"]["error"] = "Could not check permissions"

        return checks

    def _check_terminal_setup(self) -> Dict[str, Any]:
        """Check terminal capabilities and setup."""
        checks = {
            "terminal_type": os.environ.get("TERM", "unknown"),
            "colorterm": os.environ.get("COLORTERM", "not_set"),
            "terminal_size": {},
            "unicode_support": False,
            "color_support": False,
        }

        # Check terminal size
        try:
            size = shutil.get_terminal_size()
            checks["terminal_size"]["columns"] = size.columns
            checks["terminal_size"]["lines"] = size.lines

            if size.columns <= 125:
                self.issues_found.append(
                    "Terminal width is less than 125 columns (current: {})".format(
                        size.columns
                    )
                )
            if size.lines <= 35:
                self.issues_found.append(
                    "Terminal height is less than 35 lines (current: {})".format(
                        size.lines
                    )
                )
        except Exception:
            checks["terminal_size"]["error"] = "Could not determine terminal size"

        # Check Unicode support
        try:
            test_chars = "📄✓✗⚠"
            test_chars.encode("utf-8")
            checks["unicode_support"] = True
        except UnicodeEncodeError:
            checks["unicode_support"] = False
            self.issues_found.append("Terminal may not support Unicode characters")

        # Check color support
        if "color" in checks["terminal_type"].lower() or checks["colorterm"]:
            checks["color_support"] = True
        else:
            checks["color_support"] = False
            self.issues_found.append("Terminal may not support colors")

        return checks

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on diagnostic results."""
        recommendations = []

        # Database recommendations
        if not report["database_checks"]["tables_exist"]:
            recommendations.append("Run database migration to create missing tables")

        if (
            report["orphaned_records"]["summary"].get("orphaned_paper_collections", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned paper-collection associations")

        if report["orphaned_records"]["summary"].get("orphaned_paper_authors", 0) > 0:
            recommendations.append("Clean up orphaned paper-author associations")

        if (
            report.get("orphaned_pdfs", {})
            .get("summary", {})
            .get("orphaned_pdf_files", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned PDF files")

        # System recommendations
        missing_deps = [
            dep
            for dep, status in report["system_checks"]["dependencies"].items()
            if "Missing" in status
        ]
        if missing_deps:
            recommendations.append(
                f"Install missing dependencies: {', '.join(missing_deps)}"
            )

        # Terminal recommendations
        if not report["terminal_checks"]["unicode_support"]:
            recommendations.append("Configure terminal to support UTF-8/Unicode")

        if not report["terminal_checks"]["color_support"]:
            recommendations.append("Enable color support in terminal")

        return recommendations

    def _check_orphaned_pdfs(self) -> Dict[str, Any]:
        """Check for orphaned PDF files in the PDF directory."""
        orphaned = {"files": [], "summary": {}}

        try:
            with get_db_session() as session:
                db_manager = get_db_manager()
                pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")

                if not os.path.exists(pdf_dir):
                    return orphaned

                all_pdfs_in_db = {
                    p.pdf_path
                    for p in session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None))
                    .all()
                }

                disk_pdfs = {
                    os.path.join(pdf_dir, f)
                    for f in os.listdir(pdf_dir)
                    if f.endswith(".pdf")
                }

                orphaned_files = list(disk_pdfs - all_pdfs_in_db)

                orphaned["files"] = orphaned_files
                orphaned["summary"]["orphaned_pdf_files"] = len(orphaned_files)

                if orphaned_files:
                    self.issues_found.append(
                        f"Found {len(orphaned_files)} orphaned PDF files"
                    )
        except Exception as e:
            self.issues_found.append(f"Could not check for orphaned PDFs: {e}")

        return orphaned

    def clean_orphaned_pdfs(self) -> Dict[str, int]:
        """Clean up orphaned PDF files."""
        cleaned = {"pdf_files": 0}

        try:
            report = self._check_orphaned_pdfs()
            orphaned_files = report.get("files", [])

            for f in orphaned_files:
                try:
                    os.remove(f)
                    cleaned["pdf_files"] += 1
                except Exception:
                    pass  # ignore errors on individual file deletions

            if cleaned["pdf_files"] > 0:
                self.fixes_applied.append(
                    f"Cleaned {cleaned['pdf_files']} orphaned PDF files"
                )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned PDFs: {e}")

        return cleaned

    def clean_orphaned_records(self) -> Dict[str, int]:
        """Clean up orphaned records in the database."""
        cleaned = {"paper_collections": 0, "paper_authors": 0}

        try:
            with get_db_session() as session:
                # Clean orphaned paper_collections
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_collections 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR collection_id NOT IN (SELECT id FROM collections)
                """
                    )
                )
                cleaned["paper_collections"] = result.rowcount

                # Clean orphaned paper_authors
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_authors 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR author_id NOT IN (SELECT id FROM authors)
                """
                    )
                )
                cleaned["paper_authors"] = result.rowcount

                session.commit()

                if cleaned["paper_collections"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_collections']} orphaned paper-collection associations"
                    )
                if cleaned["paper_authors"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_authors']} orphaned paper-author associations"
                    )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned records: {e}")

        return cleaned


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

        # Call completion callback
        if tracking["on_all_complete"]:
            tracking["on_all_complete"](tracking)

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
                                f"Paper: {paper.title[:60]}{'...' if len(paper.title) > 60 else ''}"
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


class BackgroundOperationService:
    """Service for running operations in background threads with status updates."""

    def __init__(self, status_bar=None, log_callback=None):
        self.status_bar = status_bar
        self.log_callback = log_callback

    def run_operation(
        self, operation_func, operation_name, initial_message=None, on_complete=None
    ):
        """
        Run an operation in the background with status updates.

        Args:
            operation_func: Function to run in background
            operation_name: Name for logging purposes
            initial_message: Initial status message to display
            on_complete: Callback function to call with result

        Returns:
            Thread object
        """
        # Set initial status
        if initial_message and self.status_bar:
            self.status_bar.set_status(initial_message, "loading")
            get_app().invalidate()

        def background_worker():
            try:
                if self.log_callback:
                    self.log_callback(
                        operation_name,
                        f"Starting background operation: {operation_name}",
                    )

                # Run the operation
                result = operation_func()

                def schedule_success():
                    if self.log_callback:
                        self.log_callback(
                            operation_name, f"Successfully completed: {operation_name}"
                        )

                    # Call completion callback with result
                    if on_complete:
                        on_complete(result, None)

                    get_app().invalidate()

                return get_app().loop.call_soon_threadsafe(schedule_success)

            except Exception as e:

                def schedule_error(error=e):
                    if self.log_callback:
                        self.log_callback(
                            f"{operation_name}_error",
                            f"Error in {operation_name}: {error}",
                        )

                    # Call completion callback with error
                    if on_complete:
                        on_complete(None, error)

                    get_app().invalidate()

                return get_app().loop.call_soon_threadsafe(schedule_error)

        thread = threading.Thread(target=background_worker, daemon=True)
        thread.start()
        return thread
