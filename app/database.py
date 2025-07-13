"""
Database initialization and connection management.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
from alembic import command
from alembic.config import Config

from .models import Base


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=True, bind=self.engine
        )

    def create_tables(self):
        """Create all database tables using Alembic."""
        if not os.path.exists("alembic.ini"):
            raise Exception("Alembic config not found")
        
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option(
            "sqlalchemy.url", f"sqlite:///{self.db_path}"
        )
        command.upgrade(alembic_cfg, "head")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session with automatic cleanup."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Global database manager instance
_db_manager = None


def init_database(db_path: str) -> DatabaseManager:
    """Initialize the database manager."""
    global _db_manager
    _db_manager = DatabaseManager(db_path)
    _db_manager.create_tables()
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """Get the global database manager instance."""
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db_manager


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Get a database session."""
    db_manager = get_db_manager()
    with db_manager.get_session() as session:
        yield session
