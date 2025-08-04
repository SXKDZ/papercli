"""Sync service for managing local and remote database synchronization."""

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict
from typing import List


class SyncConflict:
    """Represents a sync conflict between local and remote data."""

    def __init__(
        self, conflict_type: str, item_id: str, local_data: Dict, remote_data: Dict
    ):
        self.conflict_type = conflict_type  # 'paper', 'collection', 'pdf'
        self.item_id = item_id
        self.local_data = local_data
        self.remote_data = remote_data
        self.differences = self._calculate_differences()

    def _calculate_differences(self) -> Dict[str, Dict]:
        """Calculate specific differences between local and remote data."""
        differences = {}

        all_keys = set(self.local_data.keys()) | set(self.remote_data.keys())
        for key in all_keys:
            local_val = self.local_data.get(key)
            remote_val = self.remote_data.get(key)

            if local_val != remote_val:
                differences[key] = {"local": local_val, "remote": remote_val}

        return differences


class SyncResult:
    """Represents the result of a sync operation."""

    def __init__(self):
        self.conflicts: List[SyncConflict] = []
        self.changes_applied: Dict[str, int] = {
            "papers_added": 0,
            "papers_updated": 0,
            "collections_added": 0,
            "collections_updated": 0,
            "pdfs_copied": 0,
            "pdfs_updated": 0,
        }
        self.detailed_changes: Dict[str, List[str]] = {
            "papers_added": [],
            "papers_updated": [],
            "collections_added": [],
            "collections_updated": [],
        }
        self.errors: List[str] = []
        self.cancelled = False

    def has_conflicts(self) -> bool:
        """Check if there are any conflicts."""
        return len(self.conflicts) > 0

    def get_summary(self) -> str:
        """Get a human-readable summary of sync results."""
        if self.cancelled:
            return "Sync operation was cancelled by user"

        if self.has_conflicts():
            return f"Sync completed with {len(self.conflicts)} conflicts that need resolution"

        total_changes = sum(self.changes_applied.values())
        if total_changes == 0:
            return "No changes to sync - local and remote are already in sync"

        summary_parts = []
        if self.changes_applied["papers_added"] > 0:
            summary_parts.append(f"{self.changes_applied['papers_added']} papers added")
        if self.changes_applied["papers_updated"] > 0:
            summary_parts.append(
                f"{self.changes_applied['papers_updated']} papers updated"
            )
        if self.changes_applied["collections_added"] > 0:
            summary_parts.append(
                f"{self.changes_applied['collections_added']} collections added"
            )
        if self.changes_applied["collections_updated"] > 0:
            summary_parts.append(
                f"{self.changes_applied['collections_updated']} collections updated"
            )
        if self.changes_applied["pdfs_copied"] > 0:
            summary_parts.append(f"{self.changes_applied['pdfs_copied']} PDFs copied")

        return f"Sync completed: {', '.join(summary_parts)}"


