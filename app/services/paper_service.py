"""Paper service - Business logic for paper management."""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from ..db.database import get_db_session
from ..db.models import Author, Collection, Paper, PaperAuthor


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
                    # Import here to avoid circular imports
                    from .pdf_service import PDFManager

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
        """Delete a paper and its associated PDF file."""
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if paper:
                # Delete associated PDF file if it exists
                if paper.pdf_path and os.path.exists(paper.pdf_path):
                    try:
                        os.remove(paper.pdf_path)
                    except Exception:
                        # Log this error, but don't prevent db deletion
                        pass

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
