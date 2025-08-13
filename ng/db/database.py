"""
Database initialization and connection management.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ng.db.models import Base


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}")
        
        # Enable foreign key constraints for SQLite
        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=True, bind=self.engine
        )

    def create_tables(self) -> None:
        """Create all database tables using Alembic or fallback to direct creation."""
        # First try to use Alembic if available
        if self._try_alembic_upgrade():
            return

        # Fallback: Create tables directly using SQLAlchemy
        print("Alembic not available, creating tables directly...")
        Base.metadata.create_all(bind=self.engine)

    def _try_alembic_upgrade(self) -> bool:
        """Try to upgrade using Alembic. Returns True if successful."""
        try:
            # Try to find alembic.ini in the current directory first (for development)
            alembic_ini_path: Optional[str | Path] = "alembic.ini"
            alembic_dir: Optional[str | Path] = "alembic"

            if not os.path.exists(str(alembic_ini_path)):
                # Look for it relative to the ng package (installed package)
                import ng

                ng_path = Path(ng.__file__).parent
                alembic_ini_path = ng_path / "alembic.ini"
                alembic_dir = ng_path / "alembic"

                if not alembic_ini_path.exists():
                    return False

            alembic_cfg = Config(str(alembic_ini_path))
            alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")
            alembic_cfg.set_main_option("script_location", str(alembic_dir))

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
_db_manager: Optional[DatabaseManager] = None


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