class SyncService:
    """Service for managing synchronization between local and remote databases."""

    def __init__(
        self,
        local_data_dir: str,
        remote_data_dir: str,
        progress_callback=None,
        log_callback=None,
    ):
        self.local_data_dir = Path(local_data_dir)
        self.remote_data_dir = Path(remote_data_dir)
        self.local_db_path = self.local_data_dir / "papers.db"
        self.remote_db_path = self.remote_data_dir / "papers.db"
        self.local_pdf_dir = self.local_data_dir / "pdfs"
        self.remote_pdf_dir = self.remote_data_dir / "pdfs"
        self.progress_callback = progress_callback
        self.log_callback = log_callback

        # Lock file paths
        self.local_lock_file = self.local_data_dir / ".papercli_sync.lock"
        self.remote_lock_file = self.remote_data_dir / ".papercli_sync.lock"

    def _acquire_locks(self) -> bool:
        """Acquire sync locks on both local and remote directories."""
        try:
            # Check if any locks already exist
            if self._check_existing_locks():
                return False

            # Create lock files with process info
            lock_info = {
                "process_id": os.getpid(),
                "timestamp": datetime.now().isoformat(),
                "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
            }

            # Create local lock
            self.local_data_dir.mkdir(exist_ok=True)
            with open(self.local_lock_file, "w") as f:
                json.dump(lock_info, f)

            # Create remote lock
            self.remote_data_dir.mkdir(exist_ok=True)
            with open(self.remote_lock_file, "w") as f:
                json.dump(lock_info, f)

            return True

        except Exception as e:
            # Clean up any partial locks
            self._release_locks()
            raise Exception(f"Failed to acquire sync locks: {str(e)}")

    def _check_existing_locks(self) -> bool:
        """Check if any sync locks exist and if they're still valid."""
        for lock_file in [self.local_lock_file, self.remote_lock_file]:
            if lock_file.exists():
                try:
                    with open(lock_file, "r") as f:
                        lock_info = json.load(f)

                    # Check if lock is stale (older than 30 minutes)
                    lock_time = datetime.fromisoformat(lock_info.get("timestamp", ""))
                    time_diff = datetime.now() - lock_time

                    if time_diff.total_seconds() > 1800:  # 30 minutes
                        # Stale lock, remove it
                        lock_file.unlink()
                        continue

                    # Check if process is still running (basic check)
                    process_id = lock_info.get("process_id")
                    if process_id and self._is_process_running(process_id):
                        return True  # Active lock found
                    else:
                        # Process not running, remove stale lock
                        lock_file.unlink()

                except (json.JSONDecodeError, ValueError, KeyError):
                    # Invalid lock file, remove it
                    lock_file.unlink()

        return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            # Send signal 0 to check if process exists
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _release_locks(self):
        """Release sync locks."""
        for lock_file in [self.local_lock_file, self.remote_lock_file]:
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except Exception:
                    pass  # Ignore errors when cleaning up

    def sync(self, conflict_resolver=None, auto_sync_mode=False) -> SyncResult:
        """Perform a complete sync operation."""
        result = SyncResult()

        # Acquire locks before starting sync
        if not self._acquire_locks():
            raise Exception(
                "Another sync operation is already in progress. Please wait for it to complete."
            )

        try:
            # Progress tracking - define all steps
            total_steps = 7
            current_step = 0

            def update_progress(message: str):
                nonlocal current_step
                current_step += 1
                if self.progress_callback:
                    percentage = int((current_step / total_steps) * 100)
                    self.progress_callback(message)
                # Add debug delay to see progress
                import time

                time.sleep(2)

            update_progress("Creating remote directory...")
            # Ensure remote directory exists
            self.remote_data_dir.mkdir(parents=True, exist_ok=True)
            self.remote_pdf_dir.mkdir(parents=True, exist_ok=True)

            update_progress("Checking remote database...")
            # If remote database doesn't exist, create it from local
            if not self.remote_db_path.exists():
                update_progress("Creating initial remote database...")
                shutil.copy2(self.local_db_path, self.remote_db_path)
                papers_count = self._count_papers(self.local_db_path)
                collections_count = self._count_collections(self.local_db_path)
                result.changes_applied["papers_added"] = papers_count
                result.changes_applied["collections_added"] = collections_count
                self.log_callback(
                    "sync_initial",
                    f"Created initial remote database with {papers_count} papers and {collections_count} collections",
                )

                update_progress("Copying PDFs to remote...")
                self._sync_pdfs_to_remote(result)
                update_progress("Initial sync completed")
                return result

            update_progress("Detecting conflicts...")
            # Detect conflicts
            conflicts = self._detect_conflicts()

            if conflicts:
                result.conflicts = conflicts
                self.log_callback(
                    "sync_conflicts",
                    f"Detected {len(conflicts)} conflicts: {[c.conflict_type for c in conflicts]}",
                )
                update_progress(f"Found {len(conflicts)} conflicts...")

                # If conflict resolver is provided, try to resolve conflicts
                if conflict_resolver:
                    update_progress("Showing conflict resolution dialog...")
                    resolved_conflicts = conflict_resolver(conflicts)
                    if resolved_conflicts is None:  # User cancelled
                        result.cancelled = True
                        self.log_callback(
                            "sync_cancelled",
                            "Sync cancelled by user during conflict resolution",
                        )
                        return result

                    update_progress("Applying conflict resolutions...")
                    resolution_summary = [
                        f"{res}" for res in resolved_conflicts.values()
                    ]
                    self.log_callback(
                        "sync_resolutions",
                        f"Applied {len(resolved_conflicts)} conflict resolutions: {resolution_summary}",
                    )
                    # Apply resolved conflicts
                    self._apply_conflict_resolutions(resolved_conflicts, result)
                else:
                    # No resolver provided, just return conflicts
                    self.log_callback(
                        "sync_conflicts_unresolved",
                        f"Found {len(conflicts)} unresolved conflicts",
                    )
                    return result
            else:
                update_progress("No conflicts detected...")

            # Get counts for progress tracking
            local_paper_count = self._count_papers(self.local_db_path)
            remote_paper_count = self._count_papers(self.remote_db_path)
            local_collection_count = self._count_collections(self.local_db_path)
            remote_collection_count = self._count_collections(self.remote_db_path)
            local_pdf_count = self._count_pdfs(self.local_pdf_dir)
            remote_pdf_count = self._count_pdfs(self.remote_pdf_dir)

            # Pass counts to progress callback directly
            if self.progress_callback:
                self.progress_callback(
                    f"Synchronizing papers...",
                    {
                        "papers_total": max(local_paper_count, remote_paper_count),
                        "papers_processed": 0,
                        "collections_total": max(
                            local_collection_count, remote_collection_count
                        ),
                        "collections_processed": 0,
                    },
                )
            # Perform sync operations
            self._sync_papers(result, auto_sync_mode)

            if self.progress_callback:
                self.progress_callback(
                    f"Synchronizing collections...",
                    {
                        "papers_total": max(local_paper_count, remote_paper_count),
                        "papers_processed": max(local_paper_count, remote_paper_count),
                        "collections_total": max(
                            local_collection_count, remote_collection_count
                        ),
                        "collections_processed": 0,
                    },
                )
            self._sync_collections(result, auto_sync_mode)

            if self.progress_callback:
                self.progress_callback(
                    f"Synchronizing PDF files...",
                    {
                        "papers_total": max(local_paper_count, remote_paper_count),
                        "papers_processed": max(local_paper_count, remote_paper_count),
                        "collections_total": max(
                            local_collection_count, remote_collection_count
                        ),
                        "collections_processed": max(
                            local_collection_count, remote_collection_count
                        ),
                        "pdfs_total": max(local_pdf_count, remote_pdf_count),
                        "pdfs_processed": 0,
                    },
                )
            self._sync_pdfs_bidirectional(result)

            update_progress("Sync completed successfully")
            self.log_callback(
                "sync_complete", f"Sync completed successfully: {result.get_summary()}"
            )

        except Exception as e:
            result.errors.append(f"Sync failed: {str(e)}")
            if self.progress_callback:
                self.progress_callback(f"Sync failed: {str(e)}")

        finally:
            # Always release locks
            self._release_locks()

        return result

    def _detect_conflicts(self) -> List[SyncConflict]:
        """Detect conflicts between local and remote databases."""
        conflicts = []

        # Get papers from both databases
        local_papers = self._get_papers_dict(self.local_db_path)
        remote_papers = self._get_papers_dict(self.remote_db_path)

        # Create content-based matching between papers
        local_to_remote_matches = self._find_paper_matches(local_papers, remote_papers)
        remote_to_local_matches = self._find_paper_matches(remote_papers, local_papers)

        # Check for paper conflicts (same content, different data/authors)
        for local_id, remote_id in local_to_remote_matches.items():
            local_paper = local_papers[local_id]
            remote_paper = remote_papers[remote_id]

            # Compare relevant fields
            if self._papers_differ(local_paper, remote_paper):
                # Use the paper title as the conflict identifier since IDs differ
                conflict_id = local_paper.get(
                    "title", f"local_{local_id}_remote_{remote_id}"
                )
                conflict = SyncConflict("paper", conflict_id, local_paper, remote_paper)
                conflicts.append(conflict)

        # Check for PDF conflicts
        pdf_conflicts = self._detect_pdf_conflicts()
        conflicts.extend(pdf_conflicts)

        return conflicts

    def _find_paper_matches(
        self, papers1: Dict[int, Dict], papers2: Dict[int, Dict]
    ) -> Dict[int, int]:
        """Find matching papers between two sets based on content similarity."""
        matches = {}

        for id1, paper1 in papers1.items():
            best_match_id = None
            best_match_score = 0

            for id2, paper2 in papers2.items():
                score = self._calculate_paper_similarity(paper1, paper2)
                if (
                    score > 0.8 and score > best_match_score
                ):  # High similarity threshold
                    best_match_score = score
                    best_match_id = id2

            if best_match_id is not None:
                matches[id1] = best_match_id

        return matches

    def _calculate_paper_similarity(self, paper1: Dict, paper2: Dict) -> float:
        """
        Calculate similarity score between two papers (0.0 to 1.0).
        Papers are considered similar (conflicting) only when most significant features match:
        - Title almost matches
        - DOI exactly matches
        - arXiv ID exactly matches
        - Website/URL exactly matches
        - PDF is almost similar
        """
        similarity_score = 0.0

        # Check exact matches for key identifiers (highest confidence)
        exact_matches = 0

        # DOI exact match
        if (
            paper1.get("doi")
            and paper2.get("doi")
            and paper1.get("doi") == paper2.get("doi")
        ):
            exact_matches += 1
            similarity_score = max(similarity_score, 1.0)

        # arXiv ID exact match
        if (
            paper1.get("preprint_id")
            and paper2.get("preprint_id")
            and paper1.get("preprint_id") == paper2.get("preprint_id")
        ):
            exact_matches += 1
            similarity_score = max(similarity_score, 1.0)

        # Website/URL exact match
        if (
            paper1.get("url")
            and paper2.get("url")
            and paper1.get("url") == paper2.get("url")
        ):
            exact_matches += 1
            similarity_score = max(similarity_score, 1.0)

        # If we have exact matches, these are definitely the same paper
        if exact_matches > 0:
            return 1.0

        # Check title similarity (required for any match)
        title1 = paper1.get("title", "").lower().strip()
        title2 = paper2.get("title", "").lower().strip()

        if not title1 or not title2:
            return 0.0

        # Title matching - must be "almost" matching
        title_score = 0.0
        if title1 == title2:
            title_score = 1.0
        elif title1 in title2 or title2 in title1:
            title_score = 0.85  # Very similar
        else:
            # Check for substantial word overlap
            words1 = set(title1.split())
            words2 = set(title2.split())
            if len(words1) > 0 and len(words2) > 0:
                overlap = len(words1 & words2) / max(len(words1), len(words2))
                title_score = (
                    overlap if overlap > 0.7 else 0.0
                )  # Higher threshold for "almost match"
            else:
                title_score = 0.0

        # Title must be "almost matching" (>0.7) to proceed
        if title_score < 0.7:
            return 0.0

        # Check PDF similarity if both papers have PDFs
        pdf_score = 0.0
        local_pdf = paper1.get("pdf_path")
        remote_pdf = paper2.get("pdf_path")
        if local_pdf and remote_pdf:
            local_pdf_full = self.local_pdf_dir / local_pdf
            remote_pdf_full = self.remote_pdf_dir / remote_pdf
            if local_pdf_full.exists() and remote_pdf_full.exists():
                local_info = self._get_file_info(local_pdf_full)
                remote_info = self._get_file_info(remote_pdf_full)

                # PDFs are "almost similar" if they have similar sizes or same hash
                if local_info.get("hash") == remote_info.get("hash"):
                    pdf_score = 1.0  # Identical PDFs
                else:
                    # Check size similarity (within 20% difference indicates likely same content)
                    local_size = local_info.get("size", 0)
                    remote_size = remote_info.get("size", 0)
                    if local_size > 0 and remote_size > 0:
                        size_ratio = min(local_size, remote_size) / max(
                            local_size, remote_size
                        )
                        if size_ratio > 0.8:  # Within 20% size difference
                            pdf_score = 0.8  # Almost similar PDFs

        # Combine scores: high title similarity + optional PDF similarity
        final_score = title_score
        if pdf_score > 0:
            final_score = max(final_score, (title_score + pdf_score) / 2)

        return final_score

    def _papers_differ(self, local_paper: Dict, remote_paper: Dict) -> bool:
        """Check if two paper records differ in significant ways."""
        # Fields to compare (excluding timestamps which may differ naturally)
        # Based on actual Paper model fields from models.py
        compare_fields = [
            "title",
            "abstract",
            "venue_full",
            "venue_acronym",
            "year",
            "volume",
            "issue",
            "pages",
            "paper_type",
            "doi",
            "preprint_id",
            "category",
            "url",
            "notes",
        ]

        for field in compare_fields:
            local_val = local_paper.get(field)
            remote_val = remote_paper.get(field)

            # Handle empty string vs None as equivalent
            if not local_val and not remote_val:
                continue

            if local_val != remote_val:
                return True

        # Check if authors differ (from the JOIN query that includes authors)
        local_authors = local_paper.get("authors", "")
        remote_authors = remote_paper.get("authors", "")
        if local_authors != remote_authors:
            return True

        # Check if PDF files exist and have different hashes
        local_pdf = local_paper.get("pdf_path")
        remote_pdf = remote_paper.get("pdf_path")
        if local_pdf and remote_pdf:
            local_pdf_full = self.local_pdf_dir / local_pdf
            remote_pdf_full = self.remote_pdf_dir / remote_pdf
            if local_pdf_full.exists() and remote_pdf_full.exists():
                local_info = self._get_file_info(local_pdf_full)
                remote_info = self._get_file_info(remote_pdf_full)
                if local_info.get("hash") != remote_info.get("hash"):
                    return True

        return False

    def _detect_pdf_conflicts(self) -> List[SyncConflict]:
        """Detect PDF file conflicts."""
        conflicts = []

        if not (self.local_pdf_dir.exists() and self.remote_pdf_dir.exists()):
            return conflicts

        local_pdfs = {
            f.name: self._get_file_info(f) for f in self.local_pdf_dir.glob("*.pdf")
        }
        remote_pdfs = {
            filename: self._get_file_info(self.remote_pdf_dir / filename)
            for filename in local_pdfs.keys()
            if (self.remote_pdf_dir / filename).exists()
        }

        for filename in set(local_pdfs.keys()) & set(remote_pdfs.keys()):
            local_info = local_pdfs[filename]
            remote_info = remote_pdfs[filename]

            # Compare file hash and size
            if (
                local_info["hash"] != remote_info["hash"]
                or local_info["size"] != remote_info["size"]
            ):

                conflict = SyncConflict("pdf", filename, local_info, remote_info)
                conflicts.append(conflict)

        return conflicts

    def _get_file_info(self, file_path: Path) -> Dict:
        """Get file information including hash, size, and modification time."""
        if not file_path.exists():
            return {}

        stat = file_path.stat()

        # Calculate MD5 hash
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        return {
            "hash": file_hash,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "path": str(file_path),
        }

    def _get_papers_dict(self, db_path: Path) -> Dict[int, Dict]:
        """Get papers from database as a dictionary."""
        papers = {}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT p.*, GROUP_CONCAT(a.full_name ORDER BY pa.position) as authors
                FROM papers p
                LEFT JOIN paper_authors pa ON p.id = pa.paper_id
                LEFT JOIN authors a ON pa.author_id = a.id
                GROUP BY p.id
                ORDER BY p.id
            """
            )

            for row in cursor.fetchall():
                papers[row["id"]] = dict(row)

        finally:
            conn.close()

        return papers

    def _count_papers(self, db_path: Path) -> int:
        """Count papers in database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM papers")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _count_collections(self, db_path: Path) -> int:
        """Count collections in database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM collections")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _count_pdfs(self, pdf_dir: Path) -> int:
        """Count PDF files in directory."""
        if not pdf_dir.exists():
            return 0
        return len([f for f in pdf_dir.glob("*.pdf")])

    def _sync_papers(self, result: SyncResult, auto_sync_mode: bool = False):
        """Sync papers between local and remote databases."""
        local_papers = self._get_papers_dict(self.local_db_path)
        remote_papers = self._get_papers_dict(self.remote_db_path)

        # Find content-based matches between papers
        local_to_remote_matches = self._find_paper_matches(local_papers, remote_papers)
        remote_to_local_matches = self._find_paper_matches(remote_papers, local_papers)

        # Get sets of matched and unmatched papers
        matched_local_ids = set(local_to_remote_matches.keys())
        matched_remote_ids = set(local_to_remote_matches.values())

        # Papers only in local (need to add to remote) - excluding already matched ones
        local_only = set(local_papers.keys()) - matched_local_ids
        for paper_id in local_only:
            paper_data = local_papers[paper_id]
            self._copy_paper_to_remote(paper_data)
            result.changes_applied["papers_added"] += 1
            result.detailed_changes["papers_added"].append(
                f"'{paper_data.get('title', 'Unknown Title')}'"
            )
            self.log_callback(
                "paper_added_remote",
                f"Added paper '{paper_data.get('title', 'Unknown Title')}' to remote",
            )

        # Papers only in remote (need to add to local) - excluding already matched ones
        remote_only = set(remote_papers.keys()) - matched_remote_ids
        for paper_id in remote_only:
            paper_data = remote_papers[paper_id]
            self._copy_paper_to_local(paper_data)
            result.changes_applied["papers_added"] += 1
            result.detailed_changes["papers_added"].append(
                f"'{paper_data.get('title', 'Unknown Title')}' (from remote)"
            )
            self.log_callback(
                "paper_added_local",
                f"Added paper '{paper_data.get('title', 'Unknown Title')}' to local (from remote)",
            )

        # For matched papers, ensure they're properly synchronized (merge any differences)
        for local_id, remote_id in local_to_remote_matches.items():
            local_paper = local_papers[local_id]
            remote_paper = remote_papers[remote_id]
            self._merge_matched_papers(local_paper, remote_paper, result)

        # Handle deletions only in auto-sync mode
        if auto_sync_mode:
            # In auto-sync mode, we can handle deletions by removing papers that exist in
            # one database but not the other (after accounting for matches)
            # This is conservative - we only delete if we're confident it was intentionally removed
            self.log_callback(
                "auto_sync_deletions", "Auto-sync mode: handling potential deletions"
            )

            # For now, we'll be conservative and not auto-delete papers to prevent data loss
            # This could be enhanced in the future with timestamps or explicit deletion tracking

    def _merge_matched_papers(
        self, local_paper: Dict, remote_paper: Dict, result: SyncResult
    ):
        """Merge two matched papers, preserving the better data and author ordering."""
        # For now, just log that papers were recognized as duplicates
        # In the future, this could intelligently merge missing fields
        local_title = local_paper.get("title", "Unknown")

        # If there are differences that weren't resolved in conflict resolution,
        # we could apply intelligent merging here (e.g., take non-empty fields)

    def _sync_collections(self, result: SyncResult, auto_sync_mode: bool = False):
        """Sync collections between local and remote databases."""
        local_collections = self._get_collections_dict(self.local_db_path)
        remote_collections = self._get_collections_dict(self.remote_db_path)

        # Collections only in local (need to add to remote)
        local_only = set(local_collections.keys()) - set(remote_collections.keys())
        for collection_id in local_only:
            collection_data = local_collections[collection_id]
            new_remote_id = self._copy_collection_to_remote(collection_data)
            # Copy paper relationships for this collection
            if new_remote_id:
                self._copy_collection_papers_to_remote(collection_id, new_remote_id)
            result.changes_applied["collections_added"] += 1
            result.detailed_changes["collections_added"].append(
                f"'{collection_data.get('name', 'Unknown Collection')}'"
            )
            self.log_callback(
                "collection_added_remote",
                f"Added collection '{collection_data.get('name', 'Unknown Collection')}' to remote",
            )

        # Collections only in remote (need to add to local)
        remote_only = set(remote_collections.keys()) - set(local_collections.keys())
        for collection_id in remote_only:
            collection_data = remote_collections[collection_id]
            new_local_id = self._copy_collection_to_local(collection_data)
            # Copy paper relationships for this collection
            if new_local_id:
                self._copy_collection_papers_to_local(collection_id, new_local_id)
            result.changes_applied["collections_added"] += 1
            result.detailed_changes["collections_added"].append(
                f"'{collection_data.get('name', 'Unknown Collection')}' (from remote)"
            )
            self.log_callback(
                "collection_added_local",
                f"Added collection '{collection_data.get('name', 'Unknown Collection')}' to local (from remote)",
            )

        # For existing collections, sync their paper relationships
        common_collections = set(local_collections.keys()) & set(
            remote_collections.keys()
        )
        for collection_id in common_collections:
            self._sync_collection_papers(collection_id, result)

    def _sync_pdfs_to_remote(self, result: SyncResult):
        """Copy PDFs from local to remote."""
        if not self.local_pdf_dir.exists():
            return

        for pdf_file in self.local_pdf_dir.glob("*.pdf"):
            remote_pdf = self.remote_pdf_dir / pdf_file.name
            if not remote_pdf.exists():
                shutil.copy2(pdf_file, remote_pdf)
                result.changes_applied["pdfs_copied"] += 1
                self.log_callback(
                    "pdf_copied_remote", f"Copied PDF '{pdf_file.name}' to remote."
                )

    def _sync_pdfs_bidirectional(self, result: SyncResult):
        """Sync PDFs in both directions, avoiding duplicates with different names."""
        # Copy missing PDFs from local to remote
        if self.local_pdf_dir.exists():
            local_pdf_hashes = {}
            remote_pdf_hashes = {}

            # Build hash maps to detect identical files with different names
            for pdf_file in self.local_pdf_dir.glob("*.pdf"):
                file_info = self._get_file_info(pdf_file)
                local_pdf_hashes[file_info["hash"]] = pdf_file

            if self.remote_pdf_dir.exists():
                for pdf_file in self.remote_pdf_dir.glob("*.pdf"):
                    file_info = self._get_file_info(pdf_file)
                    remote_pdf_hashes[file_info["hash"]] = pdf_file

            # Copy local PDFs to remote only if they don't already exist (by content)
            for pdf_file in self.local_pdf_dir.glob("*.pdf"):
                remote_pdf = self.remote_pdf_dir / pdf_file.name
                if not remote_pdf.exists():
                    # Check if identical content already exists remotely
                    file_info = self._get_file_info(pdf_file)
                    if file_info["hash"] not in remote_pdf_hashes:
                        shutil.copy2(pdf_file, remote_pdf)
                        result.changes_applied["pdfs_copied"] += 1
                        self.log_callback(
                            "pdf_copied_remote",
                            f"Copied PDF '{pdf_file.name}' to remote",
                        )

        # Copy missing PDFs from remote to local
        if self.remote_pdf_dir.exists():
            self.local_pdf_dir.mkdir(exist_ok=True)

            # Build local hash map if not already built
            if "local_pdf_hashes" not in locals():
                local_pdf_hashes = {}
                for pdf_file in self.local_pdf_dir.glob("*.pdf"):
                    file_info = self._get_file_info(pdf_file)
                    local_pdf_hashes[file_info["hash"]] = pdf_file

            for pdf_file in self.remote_pdf_dir.glob("*.pdf"):
                local_pdf = self.local_pdf_dir / pdf_file.name
                if not local_pdf.exists():
                    # Check if identical content already exists locally
                    file_info = self._get_file_info(pdf_file)
                    if file_info["hash"] not in local_pdf_hashes:
                        shutil.copy2(pdf_file, local_pdf)
                        result.changes_applied["pdfs_copied"] += 1
                        self.log_callback(
                            "pdf_copied_local",
                            f"Copied PDF '{pdf_file.name}' to local (from remote)",
                        )

    def _get_collections_dict(self, db_path: Path) -> Dict[int, Dict]:
        """Get collections from database as a dictionary."""
        collections = {}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM collections")
            for row in cursor.fetchall():
                collections[row["id"]] = dict(row)
        finally:
            conn.close()

        return collections

    def _copy_paper_to_remote(self, paper_data: Dict):
        """Copy a paper from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()

        try:
            # Prepare paper data with required datetime fields
            paper_dict = dict(paper_data)
            if "added_date" not in paper_dict or not paper_dict["added_date"]:
                paper_dict["added_date"] = datetime.now().isoformat()
            if "modified_date" not in paper_dict or not paper_dict["modified_date"]:
                paper_dict["modified_date"] = datetime.now().isoformat()

            # Ensure PDF path is relative, not absolute
            if paper_dict.get("pdf_path") and os.path.isabs(paper_dict["pdf_path"]):
                # Convert absolute path to relative path
                pdf_dir = self.remote_data_dir / "pdfs"
                try:
                    paper_dict["pdf_path"] = os.path.relpath(
                        paper_dict["pdf_path"], pdf_dir
                    )
                except ValueError:
                    # If paths are on different drives, keep as-is for now
                    pass

            # Insert paper (excluding id and authors, filtering None values)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if field not in ["id", "authors"] and value is not None:
                    filtered_fields.append(field)
                    filtered_values.append(value)

            placeholders = ", ".join(["?"] * len(filtered_fields))
            field_names = ", ".join(filtered_fields)

            cursor.execute(
                f"INSERT INTO papers ({field_names}) VALUES ({placeholders})",
                filtered_values,
            )
            new_paper_id = cursor.lastrowid

            # Handle authors if present
            if "authors" in paper_data and paper_data["authors"]:
                author_names = (
                    paper_data["authors"].split(",") if paper_data["authors"] else []
                )
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        # Insert or get author
                        cursor.execute(
                            "INSERT OR IGNORE INTO authors (full_name) VALUES (?)",
                            (author_name,),
                        )
                        cursor.execute(
                            "SELECT id FROM authors WHERE full_name = ?", (author_name,)
                        )
                        author_id = cursor.fetchone()[0]

                        # Link paper and author
                        cursor.execute(
                            "INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                            (new_paper_id, author_id, i),
                        )

            conn.commit()
        finally:
            conn.close()

    def _copy_paper_to_local(self, paper_data: Dict):
        """Copy a paper from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()

        try:
            # Prepare paper data with required datetime fields
            paper_dict = dict(paper_data)
            if "added_date" not in paper_dict or not paper_dict["added_date"]:
                paper_dict["added_date"] = datetime.now().isoformat()
            if "modified_date" not in paper_dict or not paper_dict["modified_date"]:
                paper_dict["modified_date"] = datetime.now().isoformat()

            # Ensure PDF path is relative, not absolute
            if paper_dict.get("pdf_path") and os.path.isabs(paper_dict["pdf_path"]):
                # Convert absolute path to relative path
                pdf_dir = self.local_data_dir / "pdfs"
                try:
                    paper_dict["pdf_path"] = os.path.relpath(
                        paper_dict["pdf_path"], pdf_dir
                    )
                except ValueError:
                    # If paths are on different drives, keep as-is for now
                    pass

            # Insert paper (excluding id and authors, filtering None values)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if field not in ["id", "authors"] and value is not None:
                    filtered_fields.append(field)
                    filtered_values.append(value)

            placeholders = ", ".join(["?"] * len(filtered_fields))
            field_names = ", ".join(filtered_fields)

            cursor.execute(
                f"INSERT INTO papers ({field_names}) VALUES ({placeholders})",
                filtered_values,
            )
            new_paper_id = cursor.lastrowid

            # Handle authors if present
            if "authors" in paper_data and paper_data["authors"]:
                author_names = (
                    paper_data["authors"].split(",") if paper_data["authors"] else []
                )
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        # Insert or get author
                        cursor.execute(
                            "INSERT OR IGNORE INTO authors (full_name) VALUES (?)",
                            (author_name,),
                        )
                        cursor.execute(
                            "SELECT id FROM authors WHERE full_name = ?", (author_name,)
                        )
                        author_id = cursor.fetchone()[0]

                        # Link paper and author
                        cursor.execute(
                            "INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                            (new_paper_id, author_id, i),
                        )

            conn.commit()
        finally:
            conn.close()

    def _copy_collection_to_remote(self, collection_data: Dict):
        """Copy a collection from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()

        try:
            # Include created_at field or use current timestamp
            created_at = collection_data.get("created_at") or datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?)",
                (
                    collection_data["name"],
                    collection_data.get("description", ""),
                    created_at,
                ),
            )
            new_collection_id = cursor.lastrowid
            conn.commit()
            return new_collection_id
        finally:
            conn.close()

    def _copy_collection_to_local(self, collection_data: Dict):
        """Copy a collection from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()

        try:
            # Include created_at field or use current timestamp
            created_at = collection_data.get("created_at") or datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?)",
                (
                    collection_data["name"],
                    collection_data.get("description", ""),
                    created_at,
                ),
            )
            new_collection_id = cursor.lastrowid
            conn.commit()
            return new_collection_id
        finally:
            conn.close()

    def _copy_collection_papers_to_remote(
        self, local_collection_id: int, remote_collection_id: int
    ):
        """Copy paper relationships for a collection from local to remote."""
        # Get papers in the local collection
        local_conn = sqlite3.connect(self.local_db_path)
        local_cursor = local_conn.cursor()

        remote_conn = sqlite3.connect(self.remote_db_path)
        remote_cursor = remote_conn.cursor()

        try:
            # Get paper IDs from local collection
            local_cursor.execute(
                "SELECT paper_id FROM paper_collections WHERE collection_id = ?",
                (local_collection_id,),
            )
            local_paper_ids = [row[0] for row in local_cursor.fetchall()]

            for local_paper_id in local_paper_ids:
                # Find corresponding remote paper by matching title (since IDs may differ)
                local_cursor.execute(
                    "SELECT title FROM papers WHERE id = ?", (local_paper_id,)
                )
                paper_title = local_cursor.fetchone()
                if not paper_title:
                    continue

                # Find remote paper with same title
                remote_cursor.execute(
                    "SELECT id FROM papers WHERE title = ?", (paper_title[0],)
                )
                remote_paper = remote_cursor.fetchone()
                if remote_paper:
                    remote_paper_id = remote_paper[0]
                    # Add relationship if it doesn't exist
                    remote_cursor.execute(
                        "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                        (remote_paper_id, remote_collection_id),
                    )

            remote_conn.commit()
        finally:
            local_conn.close()
            remote_conn.close()

    def _copy_collection_papers_to_local(
        self, remote_collection_id: int, local_collection_id: int
    ):
        """Copy paper relationships for a collection from remote to local."""
        # Get papers in the remote collection
        remote_conn = sqlite3.connect(self.remote_db_path)
        remote_cursor = remote_conn.cursor()

        local_conn = sqlite3.connect(self.local_db_path)
        local_cursor = local_conn.cursor()

        try:
            # Get paper IDs from remote collection
            remote_cursor.execute(
                "SELECT paper_id FROM paper_collections WHERE collection_id = ?",
                (remote_collection_id,),
            )
            remote_paper_ids = [row[0] for row in remote_cursor.fetchall()]

            for remote_paper_id in remote_paper_ids:
                # Find corresponding local paper by matching title (since IDs may differ)
                remote_cursor.execute(
                    "SELECT title FROM papers WHERE id = ?", (remote_paper_id,)
                )
                paper_title = remote_cursor.fetchone()
                if not paper_title:
                    continue

                # Find local paper with same title
                local_cursor.execute(
                    "SELECT id FROM papers WHERE title = ?", (paper_title[0],)
                )
                local_paper = local_cursor.fetchone()
                if local_paper:
                    local_paper_id = local_paper[0]
                    # Add relationship if it doesn't exist
                    local_cursor.execute(
                        "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                        (local_paper_id, local_collection_id),
                    )

            local_conn.commit()
        finally:
            remote_conn.close()
            local_conn.close()

    def _sync_collection_papers(self, collection_id: int, result: SyncResult):
        """Sync paper relationships for an existing collection between local and remote."""
        # Get papers in local and remote collections
        local_papers = self._get_collection_papers(self.local_db_path, collection_id)
        remote_papers = self._get_collection_papers(self.remote_db_path, collection_id)

        # Papers only in local collection (add to remote)
        local_only = local_papers - remote_papers
        if local_only:
            self._add_papers_to_remote_collection(local_only, collection_id)

        # Papers only in remote collection (add to local)
        remote_only = remote_papers - local_papers
        if remote_only:
            self._add_papers_to_local_collection(remote_only, collection_id)

    def _get_collection_papers(self, db_path: Path, collection_id: int) -> set:
        """Get set of paper titles in a collection."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT p.title 
                FROM papers p 
                JOIN paper_collections pc ON p.id = pc.paper_id 
                WHERE pc.collection_id = ?
            """,
                (collection_id,),
            )
            return set(row[0] for row in cursor.fetchall())
        finally:
            conn.close()

    def _add_papers_to_remote_collection(self, paper_titles: set, collection_id: int):
        """Add papers to remote collection by title."""
        remote_conn = sqlite3.connect(self.remote_db_path)
        remote_cursor = remote_conn.cursor()

        try:
            for title in paper_titles:
                # Find remote paper with this title
                remote_cursor.execute("SELECT id FROM papers WHERE title = ?", (title,))
                remote_paper = remote_cursor.fetchone()
                if remote_paper:
                    remote_paper_id = remote_paper[0]
                    # Add relationship if it doesn't exist
                    remote_cursor.execute(
                        "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                        (remote_paper_id, collection_id),
                    )
            remote_conn.commit()
        finally:
            remote_conn.close()

    def _add_papers_to_local_collection(self, paper_titles: set, collection_id: int):
        """Add papers to local collection by title."""
        local_conn = sqlite3.connect(self.local_db_path)
        local_cursor = local_conn.cursor()

        try:
            for title in paper_titles:
                # Find local paper with this title
                local_cursor.execute("SELECT id FROM papers WHERE title = ?", (title,))
                local_paper = local_cursor.fetchone()
                if local_paper:
                    local_paper_id = local_paper[0]
                    # Add relationship if it doesn't exist
                    local_cursor.execute(
                        "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                        (local_paper_id, collection_id),
                    )
            local_conn.commit()
        finally:
            local_conn.close()

    def _apply_conflict_resolutions(self, resolved_conflicts: Dict, result: SyncResult):
        """Apply user's conflict resolutions."""
        for conflict_id, resolution in resolved_conflicts.items():
            conflict = next(
                (
                    c
                    for c in result.conflicts
                    if f"{c.conflict_type}_{c.item_id}" == conflict_id
                ),
                None,
            )
            if not conflict:
                continue

            if resolution == "local":
                # Keep local version - no action needed as local takes precedence
                pass
            elif resolution == "remote":
                # Use remote version - copy remote data to local
                self._apply_remote_version(conflict, result)
            elif resolution == "keep_both":
                # Keep both versions - create duplicate with modified name/path
                self._keep_both_versions(conflict, result)

    def _apply_remote_version(self, conflict: SyncConflict, result: SyncResult):
        """Apply the remote version to resolve a conflict."""
        if conflict.conflict_type == "paper":
            # Update local paper with remote data
            self._update_local_paper_with_remote(conflict.remote_data, result)
        elif conflict.conflict_type == "pdf":
            # Replace local PDF with remote version
            local_path = Path(conflict.local_data["path"])
            remote_path = self.remote_pdf_dir / conflict.item_id
            if remote_path.exists():
                shutil.copy2(remote_path, local_path)
                result.changes_applied["pdfs_updated"] += 1
                self.log_callback(
                    "pdf_updated_local",
                    f"Updated local PDF '{conflict.item_id}' with remote version",
                )

    def _keep_both_versions(self, conflict: SyncConflict, result: SyncResult):
        """Keep both versions by creating a duplicate with modified identifier."""
        if conflict.conflict_type == "paper":
            # Create a duplicate of the remote paper with modified title
            remote_data = dict(conflict.remote_data)
            original_title = remote_data.get("title", "")
            remote_data["title"] = f"{original_title} (Remote Version)"
            self._copy_paper_to_local(remote_data)
            result.changes_applied["papers_added"] += 1
            result.detailed_changes["papers_added"].append(
                f"'{remote_data['title']}' (kept both versions)"
            )
            self.log_callback(
                "paper_added_kept_both",
                f"Added duplicate paper '{remote_data['title']}' (kept both versions)",
            )

        elif conflict.conflict_type == "pdf":
            # Create a copy of the remote PDF with modified filename
            base_name = Path(conflict.item_id).stem
            extension = Path(conflict.item_id).suffix
            new_filename = f"{base_name}_remote{extension}"

            remote_path = self.remote_pdf_dir / conflict.item_id
            local_new_path = self.local_pdf_dir / new_filename

            if remote_path.exists():
                shutil.copy2(remote_path, local_new_path)
                result.changes_applied["pdfs_copied"] += 1
                self.log_callback(
                    "pdf_added_kept_both",
                    f"Copied remote PDF '{conflict.item_id}' to local as '{new_filename}' (kept both versions)",
                )

    def _update_local_paper_with_remote(self, paper_data: Dict, result: SyncResult):
        """Update local paper with remote/merged data."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()

        try:
            # Find local paper by title (since IDs may differ)
            title = paper_data.get("title", "")
            cursor.execute("SELECT id FROM papers WHERE title = ?", (title,))
            local_paper = cursor.fetchone()

            if local_paper:
                local_paper_id = local_paper[0]

                # Update paper fields (excluding id and authors)
                update_fields = []
                update_values = []
                for field, value in paper_data.items():
                    if field not in ["id", "authors"] and value is not None:
                        update_fields.append(f"{field} = ?")
                        update_values.append(value)

                if update_fields:
                    update_values.append(local_paper_id)
                    cursor.execute(
                        f"UPDATE papers SET {', '.join(update_fields)} WHERE id = ?",
                        update_values,
                    )

                # Handle authors if present
                if "authors" in paper_data and paper_data["authors"]:
                    # Remove existing author relationships
                    cursor.execute(
                        "DELETE FROM paper_authors WHERE paper_id = ?",
                        (local_paper_id,),
                    )

                    # Add new author relationships
                    author_names = (
                        paper_data["authors"].split(",")
                        if paper_data["authors"]
                        else []
                    )
                    for i, author_name in enumerate(author_names):
                        author_name = author_name.strip()
                        if author_name:
                            cursor.execute(
                                "INSERT OR IGNORE INTO authors (full_name) VALUES (?)",
                                (author_name,),
                            )
                            cursor.execute(
                                "SELECT id FROM authors WHERE full_name = ?",
                                (author_name,),
                            )
                            author_id = cursor.fetchone()[0]
                            cursor.execute(
                                "INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                                (local_paper_id, author_id, i),
                            )

                conn.commit()
                result.changes_applied["papers_updated"] += 1
                result.detailed_changes["papers_updated"].append(
                    f"'{title}' (from remote)"
                )
                self.log_callback(
                    "paper_updated_local",
                    f"Updated local paper '{title}' with remote changes",
                )

        finally:
            conn.close()
