from __future__ import annotations
import os
import traceback
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from ng.db import models  # Reusing models
from ng.db.models import Base, Paper, Author, Collection, PaperAuthor  # Reusing models


class DatabaseHealthService:
    """Service for diagnosing and fixing database issues."""

    def __init__(self, db_path: str = None, app=None):
        # If db_path is not provided, get it from app
        self.db_path = db_path if db_path else (app.db_path if app else None)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        self.Session = sessionmaker(bind=self.engine)
        self.app = app

    def _add_log(self, action: str, details: str):
        if self.app:
            self.app._add_log(action, details)

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Runs a comprehensive diagnostic check on the database and system."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "database_checks": self._check_database_integrity(),
            "orphaned_records": self._find_orphaned_records(),
            "orphaned_pdfs": self._find_orphaned_pdfs(),
            "absolute_pdf_paths": self._find_absolute_pdf_paths(),
            "missing_pdfs": self._find_missing_pdfs(),
            "system_checks": self._check_system_health(),
            "terminal_checks": self._check_terminal_capabilities(),
            "issues_found": [],
            "recommendations": [],
        }

        # Analyze report and add issues/recommendations
        if not report["database_checks"]["database_exists"]:
            report["issues_found"].append("Database file does not exist.")
            report["recommendations"].append("Run PaperCLI to initialize the database.")
        if not report["database_checks"]["tables_exist"]:
            report["issues_found"].append("Database tables are missing.")
            report["recommendations"].append(
                "Run database migrations (e.g., alembic upgrade head)."
            )
        if not report["database_checks"]["foreign_key_constraints"]:
            report["issues_found"].append("Foreign key constraints are not enforced.")
            report["recommendations"].append(
                "Ensure SQLite foreign_keys pragma is enabled."
            )

        if report["orphaned_records"]["summary"]["orphaned_paper_collections"] > 0:
            report["issues_found"].append(
                "Orphaned paper-collection associations found."
            )
            report["recommendations"].append("Run '/doctor clean' to remove them.")
        if report["orphaned_records"]["summary"]["orphaned_paper_authors"] > 0:
            report["issues_found"].append("Orphaned paper-author associations found.")
            report["recommendations"].append("Run '/doctor clean' to remove them.")

        if report["orphaned_pdfs"]["summary"]["orphaned_pdf_files"] > 0:
            report["issues_found"].append(
                "Orphaned PDF files found (not linked to any paper)."
            )
            report["recommendations"].append("Run '/doctor clean' to remove them.")

        if report["absolute_pdf_paths"]["summary"]["absolute_path_count"] > 0:
            report["issues_found"].append(
                "Papers with absolute PDF paths found (should be relative)."
            )
            report["recommendations"].append("Run '/doctor clean' to fix them.")

        if report["missing_pdfs"]["summary"]["missing_pdf_count"] > 0:
            report["issues_found"].append("Papers with missing PDF files found.")
            report["recommendations"].append(
                "Verify PDF file locations or remove missing papers."
            )

        return report

    def _check_database_integrity(self) -> Dict[str, Any]:
        """Checks basic database file and table integrity."""
        db_exists = Path(self.db_path).exists()
        tables_exist = False
        table_counts = {}
        foreign_key_constraints = False
        db_size = 0

        if db_exists:
            db_size = os.path.getsize(self.db_path)
            try:
                with self.engine.connect() as connection:
                    inspector = inspect(self.engine)
                    existing_tables = inspector.get_table_names()
                    if existing_tables:
                        tables_exist = True
                        for table_name in existing_tables:
                            result = connection.execute(
                                text(f"SELECT COUNT(*) FROM {table_name}")
                            )
                            count = result.scalar_one()
                            table_counts[table_name] = count

                    # Check foreign key pragma
                    fk_check = connection.execute(
                        text("PRAGMA foreign_keys")
                    ).scalar_one()
                    foreign_key_constraints = fk_check == 1

            except Exception as e:
                self._add_log("db_integrity_error", f"Error checking DB integrity: {e}")

        return {
            "database_exists": db_exists,
            "tables_exist": tables_exist,
            "database_size": db_size,
            "foreign_key_constraints": foreign_key_constraints,
            "table_counts": table_counts,
        }

    def _find_orphaned_records(self) -> Dict[str, Any]:
        """Finds and counts orphaned records in association tables."""
        session = self.Session()
        orphaned_paper_collections = 0
        orphaned_paper_authors = 0
        try:
            # Orphaned PaperCollection entries (paper_id or collection_id does not exist)
            orphaned_paper_collections = (
                session.query(PaperCollection)
                .filter(
                    ~PaperCollection.paper_id.in_(session.query(Paper.id)),
                    ~PaperCollection.collection_id.in_(session.query(Collection.id)),
                )
                .count()
            )

            # Orphaned PaperAuthor entries (paper_id or author_id does not exist)
            orphaned_paper_authors = (
                session.query(PaperAuthor)
                .filter(
                    ~PaperAuthor.paper_id.in_(session.query(Paper.id)),
                    ~PaperAuthor.author_id.in_(session.query(Author.id)),
                )
                .count()
            )

        except Exception as e:
            self._add_log(
                "orphaned_records_error", f"Error finding orphaned records: {e}"
            )
        finally:
            session.close()

        return {
            "summary": {
                "orphaned_paper_collections": orphaned_paper_collections,
                "orphaned_paper_authors": orphaned_paper_authors,
            }
        }

    def _find_orphaned_pdfs(self) -> Dict[str, Any]:
        """Finds PDF files in the data directory not linked to any paper."""
        pdf_dir = Path(self.db_path).parent / "pdfs"
        orphaned_pdf_files = []
        if pdf_dir.is_dir():
            session = self.Session()
            try:
                db_pdf_paths = {
                    Path(p.file_path).name
                    for p in session.query(Paper)
                    .filter(Paper.file_path.isnot(None))
                    .all()
                }
                for pdf_file in pdf_dir.glob("*.pdf"):
                    if pdf_file.name not in db_pdf_paths:
                        orphaned_pdf_files.append(str(pdf_file))
            except Exception as e:
                self._add_log(
                    "orphaned_pdfs_error", f"Error finding orphaned PDFs: {e}"
                )
            finally:
                session.close()
        return {
            "summary": {"orphaned_pdf_files": len(orphaned_pdf_files)},
            "details": orphaned_pdf_files,
        }

    def _find_absolute_pdf_paths(self) -> Dict[str, Any]:
        """Finds papers with absolute PDF paths instead of relative ones."""
        session = self.Session()
        absolute_paths = []
        try:
            papers_with_abs_paths = (
                session.query(Paper)
                .filter(
                    Paper.file_path.isnot(None),
                    # This is a placeholder, actual check needs to be more robust
                )
                .all()
            )

            # Manual check for absolute paths
            for paper in papers_with_abs_paths:
                if paper.file_path and Path(paper.file_path).is_absolute():
                    absolute_paths.append(paper.id)

        except Exception as e:
            self._add_log(
                "absolute_paths_error", f"Error finding absolute PDF paths: {e}"
            )
        finally:
            session.close()
        return {
            "summary": {"absolute_path_count": len(absolute_paths)},
            "details": absolute_paths,
        }

    def _find_missing_pdfs(self) -> Dict[str, Any]:
        """Finds papers whose linked PDF files are missing from disk."""
        session = self.Session()
        missing_pdfs = []
        pdf_dir = Path(self.db_path).parent / "pdfs"
        try:
            papers_with_files = (
                session.query(Paper).filter(Paper.file_path.isnot(None)).all()
            )
            for paper in papers_with_files:
                if paper.file_path:
                    full_path = pdf_dir / Path(paper.file_path).name
                    if not full_path.exists():
                        missing_pdfs.append(paper.id)
        except Exception as e:
            self._add_log("missing_pdfs_error", f"Error finding missing PDFs: {e}")
        finally:
            session.close()
        return {
            "summary": {"missing_pdf_count": len(missing_pdfs)},
            "details": missing_pdfs,
        }

    def _check_system_health(self) -> Dict[str, Any]:
        """Checks system-level health (Python version, dependencies)."""
        import sys
        import importlib.util

        python_version = sys.version
        dependencies = {
            "sqlalchemy": importlib.util.find_spec("sqlalchemy") is not None,
            "rich": importlib.util.find_spec("rich") is not None,
            "textual": importlib.util.find_spec("textual") is not None,
            "prompt_toolkit": importlib.util.find_spec("prompt_toolkit")
            is not None,  # Keep for now as it's still in app
            "requests": importlib.util.find_spec("requests") is not None,
            "openai": importlib.util.find_spec("openai") is not None,
        }

        # Basic disk space check (for the drive where the DB is)
        disk_space = {}
        try:
            statvfs = os.statvfs(Path(self.db_path).parent)
            total_bytes = statvfs.f_blocks * statvfs.f_bsize
            free_bytes = statvfs.f_bavail * statvfs.f_bsize
            disk_space = {
                "total_mb": total_bytes // (1024 * 1024),
                "free_mb": free_bytes // (1024 * 1024),
            }
        except Exception as e:
            self._add_log("disk_space_error", f"Error checking disk space: {e}")

        return {
            "python_version": python_version,
            "dependencies": dependencies,
            "disk_space": disk_space,
        }

    def _check_terminal_capabilities(self) -> Dict[str, Any]:
        """Checks terminal capabilities (unicode, color, size)."""
        # These checks are more relevant for prompt_toolkit, but we can keep placeholders
        # for general terminal info.
        import sys
        import shutil

        terminal_type = os.getenv("TERM", "unknown")
        unicode_support = sys.stdout.encoding == "UTF-8"
        color_support = os.getenv("TERM") not in ("dumb", "xterm-mono")  # Basic check

        terminal_size = shutil.get_terminal_size(fallback=(80, 24))

        return {
            "terminal_type": terminal_type,
            "unicode_support": unicode_support,
            "color_support": color_support,
            "terminal_size": {
                "columns": terminal_size.columns,
                "lines": terminal_size.lines,
            },
        }

    def clean_orphaned_records(self) -> Dict[str, int]:
        """Cleans up orphaned records in association tables."""
        session = self.Session()
        cleaned_counts = {
            "paper_collections": 0,
            "paper_authors": 0,
        }
        try:
            # Delete orphaned PaperCollection entries
            orphaned_pcs = (
                session.query(PaperCollection)
                .filter(
                    ~PaperCollection.paper_id.in_(session.query(Paper.id)),
                    ~PaperCollection.collection_id.in_(session.query(Collection.id)),
                )
                .all()
            )
            for pc in orphaned_pcs:
                session.delete(pc)
                cleaned_counts["paper_collections"] += 1

            # Delete orphaned PaperAuthor entries
            orphaned_pas = (
                session.query(PaperAuthor)
                .filter(
                    ~PaperAuthor.paper_id.in_(session.query(Paper.id)),
                    ~PaperAuthor.author_id.in_(session.query(Author.id)),
                )
                .all()
            )
            for pa in orphaned_pas:
                session.delete(pa)
                cleaned_counts["paper_authors"] += 1

            session.commit()
            self._add_log(
                "clean_records",
                f"Cleaned {cleaned_counts['paper_collections']} paper-collections and {cleaned_counts['paper_authors']} paper-authors.",
            )
        except Exception as e:
            session.rollback()
            self._add_log(
                "clean_records_error", f"Error cleaning orphaned records: {e}"
            )
        finally:
            session.close()
        return cleaned_counts

    def clean_orphaned_pdfs(self) -> Dict[str, int]:
        """Deletes PDF files from the data directory not linked to any paper."""
        pdf_dir = Path(self.db_path).parent / "pdfs"
        cleaned_count = 0
        if pdf_dir.is_dir():
            session = self.Session()
            try:
                db_pdf_paths = {
                    Path(p.file_path).name
                    for p in session.query(Paper)
                    .filter(Paper.file_path.isnot(None))
                    .all()
                }
                for pdf_file in pdf_dir.glob("*.pdf"):
                    if pdf_file.name not in db_pdf_paths:
                        try:
                            os.remove(pdf_file)
                            cleaned_count += 1
                            self._add_log(
                                "clean_pdf", f"Deleted orphaned PDF: {pdf_file.name}"
                            )
                        except OSError as e:
                            self._add_log(
                                "clean_pdf_error",
                                f"Error deleting {pdf_file.name}: {e}",
                            )
            except Exception as e:
                self._add_log("clean_pdf_error", f"Error finding PDFs to clean: {e}")
            finally:
                session.close()
        return {"deleted_pdfs": cleaned_count}

    def fix_absolute_pdf_paths(self) -> Dict[str, int]:
        """Converts absolute PDF paths in the database to relative paths."""
        session = self.Session()
        fixed_count = 0
        pdf_dir = Path(self.db_path).parent / "pdfs"
        try:
            papers_with_abs_paths = (
                session.query(Paper)
                .filter(
                    Paper.file_path.isnot(None),
                    # This filter is still problematic for SQLite, will rely on manual check
                )
                .all()
            )

            for paper in papers_with_abs_paths:
                if paper.file_path and Path(paper.file_path).is_absolute():
                    try:
                        # Make path relative to the pdf_dir
                        relative_path = Path(paper.file_path).relative_to(pdf_dir)
                        paper.file_path = str(relative_path)
                        session.add(paper)
                        fixed_count += 1
                        self._add_log(
                            "fix_path",
                            f"Fixed absolute path for paper {paper.id}: {paper.file_path}",
                        )
                    except ValueError:  # Path is not relative to pdf_dir
                        self._add_log(
                            "fix_path_warning",
                            f"Could not make path relative for paper {paper.id}: {paper.file_path}",
                        )

            session.commit()
        except Exception as e:
            session.rollback()
            self._add_log("fix_path_error", f"Error fixing absolute PDF paths: {e}")
        finally:
            session.close()
        return {"fixed_paths": fixed_count}

    def clean_pdf_filenames(self) -> Dict[str, int]:
        """Renames PDF files to follow a consistent naming convention."""
        session = self.Session()
        renamed_count = 0
        pdf_dir = Path(self.db_path).parent / "pdfs"
        try:
            papers = session.query(Paper).filter(Paper.file_path.isnot(None)).all()
            for paper in papers:
                if paper.file_path:
                    old_path = pdf_dir / Path(paper.file_path).name
                    if old_path.exists():
                        # Generate new filename based on convention
                        new_filename = self._generate_pdf_filename(paper)
                        new_path = pdf_dir / new_filename

                        if old_path != new_path:
                            try:
                                os.rename(old_path, new_path)
                                paper.file_path = new_filename  # Update DB record
                                session.add(paper)
                                renamed_count += 1
                                self._add_log(
                                    "rename_pdf",
                                    f"Renamed PDF for paper {paper.id} from {old_path.name} to {new_filename}",
                                )
                            except OSError as e:
                                self._add_log(
                                    "rename_pdf_error",
                                    f"Error renaming {old_path.name} to {new_filename}: {e}",
                                )
            session.commit()
        except Exception as e:
            session.rollback()
            self._add_log("rename_pdf_error", f"Error cleaning PDF filenames: {e}")
        finally:
            session.close()
        return {"renamed_files": renamed_count}

    def _generate_pdf_filename(self, paper: Paper) -> str:
        """Generates a consistent filename for a PDF based on paper metadata."""
        author_lastname = ""
        if paper.authors:
            first_author = paper.authors[0]
            if first_author.last_name:
                author_lastname = first_author.last_name.replace(" ", "_")

        year = str(paper.year) if paper.year else ""

        # Get first significant word from title
        first_word = ""
        if paper.title:
            words = [w for w in paper.title.split() if w.isalnum()]
            if words:
                first_word = words[0].lower()

        # Use a hash of the PDF content for uniqueness (if PDF exists)
        file_hash = ""
        if paper.file_path:
            full_path = Path(self.db_path).parent / "pdfs" / Path(paper.file_path).name
            if full_path.exists():
                import hashlib

                hasher = hashlib.sha1()
                with open(full_path, "rb") as f:
                    buf = f.read()
                    hasher.update(buf)
                file_hash = hasher.hexdigest()[:6]

        parts = [author_lastname, year, first_word, file_hash]
        filename = "_".join(filter(None, parts)) + ".pdf"
        return filename
