"""Database utility functions to reduce session boilerplate."""

from contextlib import contextmanager
from typing import Any, Callable, List, Optional, Type

from sqlalchemy.orm import Session

from ..db.database import get_db_session
from ..db.models import Author, Collection, Paper


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
    def safe_execute(operation: Callable[[Session], Any]) -> tuple[Any, Optional[str]]:
        """
        Safely execute database operation with error handling.

        Args:
            operation: Function that takes a session and returns a result

        Returns:
            tuple[Any, Optional[str]]: (result, error_message)
            If successful: (result, None)
            If error: (None, error_message)
        """
        try:
            with DatabaseHelper.session() as session:
                result = operation(session)
                return result, None
        except Exception as e:
            return None, str(e)


class PaperQueries:
    """Specialized queries for Paper model."""

    @staticmethod
    def get_by_title(title: str) -> Optional[Paper]:
        """Get paper by exact title match."""
        with DatabaseHelper.session() as session:
            return session.query(Paper).filter(Paper.title == title).first()

    @staticmethod
    def search_by_title(title_fragment: str, limit: int = 50) -> List[Paper]:
        """Search papers by title fragment."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Paper)
                .filter(Paper.title.ilike(f"%{title_fragment}%"))
                .limit(limit)
                .all()
            )

    @staticmethod
    def get_by_year_range(start_year: int, end_year: int) -> List[Paper]:
        """Get papers within year range."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Paper)
                .filter(Paper.year.between(start_year, end_year))
                .all()
            )

    @staticmethod
    def get_recent(limit: int = 10) -> List[Paper]:
        """Get most recently added papers."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Paper)
                .order_by(Paper.added_date.desc())
                .limit(limit)
                .all()
            )


class AuthorQueries:
    """Specialized queries for Author model."""

    @staticmethod
    def get_by_name(full_name: str) -> Optional[Author]:
        """Get author by exact name match."""
        with DatabaseHelper.session() as session:
            return session.query(Author).filter(Author.full_name == full_name).first()

    @staticmethod
    def search_by_name(name_fragment: str, limit: int = 50) -> List[Author]:
        """Search authors by name fragment."""
        with DatabaseHelper.session() as session:
            return (
                session.query(Author)
                .filter(Author.full_name.ilike(f"%{name_fragment}%"))
                .limit(limit)
                .all()
            )


class CollectionQueries:
    """Specialized queries for Collection model."""

    @staticmethod
    def get_by_name(name: str) -> Optional[Collection]:
        """Get collection by exact name match."""
        with DatabaseHelper.session() as session:
            return session.query(Collection).filter(Collection.name == name).first()

    @staticmethod
    def get_all_names() -> List[str]:
        """Get all collection names."""
        with DatabaseHelper.session() as session:
            return [c.name for c in session.query(Collection).all()]
