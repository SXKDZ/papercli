from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from ng.db.database import get_db_session
from ng.db.models import Collection, Paper, paper_collections


class CollectionService:
    """Service for managing collections."""

    def __init__(self, app=None):
        self.app = app

    def get_all_collections(self) -> List[Collection]:
        """Get all collections with their papers eagerly loaded."""
        with get_db_session() as session:
            collections = (
                session.query(Collection)
                .options(joinedload(Collection.papers))
                .order_by(Collection.name)
                .all()
            )

            # Force loading of relationships before expunging
            for collection in collections:
                _ = collection.papers  # Force load papers relationship
                for paper in collection.papers:
                    _ = paper.title  # Force load paper attributes

            session.expunge_all()
            return collections

    def get_collection_by_name(self, name: str) -> Optional[Collection]:
        """Get a collection by its name."""
        with get_db_session() as session:
            collection = session.query(Collection).filter_by(name=name).first()
            if collection:
                session.expunge(collection)
            return collection

    def add_collection(self, name: str) -> Collection:
        """Add a new collection."""
        with get_db_session() as session:
            collection = Collection(name=name)
            session.add(collection)
            session.commit()
            session.refresh(collection)
            session.expunge(collection)
            if self.app:
                self.app._add_log(
                    "collection_add", f"Added collection ID {collection.id}: '{name}'"
                )
            return collection

    def add_papers_to_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> int:
        """Adds papers to a specified collection. Creates collection if it doesn't exist."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter_by(name=collection_name).first()
            )
            if not collection:
                collection = Collection(name=collection_name)
                session.add(collection)
                session.flush()  # Ensure collection gets an ID

            added_count = 0
            for paper_id in paper_ids:
                paper = session.query(Paper).get(paper_id)
                if paper and paper not in collection.papers:
                    collection.papers.append(paper)
                    added_count += 1
            session.commit()
            if self.app and added_count:
                paper_list = ", ".join(str(pid) for pid in paper_ids)
                self.app._add_log(
                    "collection_add_papers",
                    f"Added {added_count} paper(s) to '{collection_name}': {paper_list}",
                )
            return added_count

    def remove_papers_from_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> tuple[int, List[str]]:
        """Removes papers from a specified collection."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter_by(name=collection_name).first()
            )
            if not collection:
                return 0, [f"Collection '{collection_name}' not found."]

            removed_count = 0
            errors = []
            for paper_id in paper_ids:
                paper = session.query(Paper).get(paper_id)
                if paper and paper in collection.papers:
                    collection.papers.remove(paper)
                    removed_count += 1
                elif not paper:
                    errors.append(f"Paper with ID {paper_id} not found.")
                else:
                    errors.append(
                        f"Paper with ID {paper_id} is not in collection '{collection_name}'."
                    )
            session.commit()
            if self.app and removed_count:
                paper_list = ", ".join(str(pid) for pid in paper_ids)
                self.app._add_log(
                    "collection_remove_papers",
                    f"Removed {removed_count} paper(s) from '{collection_name}': {paper_list}",
                )
            return removed_count, errors

    def purge_empty_collections(self) -> int:
        """Deletes collections that have no papers associated with them."""
        with get_db_session() as session:
            # Find collections with no associated papers
            empty_collections = (
                session.query(Collection)
                .outerjoin(paper_collections)
                .group_by(Collection.id)
                .having(func.count(paper_collections.c.paper_id) == 0)
                .all()
            )

            deleted_count = 0
            for collection in empty_collections:
                session.delete(collection)
                deleted_count += 1
            session.commit()
            if self.app and deleted_count:
                self.app._add_log(
                    "collection_purge", f"Purged {deleted_count} empty collection(s)"
                )
            return deleted_count

    def get_or_create_collection(self, name: str) -> Collection:
        """Get existing collection or create new one."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter(Collection.name == name).first()
            )
            if not collection:
                collection = Collection(name=name)
                session.add(collection)
                session.commit()
                session.refresh(collection)
            session.expunge(collection)
            if self.app:
                self.app._add_log(
                    "collection_get_or_create",
                    f"Retrieved or created collection ID {collection.id}: '{name}'",
                )
            return collection

    def update_collection_name(self, collection_id: int, new_name: str) -> bool:
        """Update the name of an existing collection."""
        with get_db_session() as session:
            collection = session.query(Collection).get(collection_id)
            if collection:
                old_name = collection.name
                collection.name = new_name
                session.commit()
                if self.app:
                    self.app._add_log(
                        "collection_rename",
                        f"Renamed collection ID {collection_id}: '{old_name}' → '{new_name}'",
                    )
                return True
            return False

    def delete_collection(self, collection_id: int) -> bool:
        """Delete a collection by ID."""
        with get_db_session() as session:
            collection = session.query(Collection).get(collection_id)
            if collection:
                old_name = collection.name
                session.delete(collection)
                session.commit()
                if self.app:
                    self.app._add_log(
                        "collection_delete",
                        f"Deleted collection ID {collection_id}: '{old_name}'",
                    )
                return True
            return False

    def add_paper_to_collection(self, paper_id: int, collection_id: int) -> bool:
        """Add a single paper to a collection."""
        with get_db_session() as session:
            collection = session.query(Collection).get(collection_id)
            paper = session.query(Paper).get(paper_id)
            if collection and paper and paper not in collection.papers:
                collection.papers.append(paper)
                session.commit()
                if self.app:
                    self.app._add_log(
                        "collection_add_paper",
                        f"Added paper {paper_id} to collection {collection_id}",
                    )
                return True
            return False

    def remove_paper_from_collection(self, paper_id: int, collection_id: int) -> bool:
        """Remove a single paper from a collection."""
        with get_db_session() as session:
            collection = session.query(Collection).get(collection_id)
            paper = session.query(Paper).get(paper_id)
            if collection and paper and paper in collection.papers:
                collection.papers.remove(paper)
                session.commit()
                if self.app:
                    self.app._add_log(
                        "collection_remove_paper",
                        f"Removed paper {paper_id} from collection {collection_id}",
                    )
                return True
            return False
