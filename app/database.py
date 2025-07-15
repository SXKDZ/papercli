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
        """Create all database tables using Alembic or fallback to direct creation."""
        # First try to use Alembic if available
        if self._try_alembic_upgrade():
            return
            
        # Fallback: Create tables directly using SQLAlchemy
        print("Alembic not available, creating tables directly...")
        Base.metadata.create_all(bind=self.engine)
    
    def _try_alembic_upgrade(self):
        """Try to upgrade using Alembic. Returns True if successful."""
        try:
            # Try to find alembic.ini in the current directory first (for development)
            alembic_ini_path = "alembic.ini"
            alembic_dir = "alembic"
            
            if not os.path.exists(alembic_ini_path):
                # Look for it relative to this file (installed package)
                import app
                app_path = Path(app.__file__).parent
                alembic_ini_path = app_path / "alembic.ini"
                alembic_dir = app_path / "alembic"
                
                if not alembic_ini_path.exists():
                    return False
                
                alembic_ini_path = str(alembic_ini_path)
                alembic_dir = str(alembic_dir)
            
            alembic_cfg = Config(alembic_ini_path)
            alembic_cfg.set_main_option(
                "sqlalchemy.url", f"sqlite:///{self.db_path}"
            )
            alembic_cfg.set_main_option("script_location", alembic_dir)
            
            command.upgrade(alembic_cfg, "head")
            return True
        except Exception:
            return False

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
