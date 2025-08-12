"""Database utility functions to reduce session boilerplate."""

from contextlib import contextmanager
from typing import Any, Callable, List, Optional, Type

from sqlalchemy.orm import Session

from ng.db.database import get_db_session
from ng.db.models import Author, Collection, Paper


class DatabaseHelper:
    """Helper class for common database operations."""

    @staticmethod
    @contextmanager
    def session():
        """Context manager for database sessions."""
        with get_db_session() as session:
            yield session

    @staticmethod
    def get_by_id(model_class: Type, id_value: int) -> Optional[Any]:
        """Get a single record by ID."""
        with DatabaseHelper.session() as session:
            return session.query(model_class).filter(model_class.id == id_value).first()

    @staticmethod
    def get_all(model_class: Type, limit: Optional[int] = None) -> List[Any]:
        """Get all records of a model type."""
        with DatabaseHelper.session() as session:
            query = session.query(model_class)
            if limit:
                query = query.limit(limit)
            return query.all()

    @staticmethod
    def get_filtered(
        model_class: Type, filter_func: Callable, limit: Optional[int] = None
    ) -> List[Any]:
        """Get records with custom filter function."""
        with DatabaseHelper.session() as session:
            query = session.query(model_class)
            query = filter_func(query)
            if limit:
                query = query.limit(limit)
            return query.all()

    @staticmethod
    def count_all(model_class: Type) -> int:
        """Count all records of a model type."""
        with DatabaseHelper.session() as session:
            return session.query(model_class).count()

    @staticmethod
    def count_filtered(model_class: Type, filter_func: Callable) -> int:
        """Count records with custom filter function."""
        with DatabaseHelper.session() as session:
            query = session.query(model_class)
            query = filter_func(query)
            return query.count()

    @staticmethod
    def execute_in_session(func: Callable[[Session], Any]) -> Any:
        """Execute a function with a database session."""
        with DatabaseHelper.session() as session:
            return func(session)


class PaperQueries:
    """Specialized queries for Paper model."""

    @staticmethod
    def get_by_title(title: str) -> Optional[Paper]:
        """Get paper by title."""
        with DatabaseHelper.session() as session:
            return session.query(Paper).filter(Paper.title == title).first()

    @staticmethod
    def get_by_author_name(author_name: str) -> List[Paper]:
        """Get papers by author name."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Paper)
                .join(Paper.authors)
                .filter(Author.name.contains(author_name))
                .all()
            )

    @staticmethod
    def get_by_venue(venue: str) -> List[Paper]:
        """Get papers by venue."""
        with DatabaseHelper.session() as session:
            return session.query(Paper).filter(Paper.venue.contains(venue)).all()

    @staticmethod
    def get_by_year_range(start_year: int, end_year: int) -> List[Paper]:
        """Get papers within a year range."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Paper)
                .filter(Paper.year >= start_year, Paper.year <= end_year)
                .all()
            )


class AuthorQueries:
    """Specialized queries for Author model."""

    @staticmethod
    def get_by_name(name: str) -> Optional[Author]:
        """Get author by exact name."""
        with DatabaseHelper.session() as session:
            return session.query(Author).filter(Author.name == name).first()

    @staticmethod
    def search_by_name(name_pattern: str) -> List[Author]:
        """Search authors by name pattern."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Author).filter(Author.name.contains(name_pattern)).all()
            )

    @staticmethod
    def get_most_prolific(limit: int = 10) -> List[tuple]:
        """Get authors with most papers."""
        with DatabaseHelper.session() as session:
            from sqlalchemy import func

            return (
                session.query(Author.name, func.count(Paper.id))
                .join(Paper.authors)
                .group_by(Author.id, Author.name)
                .order_by(func.count(Paper.id).desc())
                .limit(limit)
                .all()
            )


class CollectionQueries:
    """Specialized queries for Collection model."""

    @staticmethod
    def get_by_name(name: str) -> Optional[Collection]:
        """Get collection by exact name."""
        with DatabaseHelper.session() as session:
            return session.query(Collection).filter(Collection.name == name).first()

    @staticmethod
    def search_by_name(name_pattern: str) -> List[Collection]:
        """Search collections by name pattern."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Collection)
                .filter(Collection.name.contains(name_pattern))
                .all()
            )

    @staticmethod
    def get_with_paper_counts() -> List[tuple]:
        """Get collections with their paper counts."""
        with DatabaseHelper.session() as session:
            from sqlalchemy import func

            return (
                session.query(Collection.name, func.count(Paper.id))
                .outerjoin(Collection.papers)
                .group_by(Collection.id, Collection.name)
                .order_by(Collection.name)
                .all()
            )
