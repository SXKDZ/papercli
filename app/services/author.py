"""Author and Collection services - Business logic for author and collection management."""

from typing import List

from ..db.database import get_db_session
from ..db.models import Author
from ..db.models import Collection
from ..db.models import Paper


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
                            f"Paper '{paper.title[:50]}...' not in collection: {collection_name}"
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
