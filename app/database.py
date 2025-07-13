"""
Database initialization and connection management.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
from alembic import command
from alembic.config import Config
import pkg_resources

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
        # Try to find alembic.ini in the current directory first (for development)
        alembic_ini_path = "alembic.ini"
        
        if not os.path.exists(alembic_ini_path):
            # If not found, try to get it from the package
            try:
                alembic_ini_path = pkg_resources.resource_filename('papercli', 'alembic.ini')
            except:
                # Fallback: look for it relative to this file
                current_dir = Path(__file__).parent.parent
                alembic_ini_path = current_dir / "alembic.ini"
                if not alembic_ini_path.exists():
                    raise Exception("Alembic config not found")
                alembic_ini_path = str(alembic_ini_path)
        
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option(
            "sqlalchemy.url", f"sqlite:///{self.db_path}"
        )
        
        # Set the script location to the alembic directory
        if not os.path.exists("alembic"):
            try:
                alembic_dir = pkg_resources.resource_filename('alembic', '')
                alembic_cfg.set_main_option("script_location", alembic_dir)
            except:
                # Fallback: look for it relative to this file
                current_dir = Path(__file__).parent.parent
                alembic_dir = current_dir / "alembic"
                if alembic_dir.exists():
                    alembic_cfg.set_main_option("script_location", str(alembic_dir))
        
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


def get_pdf_directory() -> str:
    """Get the global PDF directory path."""
    db_manager = get_db_manager()
    pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    return pdf_dir
