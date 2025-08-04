"""Database health service - Business logic for database diagnostics and maintenance."""

import os
import shutil
from datetime import datetime
from typing import Any
from typing import Dict
from typing import List

from sqlalchemy import text

from ..db.database import get_db_manager
from ..db.database import get_db_session
from ..db.models import Author
from ..db.models import Collection
from ..db.models import Paper


class DatabaseHealthService:
    """Service for diagnosing and fixing database health issues."""

    def __init__(self, log_callback=None):
        self.issues_found = []
        self.fixes_applied = []
        self.log_callback = log_callback

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Run comprehensive database and system diagnostics."""
        self.issues_found = []
        self.fixes_applied = []

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "database_checks": self._check_database_health(),
            "orphaned_records": self._check_orphaned_records(),
            "orphaned_pdfs": self._check_orphaned_pdfs(),
            "missing_pdfs": self._check_missing_pdfs(),
            "absolute_pdf_paths": self._check_absolute_pdf_paths(),
            "system_checks": self._check_system_health(),
            "terminal_checks": self._check_terminal_setup(),
            "issues_found": self.issues_found,
            "fixes_applied": self.fixes_applied,
            "recommendations": [],
        }

        # Add recommendations based on findings
        report["recommendations"] = self._generate_recommendations(report)

        return report

    def _check_database_health(self) -> Dict[str, Any]:
        """Check database integrity and structure."""
        checks = {
            "database_exists": False,
            "tables_exist": False,
            "table_counts": {},
            "foreign_key_constraints": True,
            "database_size": 0,
        }

        try:
            with get_db_session() as session:
                # Check if database file exists
                db_manager = get_db_manager()
                db_path = db_manager.db_path
                checks["database_exists"] = os.path.exists(db_path)

                if checks["database_exists"]:
                    checks["database_size"] = os.path.getsize(db_path)

                # Check if tables exist and get counts
                try:
                    checks["table_counts"]["papers"] = session.query(Paper).count()
                    checks["table_counts"]["authors"] = session.query(Author).count()
                    checks["table_counts"]["collections"] = session.query(
                        Collection
                    ).count()
                    checks["tables_exist"] = True
                except Exception as e:
                    self.issues_found.append(f"Database tables missing or corrupt: {e}")
                    checks["tables_exist"] = False

                # Check foreign key constraints
                try:
                    result = session.execute(
                        text("PRAGMA foreign_key_check")
                    ).fetchall()
                    if result:
                        checks["foreign_key_constraints"] = False
                        self.issues_found.append(
                            f"Foreign key constraint violations found: {len(result)} issues"
                        )
                except Exception as e:
                    self.issues_found.append(f"Could not check foreign keys: {e}")

        except Exception as e:
            self.issues_found.append(f"Database connection failed: {e}")

        return checks

    def _check_orphaned_records(self) -> Dict[str, Any]:
        """Check for orphaned records in association tables."""
        orphaned = {"paper_collections": [], "paper_authors": [], "summary": {}}

        try:
            with get_db_session() as session:
                # Check orphaned paper_collections
                orphaned_pc = session.execute(
                    text(
                        """
                    SELECT pc.paper_id, pc.collection_id 
                    FROM paper_collections pc
                    LEFT JOIN papers p ON pc.paper_id = p.id
                    LEFT JOIN collections c ON pc.collection_id = c.id
                    WHERE p.id IS NULL OR c.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_collections"] = [
                    (row[0], row[1]) for row in orphaned_pc
                ]
                orphaned["summary"]["orphaned_paper_collections"] = len(orphaned_pc)

                # Check orphaned paper_authors
                orphaned_pa = session.execute(
                    text(
                        """
                    SELECT pa.paper_id, pa.author_id 
                    FROM paper_authors pa
                    LEFT JOIN papers p ON pa.paper_id = p.id
                    LEFT JOIN authors a ON pa.author_id = a.id
                    WHERE p.id IS NULL OR a.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_authors"] = [(row[0], row[1]) for row in orphaned_pa]
                orphaned["summary"]["orphaned_paper_authors"] = len(orphaned_pa)

                if orphaned_pc:
                    self.issues_found.append(
                        f"Found {len(orphaned_pc)} orphaned paper-collection associations"
                    )
                if orphaned_pa:
                    self.issues_found.append(
                        f"Found {len(orphaned_pa)} orphaned paper-author associations"
                    )

        except Exception as e:
            self.issues_found.append(f"Could not check orphaned records: {e}")

        return orphaned

    def _check_system_health(self) -> Dict[str, Any]:
        """Check system and environment health."""
        checks = {
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "dependencies": {},
            "disk_space": {},
            "permissions": {},
        }

        # Check required dependencies
        required_deps = ["sqlalchemy", "prompt_toolkit", "requests", "rich"]
        for dep in required_deps:
            try:
                __import__(dep)
                checks["dependencies"][dep] = "✓ Available"
            except ImportError:
                checks["dependencies"][dep] = "✗ Missing"
                self.issues_found.append(f"Missing required dependency: {dep}")

        # Check disk space
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            if os.path.exists(papercli_dir):
                statvfs = os.statvfs(papercli_dir)
                free_space = statvfs.f_frsize * statvfs.f_bavail
                checks["disk_space"]["free_bytes"] = free_space
                checks["disk_space"]["free_mb"] = free_space // (1024 * 1024)

                if free_space < 100 * 1024 * 1024:  # Less than 100MB
                    self.issues_found.append(
                        "Low disk space: less than 100MB available"
                    )
        except Exception:
            checks["disk_space"]["error"] = "Could not check disk space"

        # Check directory permissions
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            checks["permissions"]["papercli_dir_writable"] = os.access(
                papercli_dir, os.W_OK
            )
            if not checks["permissions"]["papercli_dir_writable"]:
                self.issues_found.append("PaperCLI directory is not writable")
        except Exception:
            checks["permissions"]["error"] = "Could not check permissions"

        return checks

    def _check_terminal_setup(self) -> Dict[str, Any]:
        """Check terminal capabilities and setup."""
        checks = {
            "terminal_type": os.environ.get("TERM", "unknown"),
            "colorterm": os.environ.get("COLORTERM", "not_set"),
            "terminal_size": {},
            "unicode_support": False,
            "color_support": False,
        }

        # Check terminal size
        try:
            size = shutil.get_terminal_size()
            checks["terminal_size"]["columns"] = size.columns
            checks["terminal_size"]["lines"] = size.lines

            if size.columns <= 125:
                self.issues_found.append(
                    "Terminal width is less than 125 columns (current: {})".format(
                        size.columns
                    )
                )
            if size.lines <= 35:
                self.issues_found.append(
                    "Terminal height is less than 35 lines (current: {})".format(
                        size.lines
                    )
                )
        except Exception:
            checks["terminal_size"]["error"] = "Could not determine terminal size"

        # Check Unicode support
        try:
            test_chars = "📄✓✗⚠"
            test_chars.encode("utf-8")
            checks["unicode_support"] = True
        except UnicodeEncodeError:
            checks["unicode_support"] = False
            self.issues_found.append("Terminal may not support Unicode characters")

        # Check color support
        if "color" in checks["terminal_type"].lower() or checks["colorterm"]:
            checks["color_support"] = True
        else:
            checks["color_support"] = False
            self.issues_found.append("Terminal may not support colors")

        return checks

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on diagnostic results."""
        recommendations = []

        # Database recommendations
        if not report["database_checks"]["tables_exist"]:
            recommendations.append("Run database migration to create missing tables")

        if (
            report["orphaned_records"]["summary"].get("orphaned_paper_collections", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned paper-collection associations")

        if report["orphaned_records"]["summary"].get("orphaned_paper_authors", 0) > 0:
            recommendations.append("Clean up orphaned paper-author associations")

        if (
            report.get("orphaned_pdfs", {})
            .get("summary", {})
            .get("orphaned_pdf_files", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned PDF files")

        if (
            report.get("absolute_pdf_paths", {})
            .get("summary", {})
            .get("absolute_path_count", 0)
            > 0
        ):
            recommendations.append("Fix absolute PDF paths to be relative paths")

        if (
            report.get("missing_pdfs", {})
            .get("summary", {})
            .get("missing_pdf_count", 0)
            > 0
        ):
            recommendations.append("Review papers with missing PDF files")

        # System recommendations
        missing_deps = [
            dep
            for dep, status in report["system_checks"]["dependencies"].items()
            if "Missing" in status
        ]
        if missing_deps:
            recommendations.append(
                f"Install missing dependencies: {', '.join(missing_deps)}"
            )

        # Terminal recommendations
        if not report["terminal_checks"]["unicode_support"]:
            recommendations.append("Configure terminal to support UTF-8/Unicode")

        if not report["terminal_checks"]["color_support"]:
            recommendations.append("Enable color support in terminal")

        return recommendations

    def _check_orphaned_pdfs(self) -> Dict[str, Any]:
        """Check for orphaned PDF files in the PDF directory."""
        orphaned = {"files": [], "summary": {}}

        try:
            with get_db_session() as session:
                db_manager = get_db_manager()
                pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")

                if not os.path.exists(pdf_dir):
                    return orphaned

                # Get PDF paths from database (these are relative paths)
                all_pdfs_in_db_relative = {
                    p.pdf_path
                    for p in session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None))
                    .all()
                    if p.pdf_path  # Filter out empty strings
                }

                # Convert relative paths to absolute for comparison
                all_pdfs_in_db_absolute = set()
                for rel_path in all_pdfs_in_db_relative:
                    if os.path.isabs(rel_path):
                        # Handle legacy absolute paths
                        all_pdfs_in_db_absolute.add(rel_path)
                    else:
                        # Convert relative to absolute
                        abs_path = os.path.join(pdf_dir, rel_path)
                        all_pdfs_in_db_absolute.add(abs_path)

                # Get all PDF files on disk (absolute paths)
                disk_pdfs = {
                    os.path.join(pdf_dir, f)
                    for f in os.listdir(pdf_dir)
                    if f.endswith(".pdf")
                }

                # Find orphaned files (on disk but not in database)
                orphaned_files = list(disk_pdfs - all_pdfs_in_db_absolute)

                orphaned["files"] = orphaned_files
                orphaned["summary"]["orphaned_pdf_files"] = len(orphaned_files)

                if orphaned_files:
                    self.issues_found.append(
                        f"Found {len(orphaned_files)} orphaned PDF files"
                    )
        except Exception as e:
            self.issues_found.append(f"Could not check for orphaned PDFs: {e}")

        return orphaned

    def _check_missing_pdfs(self) -> Dict[str, Any]:
        """Check for PDF files referenced in database but missing from disk."""
        missing = {"papers": [], "summary": {}}

        try:
            with get_db_session() as session:
                db_manager = get_db_manager()
                pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")

                # Get all papers with PDF paths
                papers_with_pdfs = (
                    session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None), Paper.pdf_path != "")
                    .all()
                )

                missing_pdfs = []
                for paper in papers_with_pdfs:
                    if paper.pdf_path:
                        # Handle both relative and absolute paths
                        if os.path.isabs(paper.pdf_path):
                            pdf_full_path = paper.pdf_path
                        else:
                            pdf_full_path = os.path.join(pdf_dir, paper.pdf_path)

                        if not os.path.exists(pdf_full_path):
                            missing_pdfs.append(
                                {
                                    "id": paper.id,
                                    "title": paper.title[:50]
                                    + ("..." if len(paper.title) > 50 else ""),
                                    "pdf_path": paper.pdf_path,
                                    "expected_location": pdf_full_path,
                                }
                            )

                missing["papers"] = missing_pdfs
                missing["summary"]["missing_pdf_count"] = len(missing_pdfs)

                if missing_pdfs:
                    self.issues_found.append(
                        f"Found {len(missing_pdfs)} papers with missing PDF files"
                    )

        except Exception as e:
            self.issues_found.append(f"Could not check for missing PDFs: {e}")

        return missing

    def _check_absolute_pdf_paths(self) -> Dict[str, Any]:
        """Check for papers with absolute PDF paths (should be relative)."""
        absolute_paths = {"papers": [], "summary": {}}

        try:
            with get_db_session() as session:
                papers_with_pdfs = (
                    session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None), Paper.pdf_path != "")
                    .all()
                )

                absolute_path_papers = []
                for paper in papers_with_pdfs:
                    if paper.pdf_path and os.path.isabs(paper.pdf_path):
                        absolute_path_papers.append(
                            {
                                "id": paper.id,
                                "title": paper.title[:50]
                                + ("..." if len(paper.title) > 50 else ""),
                                "pdf_path": paper.pdf_path,
                            }
                        )

                absolute_paths["papers"] = absolute_path_papers
                absolute_paths["summary"]["absolute_path_count"] = len(
                    absolute_path_papers
                )

                if absolute_path_papers:
                    self.issues_found.append(
                        f"Found {len(absolute_path_papers)} papers with absolute PDF paths (should be relative)"
                    )

        except Exception as e:
            self.issues_found.append(f"Could not check PDF path types: {e}")

        return absolute_paths

    def clean_orphaned_pdfs(self) -> Dict[str, int]:
        """Clean up orphaned PDF files."""
        cleaned = {"pdf_files": 0}
        cleaned_files = []

        try:
            report = self._check_orphaned_pdfs()
            orphaned_files = report.get("files", [])

            for f in orphaned_files:
                try:
                    filename = os.path.basename(f)
                    os.remove(f)
                    cleaned["pdf_files"] += 1
                    cleaned_files.append(filename)

                    # Log individual file deletion if log callback is available
                    if hasattr(self, "log_callback") and self.log_callback:
                        self.log_callback(
                            "database_cleanup", f"Deleted orphaned PDF: {filename}"
                        )
                except Exception:
                    pass  # ignore errors on individual file deletions

            if cleaned["pdf_files"] > 0:
                self.fixes_applied.append(
                    f"Cleaned {cleaned['pdf_files']} orphaned PDF files: {', '.join(cleaned_files)}"
                )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned PDFs: {e}")

        return cleaned

    def clean_orphaned_records(self) -> Dict[str, int]:
        """Clean up orphaned records in the database."""
        cleaned = {"paper_collections": 0, "paper_authors": 0}

        try:
            with get_db_session() as session:
                # Clean orphaned paper_collections
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_collections 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR collection_id NOT IN (SELECT id FROM collections)
                """
                    )
                )
                cleaned["paper_collections"] = result.rowcount

                # Clean orphaned paper_authors
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_authors 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR author_id NOT IN (SELECT id FROM authors)
                """
                    )
                )
                cleaned["paper_authors"] = result.rowcount

                session.commit()

                if cleaned["paper_collections"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_collections']} orphaned paper-collection associations"
                    )
                if cleaned["paper_authors"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_authors']} orphaned paper-author associations"
                    )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned records: {e}")

        return cleaned

    def fix_absolute_pdf_paths(self) -> Dict[str, int]:
        """Fix absolute PDF paths to be relative paths."""
        fixed = {"pdf_paths": 0}
        fixed_papers = []

        try:
            with get_db_session() as session:
                # Get the PDF directory path for relative conversion
                db_manager = get_db_manager()
                pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")

                # Find papers with absolute paths
                papers_with_absolute_paths = (
                    session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None), Paper.pdf_path != "")
                    .all()
                )

                for paper in papers_with_absolute_paths:
                    if paper.pdf_path and os.path.isabs(paper.pdf_path):
                        # Convert to relative path
                        try:
                            relative_path = os.path.relpath(paper.pdf_path, pdf_dir)
                            # Only update if the relative path makes sense (no '..' at start)
                            if not relative_path.startswith(".."):
                                paper.pdf_path = relative_path
                                fixed["pdf_paths"] += 1
                                fixed_papers.append(
                                    paper.title[:30]
                                    + ("..." if len(paper.title) > 30 else "")
                                )

                                # Log individual fix if log callback is available
                                if hasattr(self, "log_callback") and self.log_callback:
                                    self.log_callback(
                                        "database_cleanup",
                                        f"Fixed absolute PDF path for: {paper.title[:50]}",
                                    )
                        except Exception:
                            # Skip papers we can't fix
                            continue

                session.commit()

                if fixed["pdf_paths"] > 0:
                    self.fixes_applied.append(
                        f"Fixed {fixed['pdf_paths']} absolute PDF paths: {', '.join(fixed_papers[:5])}"
                        + (
                            f" and {len(fixed_papers) - 5} more"
                            if len(fixed_papers) > 5
                            else ""
                        )
                    )

        except Exception as e:
            raise Exception(f"Failed to fix absolute PDF paths: {e}")

        return fixed

    def clean_pdf_filenames(self) -> Dict[str, int]:
        """Rename all PDF files according to the established naming convention."""
        from .pdf import PDFManager

        cleaned = {"renamed_files": 0}
        renamed_files = []

        try:
            with get_db_session() as session:
                pdf_manager = PDFManager()

                # Get all papers with PDF paths
                papers_with_pdfs = (
                    session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None), Paper.pdf_path != "")
                    .all()
                )

                for paper in papers_with_pdfs:
                    if not paper.pdf_path:
                        continue

                    # Get current absolute PDF path
                    current_path = pdf_manager.get_absolute_path(paper.pdf_path)

                    # Skip if file doesn't exist
                    if not os.path.exists(current_path):
                        continue

                    # Create paper data dict for filename generation
                    paper_data = {
                        "title": paper.title,
                        "year": paper.year or "nodate",
                        "authors": (
                            [paper.author_names]
                            if hasattr(paper, "author_names") and paper.author_names
                            else ["unknown"]
                        ),
                    }

                    # If paper has proper authors relationship, use those
                    if paper.paper_authors:
                        author_names = []
                        for paper_author in sorted(
                            paper.paper_authors, key=lambda pa: pa.position
                        ):
                            if paper_author.author:
                                author_names.append(paper_author.author.full_name)
                        if author_names:
                            paper_data["authors"] = author_names

                    # Generate the proper filename
                    proper_filename = pdf_manager._generate_pdf_filename(
                        paper_data, current_path
                    )
                    proper_path = os.path.join(pdf_manager.pdf_dir, proper_filename)

                    # Skip if already properly named
                    current_filename = os.path.basename(current_path)
                    if current_filename == proper_filename:
                        continue

                    # Handle filename conflicts
                    counter = 1
                    base_name = proper_filename[:-4]  # Remove .pdf extension
                    final_filename = proper_filename
                    final_path = proper_path

                    while os.path.exists(final_path) and final_path != current_path:
                        final_filename = f"{base_name}_{counter:02d}.pdf"
                        final_path = os.path.join(pdf_manager.pdf_dir, final_filename)
                        counter += 1

                    # Rename the file
                    try:
                        os.rename(current_path, final_path)

                        # Update database with new relative path
                        new_relative_path = os.path.relpath(
                            final_path, pdf_manager.pdf_dir
                        )
                        old_path = paper.pdf_path
                        paper.pdf_path = new_relative_path

                        # Flush to ensure database update
                        session.flush()

                        cleaned["renamed_files"] += 1
                        renamed_files.append(f"{current_filename} → {final_filename}")

                        # Log individual rename if log callback is available
                        if hasattr(self, "log_callback") and self.log_callback:
                            self.log_callback(
                                "pdf_filename_cleanup",
                                f"Renamed PDF: {current_filename} → {final_filename} (DB: {old_path} → {new_relative_path})",
                            )

                    except Exception as e:
                        # Log error but continue with other files
                        if hasattr(self, "log_callback") and self.log_callback:
                            self.log_callback(
                                "pdf_filename_error",
                                f"Failed to rename {current_filename}: {str(e)}",
                            )
                        continue

                # Commit all database changes at once
                session.commit()

                if cleaned["renamed_files"] > 0:
                    self.fixes_applied.append(
                        f"Renamed {cleaned['renamed_files']} PDF files to follow naming convention"
                    )

        except Exception as e:
            raise Exception(f"Failed to clean PDF filenames: {e}")

        return cleaned
