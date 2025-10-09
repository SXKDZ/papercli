from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from ng.db.database import get_pdf_directory
from ng.db.models import Author, Paper, PaperAuthor
from ng.services.formatting import format_file_size, format_title_by_words
from ng.services.pdf import PDFManager


class DatabaseHealthService:
    """Service for diagnosing and fixing database issues."""

    def __init__(self, db_path: str = None, app=None):
        # If db_path is not provided, get it from app
        self.db_path = db_path if db_path else (app.db_path if app else None)
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        # Enable foreign key constraints for SQLite
        def _enable_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        event.listen(self.engine, "connect", _enable_foreign_keys)

        self.Session = sessionmaker(bind=self.engine)
        self.app = app

    def _add_log(self, action: str, details: str):
        self.app._add_log(action, details)

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Runs a comprehensive diagnostic check on the database and system."""
        self._add_log("diagnostic_start", "Starting full database diagnostic")

        try:
            report = {
                "timestamp": datetime.now().isoformat(),
                "database_checks": self._check_database_integrity(),
                "orphaned_records": self._find_orphaned_records(),
                "orphaned_pdfs": self._find_orphaned_pdfs(),
                "orphaned_htmls": self._find_orphaned_htmls(),
                "absolute_pdf_paths": self._find_absolute_pdf_paths(),
                "missing_pdfs": self._find_missing_pdfs(),
                "missing_htmls": self._find_missing_htmls(),
                "pdf_statistics": self._get_pdf_statistics(),
                "html_statistics": self._get_html_statistics(),
                "system_checks": self._check_system_health(),
                "terminal_checks": self._check_terminal_capabilities(),
                "issues_found": [],
                "recommendations": [],
            }

            self._add_log(
                "diagnostic_progress", "Basic checks completed, analyzing results"
            )

        except Exception as e:
            self._add_log("diagnostic_error", f"Error during diagnostic setup: {e}")
            raise

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

        if report["orphaned_htmls"]["summary"]["orphaned_html_files"] > 0:
            report["issues_found"].append(
                "Orphaned HTML files found (not linked to any paper)."
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

        if report["missing_htmls"]["summary"]["missing_html_count"] > 0:
            report["issues_found"].append("Papers with missing HTML snapshot files found.")
            report["recommendations"].append(
                "Verify HTML snapshot file locations or remove missing papers."
            )

        self._add_log(
            "diagnostic_complete",
            f"Diagnostic completed, found {len(report['issues_found'])} issues",
        )
        return report

    def _check_database_integrity(self) -> Dict[str, Any]:
        """Checks basic database file and table integrity."""
        self._add_log(
            "db_integrity_start", f"Checking database integrity for {self.db_path}"
        )

        db_exists = Path(self.db_path).exists()
        tables_exist = False
        table_counts = {}
        foreign_key_constraints = False
        db_size = 0

        if db_exists:
            db_size = os.path.getsize(self.db_path)
            self._add_log(
                "db_integrity_info", f"Database exists, size: {db_size} bytes"
            )

            try:
                with self.engine.connect() as connection:
                    inspector = inspect(self.engine)
                    existing_tables = inspector.get_table_names()
                    if existing_tables:
                        tables_exist = True
                        self._add_log(
                            "db_integrity_info",
                            f"Found {len(existing_tables)} tables: {existing_tables}",
                        )

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
                    self._add_log(
                        "db_integrity_info",
                        f"Foreign key constraints: {foreign_key_constraints}",
                    )

            except Exception as e:
                self._add_log("db_integrity_error", f"Error checking DB integrity: {e}")
        else:
            self._add_log(
                "db_integrity_warning", f"Database file does not exist: {self.db_path}"
            )

        result = {
            "database_exists": db_exists,
            "tables_exist": tables_exist,
            "database_size": db_size,
            "foreign_key_constraints": foreign_key_constraints,
            "table_counts": table_counts,
        }

        self._add_log("db_integrity_complete", f"Database integrity check complete")
        return result

    def _find_orphaned_records(self) -> Dict[str, Any]:
        """Finds and counts orphaned records in association tables."""
        self._add_log("orphaned_records_start", "Checking for orphaned records")

        session = self.Session()
        orphaned_paper_collections = 0
        orphaned_paper_authors = 0
        try:
            # Orphaned paper_collections entries (paper_id or collection_id does not exist)
            # Use raw SQL since paper_collections is a Table, not a model class
            result = session.execute(
                text(
                    """
                SELECT COUNT(*) FROM paper_collections pc
                LEFT JOIN papers p ON pc.paper_id = p.id
                LEFT JOIN collections c ON pc.collection_id = c.id
                WHERE p.id IS NULL OR c.id IS NULL
            """
                )
            )
            orphaned_paper_collections = result.scalar_one()
            self._add_log(
                "orphaned_records_info",
                f"Found {orphaned_paper_collections} orphaned paper-collection associations",
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
            self._add_log(
                "orphaned_records_info",
                f"Found {orphaned_paper_authors} orphaned paper-author associations",
            )

        except Exception as e:
            self._add_log(
                "orphaned_records_error", f"Error finding orphaned records: {e}"
            )
        finally:
            session.close()

        result = {
            "summary": {
                "orphaned_paper_collections": orphaned_paper_collections,
                "orphaned_paper_authors": orphaned_paper_authors,
            }
        }

        self._add_log("orphaned_records_complete", f"Orphaned records check complete")
        return result

    def _find_orphaned_pdfs(self) -> Dict[str, Any]:
        """Finds PDF files in the data directory not linked to any paper."""
        pdf_dir = Path(get_pdf_directory())
        orphaned_pdf_files = []
        if pdf_dir.is_dir():
            session = self.Session()
            try:
                db_pdf_paths = {
                    Path(p.pdf_path).name
                    for p in session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None))
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

    def _find_orphaned_htmls(self) -> Dict[str, Any]:
        """Finds HTML files in the html_snapshots directory not linked to any paper."""
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = Path(os.path.dirname(db_manager.db_path))
        html_dir = data_dir / "html_snapshots"
        orphaned_html_files = []
        if html_dir.is_dir():
            session = self.Session()
            try:
                db_html_paths = {
                    Path(p.html_snapshot_path).name
                    for p in session.query(Paper)
                    .filter(Paper.html_snapshot_path.isnot(None))
                    .all()
                }
                for html_file in html_dir.glob("*.html"):
                    if html_file.name not in db_html_paths:
                        orphaned_html_files.append(str(html_file))
            except Exception as e:
                self._add_log(
                    "orphaned_htmls_error", f"Error finding orphaned HTML files: {e}"
                )
            finally:
                session.close()
        return {
            "summary": {"orphaned_html_files": len(orphaned_html_files)},
            "details": orphaned_html_files,
        }

    def _find_absolute_pdf_paths(self) -> Dict[str, Any]:
        """Finds papers with absolute PDF paths instead of relative ones."""
        session = self.Session()
        absolute_paths = []
        try:
            papers_with_abs_paths = (
                session.query(Paper)
                .filter(
                    Paper.pdf_path.isnot(None),
                    # This is a placeholder, actual check needs to be more robust
                )
                .all()
            )

            # Manual check for absolute paths
            for paper in papers_with_abs_paths:
                if paper.pdf_path and Path(paper.pdf_path).is_absolute():
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
        missing_pdf_details = []
        pdf_dir = Path(get_pdf_directory())

        self._add_log("missing_pdfs_start", f"Checking for missing PDFs in {pdf_dir}")

        try:
            # Get all papers
            all_papers = session.query(Paper).all()
            papers_with_paths = [p for p in all_papers if p.pdf_path]
            papers_without_paths = [p for p in all_papers if not p.pdf_path]

            self._add_log(
                "missing_pdfs_info",
                f"Found {len(all_papers)} total papers: {len(papers_with_paths)} with PDF paths, {len(papers_without_paths)} without PDF paths",
            )

            # Only check papers that have PDF paths set for file existence
            # (papers without PDF paths are not considered "missing" - they just don't have PDFs)
            for paper in papers_with_paths:
                if paper.pdf_path:
                    # Handle both relative and absolute paths properly
                    if Path(paper.pdf_path).is_absolute():
                        # Absolute path - check directly
                        full_path = Path(paper.pdf_path)
                    else:
                        # Relative path - resolve relative to PDF directory
                        full_path = pdf_dir / paper.pdf_path

                    if not full_path.exists():
                        missing_pdfs.append(paper.id)
                        missing_pdf_details.append(
                            {
                                "paper_id": paper.id,
                                "title": format_title_by_words(paper.title or ""),
                                "pdf_path": paper.pdf_path,
                                "resolved_path": str(full_path),
                                "path_type": (
                                    "absolute"
                                    if Path(paper.pdf_path).is_absolute()
                                    else "relative"
                                ),
                            }
                        )
                        self._add_log(
                            "missing_pdfs_found",
                            f"Missing PDF for paper {paper.id}: {paper.pdf_path}",
                        )

        except Exception as e:
            self._add_log("missing_pdfs_error", f"Error finding missing PDFs: {e}")
        finally:
            session.close()

        self._add_log(
            "missing_pdfs_complete",
            f"Found {len(missing_pdfs)} papers with missing PDF files",
        )

        return {
            "summary": {"missing_pdf_count": len(missing_pdfs)},
            "details": missing_pdf_details,
        }

    def _find_missing_htmls(self) -> Dict[str, Any]:
        """Finds papers whose linked HTML snapshot files are missing from disk."""
        from ng.db.database import get_db_manager

        session = self.Session()
        missing_htmls = []
        missing_html_details = []

        db_manager = get_db_manager()
        data_dir = Path(os.path.dirname(db_manager.db_path))
        html_dir = data_dir / "html_snapshots"

        self._add_log("missing_htmls_start", f"Checking for missing HTML snapshots in {html_dir}")

        try:
            # Get all papers
            all_papers = session.query(Paper).all()
            papers_with_html = [p for p in all_papers if p.html_snapshot_path]
            papers_without_html = [p for p in all_papers if not p.html_snapshot_path]

            self._add_log(
                "missing_htmls_info",
                f"Found {len(all_papers)} total papers: {len(papers_with_html)} with HTML paths, {len(papers_without_html)} without HTML paths",
            )

            # Only check papers that have HTML snapshot paths set
            # (unlike PDFs, not having an HTML snapshot is normal, so we don't report it)
            for paper in papers_with_html:
                if paper.html_snapshot_path:
                    # Handle both relative and absolute paths properly
                    if Path(paper.html_snapshot_path).is_absolute():
                        # Absolute path - check directly
                        full_path = Path(paper.html_snapshot_path)
                    else:
                        # Relative path - resolve relative to HTML directory
                        full_path = html_dir / paper.html_snapshot_path

                    if not full_path.exists():
                        missing_htmls.append(paper.id)
                        missing_html_details.append(
                            {
                                "paper_id": paper.id,
                                "title": format_title_by_words(paper.title or ""),
                                "html_snapshot_path": paper.html_snapshot_path,
                                "resolved_path": str(full_path),
                                "path_type": (
                                    "absolute"
                                    if Path(paper.html_snapshot_path).is_absolute()
                                    else "relative"
                                ),
                            }
                        )
                        self._add_log(
                            "missing_htmls_found",
                            f"Missing HTML snapshot for paper {paper.id}: {paper.html_snapshot_path}",
                        )

        except Exception as e:
            self._add_log("missing_htmls_error", f"Error finding missing HTML snapshots: {e}")
        finally:
            session.close()

        self._add_log(
            "missing_htmls_complete",
            f"Found {len(missing_htmls)} papers with missing HTML snapshot files",
        )

        return {
            "summary": {"missing_html_count": len(missing_htmls)},
            "details": missing_html_details,
        }

    def _get_pdf_statistics(self) -> Dict[str, Any]:
        """Get statistics about the PDF folder including file count and total size."""
        pdf_dir = Path(get_pdf_directory())

        self._add_log("pdf_stats_start", f"Collecting PDF statistics from {pdf_dir}")

        stats = {
            "pdf_folder_exists": False,
            "total_pdf_files": 0,
            "total_size_bytes": 0,
            "total_size_formatted": "0 B",
            "pdf_folder_path": str(pdf_dir),
        }

        try:
            if not pdf_dir.exists():
                self._add_log("pdf_stats_info", "PDF folder does not exist")
                return stats

            stats["pdf_folder_exists"] = True
            pdf_files = list(pdf_dir.glob("*.pdf"))
            stats["total_pdf_files"] = len(pdf_files)

            if pdf_files:
                total_size = 0
                for pdf_file in pdf_files:
                    try:
                        size = pdf_file.stat().st_size
                        total_size += size
                    except Exception as e:
                        self._add_log(
                            "pdf_stats_warning",
                            f"Error getting size for {pdf_file.name}: {e}",
                        )
                        continue

                stats["total_size_bytes"] = total_size
                stats["total_size_formatted"] = format_file_size(total_size)

            self._add_log(
                "pdf_stats_complete",
                f"Found {stats['total_pdf_files']} PDF files, total size: {stats['total_size_formatted']}",
            )

        except Exception as e:
            self._add_log("pdf_stats_error", f"Error collecting PDF statistics: {e}")
            stats["error"] = str(e)

        return stats

    def _get_html_statistics(self) -> Dict[str, Any]:
        """Get statistics about the HTML snapshots folder including file count and total size."""
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = Path(os.path.dirname(db_manager.db_path))
        html_dir = data_dir / "html_snapshots"

        self._add_log("html_stats_start", f"Collecting HTML statistics from {html_dir}")

        stats = {
            "html_folder_exists": False,
            "total_html_files": 0,
            "total_size_bytes": 0,
            "total_size_formatted": "0 B",
            "html_folder_path": str(html_dir),
        }

        try:
            if not html_dir.exists():
                self._add_log("html_stats_info", "HTML snapshots folder does not exist")
                return stats

            stats["html_folder_exists"] = True
            html_files = list(html_dir.glob("*.html"))
            stats["total_html_files"] = len(html_files)

            if html_files:
                total_size = 0
                for html_file in html_files:
                    try:
                        size = html_file.stat().st_size
                        total_size += size
                    except Exception as e:
                        self._add_log(
                            "html_stats_warning",
                            f"Error getting size for {html_file.name}: {e}",
                        )
                        continue

                stats["total_size_bytes"] = total_size
                stats["total_size_formatted"] = format_file_size(total_size)

            self._add_log(
                "html_stats_complete",
                f"Found {stats['total_html_files']} HTML files, total size: {stats['total_size_formatted']}",
            )

        except Exception as e:
            self._add_log("html_stats_error", f"Error collecting HTML statistics: {e}")
            stats["error"] = str(e)

        return stats

    def _check_system_health(self) -> Dict[str, Any]:
        """Checks system-level health (Python version, dependencies)."""
        self._add_log("system_health_start", "Checking system health")

        try:
            python_version = sys.version
            self._add_log(
                "system_health_info", f"Python version: {python_version[:50]}..."
            )

            dependencies = {}
            
            # Mapping of package names to their actual import names (for special cases)
            package_to_module = {
                "beautifulsoup4": "bs4",
                "pypdf2": "PyPDF2",
                "python-levenshtein": "Levenshtein",
                "python-dotenv": "dotenv",
            }
            
            # Read dependencies from requirements.txt
            requirements_path = Path(__file__).parent.parent.parent / "requirements.txt"
            dep_modules = []
            
            if requirements_path.exists():
                try:
                    with open(requirements_path, "r") as f:
                        for line in f:
                            line = line.strip()
                            # Skip empty lines and comments
                            if not line or line.startswith("#"):
                                continue
                            # Extract package name (remove version specifiers)
                            # Handle formats like: package>=1.0.0, package==1.0.0, package
                            package_name = line.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].split("~=")[0].strip()
                            if package_name:
                                package_lower = package_name.lower()
                                # Check if there's a special mapping, otherwise use default conversion
                                if package_lower in package_to_module:
                                    module_name = package_to_module[package_lower]
                                else:
                                    # Default: lowercase and replace hyphens with underscores
                                    module_name = package_lower.replace("-", "_")
                                dep_modules.append((module_name, package_name))
                    
                    self._add_log(
                        "system_health_info", 
                        f"Found {len(dep_modules)} dependencies in requirements.txt"
                    )
                except Exception as e:
                    self._add_log(
                        "system_health_warning",
                        f"Error reading requirements.txt: {e}",
                    )
                    # Fallback to hardcoded list if requirements.txt can't be read
                    dep_modules = [
                        ("sqlalchemy", "SQLAlchemy"),
                        ("rich", "rich"),
                        ("textual", "textual"),
                        ("requests", "requests"),
                        ("openai", "openai"),
                    ]
            else:
                self._add_log(
                    "system_health_warning",
                    f"requirements.txt not found at {requirements_path}",
                )
                # Fallback to hardcoded list
                dep_modules = [
                    ("sqlalchemy", "SQLAlchemy"),
                    ("rich", "rich"),
                    ("textual", "textual"),
                    ("requests", "requests"),
                    ("openai", "openai"),
                ]

            for module_name, package_name in dep_modules:
                try:
                    if importlib.util.find_spec(module_name) is not None:
                        # Try to get version
                        version = None
                        try:
                            # First try to import and get __version__
                            module = importlib.import_module(module_name)
                            if hasattr(module, "__version__"):
                                version = module.__version__
                            elif hasattr(module, "VERSION"):
                                version = module.VERSION
                        except:
                            pass
                        
                        # If that didn't work, try pkg_resources or importlib.metadata
                        if not version:
                            try:
                                from importlib.metadata import version as get_version
                                version = get_version(package_name)
                            except:
                                try:
                                    import pkg_resources
                                    version = pkg_resources.get_distribution(package_name).version
                                except:
                                    version = "installed"
                        
                        dependencies[module_name] = {"installed": True, "version": version}
                        self._add_log(
                            "system_health_info",
                            f"Module {module_name}: Found (version {version})",
                        )
                    else:
                        dependencies[module_name] = {"installed": False, "version": None}
                        self._add_log(
                            "system_health_info",
                            f"Module {module_name}: Missing",
                        )
                except Exception as e:
                    self._add_log(
                        "system_health_warning",
                        f"Error checking module {module_name}: {e}",
                    )
                    dependencies[module_name] = {"installed": False, "version": None}

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
                self._add_log(
                    "system_health_info", f"Disk space: {disk_space['free_mb']}MB free"
                )
            except Exception as e:
                self._add_log("disk_space_error", f"Error checking disk space: {e}")
                disk_space = {"error": str(e)}

            result = {
                "python_version": python_version,
                "dependencies": dependencies,
                "disk_space": disk_space,
            }

            self._add_log("system_health_complete", "System health check complete")
            return result

        except Exception as e:
            self._add_log(
                "system_health_error", f"Critical error in system health check: {e}"
            )
            return {
                "python_version": "Error retrieving",
                "dependencies": {},
                "disk_space": {"error": str(e)},
            }

    def _check_terminal_capabilities(self) -> Dict[str, Any]:
        """Checks terminal capabilities for Textual application mode."""
        try:
            # In Textual application mode, we should report capabilities differently
            terminal_type = "textual-app"

            # For Textual apps, we can assume good capabilities
            unicode_support = True  # Textual handles Unicode well
            color_support = True  # Textual supports rich colors

            # Get actual terminal size for the underlying terminal
            try:
                terminal_size = shutil.get_terminal_size(fallback=(80, 24))
                size_dict = {
                    "columns": terminal_size.columns,
                    "lines": terminal_size.lines,
                }
            except Exception as e:
                self._add_log(
                    "terminal_check_warning", f"Error getting terminal size: {e}"
                )
                size_dict = {"columns": 80, "lines": 24}

            # Additional Textual-specific capabilities
            textual_features = {
                "rich_rendering": True,
                "mouse_support": True,
                "keyboard_events": True,
                "async_events": True,
            }

            result = {
                "terminal_type": terminal_type,
                "unicode_support": unicode_support,
                "color_support": color_support,
                "terminal_size": size_dict,
                "textual_features": textual_features,
            }

            self._add_log(
                "terminal_check",
                f"Terminal capabilities for Textual app: {terminal_type}, unicode: {unicode_support}, colors: {color_support}",
            )
            return result

        except Exception as e:
            self._add_log(
                "terminal_check_error",
                f"Critical error in terminal capabilities check: {e}",
            )
            # Return safe defaults with Textual assumptions
            return {
                "terminal_type": "textual-app-fallback",
                "unicode_support": True,
                "color_support": True,
                "terminal_size": {"columns": 80, "lines": 24},
                "textual_features": {
                    "rich_rendering": True,
                    "mouse_support": True,
                    "keyboard_events": True,
                    "async_events": True,
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
            # Delete orphaned paper_collections entries using raw SQL
            result = session.execute(
                text(
                    """
                DELETE FROM paper_collections
                WHERE paper_id NOT IN (SELECT id FROM papers)
                   OR collection_id NOT IN (SELECT id FROM collections)
            """
                )
            )
            cleaned_counts["paper_collections"] = result.rowcount

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
                f"Cleaned {cleaned_counts['paper_collections']} paper-collections and {cleaned_counts['paper_authors']} paper-authors",
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
        pdf_dir = Path(get_pdf_directory())
        cleaned_count = 0
        if pdf_dir.is_dir():
            session = self.Session()
            try:
                db_pdf_paths = {
                    Path(p.pdf_path).name
                    for p in session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None))
                    .all()
                }

                # Get current time for age-based filtering
                current_time = time.time()

                for pdf_file in pdf_dir.glob("*.pdf"):
                    if pdf_file.name not in db_pdf_paths:
                        # Safety checks to avoid deleting files during active operations
                        try:
                            # Check 1: Don't delete files that are very recent (< 2 minutes old)
                            # This protects against deleting files that are still being downloaded/processed
                            file_age = current_time - pdf_file.stat().st_mtime
                            if file_age < 120:  # Less than 2 minutes old
                                self._add_log(
                                    "clean_pdf_skip",
                                    f"Skipping recent file (age: {file_age:.1f}s): {pdf_file.name}",
                                )
                                continue

                            # Check 2: Don't delete files with temporary naming patterns
                            # These patterns indicate active download/processing operations
                            if (
                                pdf_file.name.endswith("_temp00.pdf")
                                or "_temp" in pdf_file.name
                                or len(pdf_file.name.split("_")[-1].replace(".pdf", ""))
                                == 6
                            ):  # 6-char hash pattern
                                # Additional check: if it's a temp file that's old enough, it might be stale
                                if file_age < 300:  # Less than 5 minutes old
                                    self._add_log(
                                        "clean_pdf_skip",
                                        f"Skipping potential temp file: {pdf_file.name}",
                                    )
                                    continue

                            # File passed all safety checks, safe to delete
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
                            self._add_log(
                                "clean_pdf_error",
                                f"Error checking {pdf_file.name}: {e}",
                            )
            except Exception as e:
                self._add_log("clean_pdf_error", f"Error finding PDFs to clean: {e}")
            finally:
                session.close()
        return {"deleted_pdfs": cleaned_count}

    def clean_orphaned_htmls(self) -> Dict[str, int]:
        """Deletes HTML files from html_snapshots directory not linked to any paper."""
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = Path(os.path.dirname(db_manager.db_path))
        html_dir = data_dir / "html_snapshots"
        cleaned_count = 0
        if html_dir.is_dir():
            session = self.Session()
            try:
                db_html_paths = {
                    Path(p.html_snapshot_path).name
                    for p in session.query(Paper)
                    .filter(Paper.html_snapshot_path.isnot(None))
                    .all()
                }

                current_time = time.time()

                for html_file in html_dir.glob("*.html"):
                    if html_file.name not in db_html_paths:
                        try:
                            # Don't delete files that are very recent (< 2 minutes old)
                            file_age = current_time - html_file.stat().st_mtime
                            if file_age < 120:
                                self._add_log(
                                    "clean_html_skip",
                                    f"Skipping recent file (age: {file_age:.1f}s): {html_file.name}",
                                )
                                continue

                            os.remove(html_file)
                            cleaned_count += 1
                            self._add_log(
                                "clean_html", f"Deleted orphaned HTML: {html_file.name}"
                            )
                        except OSError as e:
                            self._add_log(
                                "clean_html_error",
                                f"Error deleting {html_file.name}: {e}",
                            )
                        except Exception as e:
                            self._add_log(
                                "clean_html_error",
                                f"Error checking {html_file.name}: {e}",
                            )
            except Exception as e:
                self._add_log(
                    "clean_html_error", f"Error finding HTML files to clean: {e}"
                )
            finally:
                session.close()
        return {"deleted_htmls": cleaned_count}

    def fix_absolute_pdf_paths(self) -> Dict[str, int]:
        """Converts absolute PDF paths in the database to relative paths."""
        session = self.Session()
        fixed_count = 0
        pdf_dir = Path(get_pdf_directory())
        try:
            papers_with_abs_paths = (
                session.query(Paper)
                .filter(
                    Paper.pdf_path.isnot(None),
                    # This filter is still problematic for SQLite, will rely on manual check
                )
                .all()
            )

            for paper in papers_with_abs_paths:
                if paper.pdf_path and Path(paper.pdf_path).is_absolute():
                    try:
                        # Make path relative to the pdf_dir
                        relative_path = Path(paper.pdf_path).relative_to(pdf_dir)
                        paper.pdf_path = str(relative_path)
                        session.add(paper)
                        fixed_count += 1
                        self._add_log(
                            "fix_path",
                            f"Fixed absolute path for paper {paper.id}: {paper.pdf_path}",
                        )
                    except ValueError:  # Path is not relative to pdf_dir
                        self._add_log(
                            "fix_path_warning",
                            f"Could not make path relative for paper {paper.id}: {paper.pdf_path}",
                        )

            session.commit()
        except Exception as e:
            session.rollback()
            self._add_log("fix_path_error", f"Error fixing absolute PDF paths: {e}")
        finally:
            session.close()
        return {"pdf_paths": fixed_count}

    def clean_pdf_filenames(self) -> Dict[str, int]:
        """Renames PDF files to follow a consistent naming convention."""
        session = self.Session()
        renamed_count = 0
        pdf_dir = Path(get_pdf_directory())
        pdf_manager = PDFManager(app=self.app)
        try:
            papers = session.query(Paper).filter(Paper.pdf_path.isnot(None)).all()
            for paper in papers:
                if paper.pdf_path:
                    old_path = pdf_dir / Path(paper.pdf_path).name
                    if old_path.exists():
                        # Generate new filename based on convention using PDFManager
                        # Convert Paper object to dictionary format expected by PDFManager
                        # IMPORTANT: use ordered authors so first entry is the first author
                        author_names: list[str] = []
                        ordered = (
                            paper.get_ordered_authors()
                            if hasattr(paper, "get_ordered_authors")
                            else list(paper.authors or [])
                        )
                        for author in ordered:
                            name = (getattr(author, "full_name", "") or "").strip()
                            if not name:
                                parts = []
                                if getattr(author, "first_name", None):
                                    parts.append(author.first_name)
                                if getattr(author, "last_name", None):
                                    parts.append(author.last_name)
                                name = " ".join(parts).strip()
                            if name:
                                author_names.append(name)

                        paper_data = {
                            "authors": author_names,
                            "year": paper.year,
                            "title": paper.title,
                        }
                        new_filename = pdf_manager._generate_pdf_filename(
                            paper_data, str(old_path)
                        )
                        new_path = pdf_dir / new_filename

                        if old_path != new_path:
                            try:
                                os.rename(old_path, new_path)
                                paper.pdf_path = new_filename  # Update DB record
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
