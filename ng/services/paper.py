from __future__ import annotations
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from ng.db.database import get_db_session
from ng.db.models import (
    Author,
    Collection,
    Paper,
    PaperAuthor,
)


class PaperService:
    """Service for managing papers."""

    def get_all_papers(self) -> List[Paper]:
        """Get all papers ordered by added date (newest first)."""
        with get_db_session() as session:
            papers = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .order_by(Paper.added_date.desc())
                .all()
            )

            for paper in papers:
                _ = paper.paper_authors
                _ = paper.collections
                # Force load collection names
                for collection in paper.collections:
                    _ = collection.name

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
                _ = paper.paper_authors
                for paper_author in paper.paper_authors:
                    _ = paper_author.author
                _ = paper.collections

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
                if "pdf_path" in paper_data and paper_data["pdf_path"]:
                    from .pdf import PDFManager

                    pdf_manager = PDFManager()

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
                        paper_data.pop("pdf_path")
                        return None, pdf_error
                    else:
                        paper_data["pdf_path"] = new_pdf_path

                if "authors" in paper_data:
                    authors = paper_data.pop("authors")
                    session.query(PaperAuthor).filter(
                        PaperAuthor.paper_id == paper.id
                    ).delete()
                    session.flush()

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

                for key, value in paper_data.items():
                    if hasattr(paper, key):
                        setattr(paper, key, value)

                paper.modified_date = datetime.now()
                session.commit()
                session.refresh(paper)

                _ = paper.paper_authors
                for pa in paper.paper_authors:
                    _ = pa.author
                    _ = pa.position
                _ = paper.collections

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
                if paper.pdf_path:
                    try:
                        from ng.services.pdf import PDFManager

                        pdf_manager = PDFManager()
                        full_pdf_path = pdf_manager.get_absolute_path(paper.pdf_path)
                        if os.path.exists(full_pdf_path):
                            os.remove(full_pdf_path)
                    except Exception:
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
                if paper.pdf_path:
                    try:
                        from ng.services.pdf import PDFManager

                        pdf_manager = PDFManager()
                        full_pdf_path = pdf_manager.get_absolute_path(paper.pdf_path)
                        if os.path.exists(full_pdf_path):
                            os.remove(full_pdf_path)
                    except Exception:
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

            paper = Paper()
            for key, value in paper_data.items():
                if hasattr(paper, key) and value is not None:
                    setattr(paper, key, value)

            session.add(paper)
            session.flush()

            for position, author_name in enumerate(authors):
                author = (
                    session.query(Author)
                    .filter(Author.full_name == author_name)
                    .first()
                )
                if not author:
                    author = Author(full_name=author_name)
                    session.add(author)
                    session.flush()

                paper_author = PaperAuthor(
                    paper=paper, author=author, position=position
                )
                session.add(paper_author)

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
                        session.flush()

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

            paper_with_relationships = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .filter(Paper.id == paper.id)
                .first()
            )

            _ = paper_with_relationships.paper_authors
            _ = paper_with_relationships.collections

            session.expunge_all()

            return paper_with_relationships

    def prepare_paper_data_for_edit(self, paper) -> dict:
        """Prepare paper data dictionary for EditDialog from a Paper model instance.

        This method extracts all relevant fields from a Paper model
        and formats them for use with EditDialog.

        Args:
            paper: Paper model instance

        Returns:
            dict: Paper data formatted for EditDialog
        """
        return {
            "id": paper.id,
            "title": paper.title,
            "abstract": paper.abstract,
            "venue_full": paper.venue_full,
            "venue_acronym": paper.venue_acronym,
            "year": paper.year,
            "volume": getattr(paper, "volume", None),
            "issue": getattr(paper, "issue", None),
            "pages": paper.pages,
            "paper_type": paper.paper_type,
            "doi": paper.doi,
            "preprint_id": paper.preprint_id,
            "category": paper.category,
            "url": paper.url,
            "pdf_path": paper.pdf_path,
            "notes": paper.notes,
            "added_date": paper.added_date,
            "modified_date": paper.modified_date,
            "authors": (
                paper.get_ordered_authors()
                if hasattr(paper, "get_ordered_authors")
                else []
            ),
            "collections": (paper.collections if hasattr(paper, "collections") else []),
        }

    def create_edit_callback(self, app, paper_id):
        """Create a standardized edit callback for handling EditDialog results.

        This method creates a callback that handles paper updates,
        notifications, and error handling consistently across the application.

        Args:
            app: The main application instance for notifications and paper reloading
            paper_id: ID of the paper being edited

        Returns:
            callable: Callback function for EditDialog results
        """

        def callback(result):
            if result:
                try:
                    updated_paper, error_message = self.update_paper(paper_id, result)
                    if updated_paper:
                        app.load_papers()  # Reload papers to reflect changes
                        app.notify(
                            f"Paper '{updated_paper.title}' updated successfully",
                            severity="information",
                        )
                        return updated_paper  # Return for caller to use
                    else:
                        app.notify(
                            f"Failed to update paper: {error_message}", severity="error"
                        )
                except Exception as e:
                    app.notify(f"Error updating paper: {e}", severity="error")
            return None

        return callback
