"""Simplified sync service for managing local and remote database synchronization."""

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ng
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from ng.db.database import ensure_schema_current
from ng.services import DatabaseHealthService
from pluralizer import Pluralizer
from sqlalchemy import create_engine

_pluralizer = Pluralizer()


class SyncOperation:
    """Represents a sync operation to be performed."""

    def __init__(
        self,
        operation_type: str,
        target: str,
        item_type: str,
        item_id: str,
        data: Dict = None,
    ):
        self.operation_type = operation_type  # 'add', 'edit', 'delete', 'conflict'
        self.target = target  # 'local', 'remote', 'both'
        self.item_type = item_type  # 'paper', 'collection', 'pdf'
        self.item_id = (
            item_id  # title for papers, name for collections, filename for pdfs
        )
        self.data = data or {}  # data to add/edit with


class SyncConflict:
    """Represents a sync conflict between local and remote data."""

    def __init__(
        self, conflict_type: str, item_id: str, local_data: Dict, remote_data: Dict
    ):
        self.conflict_type = conflict_type  # 'paper', 'pdf' (no collections)
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
            "html_snapshots_copied": 0,
        }
        self.detailed_changes: Dict[str, List[str]] = {
            "papers_added": [],
            "papers_updated": [],
            "collections_added": [],
            "collections_updated": [],
            "pdfs_copied": [],
            "pdfs_updated": [],
            "html_snapshots_copied": [],
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
            return (
                f"Sync completed with "
                f"{_pluralizer.pluralize('conflict', len(self.conflicts), True)} that need resolution"
            )

        total_changes = sum(self.changes_applied.values())
        has_detailed_changes = (
            any(self.detailed_changes.values())
            if hasattr(self, "detailed_changes")
            else False
        )

        if total_changes == 0 and not has_detailed_changes:
            return "No changes to sync - local and remote are already in sync"

        summary_parts = []
        if self.changes_applied["papers_added"] > 0:
            count = self.changes_applied["papers_added"]
            summary_parts.append(f"{_pluralizer.pluralize('paper', count, True)} added")
        if self.changes_applied["papers_updated"] > 0:
            count = self.changes_applied["papers_updated"]
            summary_parts.append(
                f"{_pluralizer.pluralize('paper', count, True)} updated"
            )
        if self.changes_applied["collections_added"] > 0:
            c = self.changes_applied["collections_added"]
            summary_parts.append(
                f"{_pluralizer.pluralize('collection', c, True)} added"
            )
        if self.changes_applied["collections_updated"] > 0:
            c = self.changes_applied["collections_updated"]
            summary_parts.append(
                f"{_pluralizer.pluralize('collection', c, True)} updated"
            )
        if self.changes_applied["pdfs_copied"] > 0:
            c = self.changes_applied["pdfs_copied"]
            summary_parts.append(f"{_pluralizer.pluralize('PDF', c, True)} copied")
        if self.changes_applied["html_snapshots_copied"] > 0:
            c = self.changes_applied["html_snapshots_copied"]
            summary_parts.append(f"{_pluralizer.pluralize('HTML snapshot', c, True)} copied")

        return f"Sync completed: {', '.join(summary_parts)}"


class SyncService:
    """Simplified service for managing synchronization between local and remote databases."""

    def __init__(
        self,
        local_data_dir: str,
        remote_data_dir: str,
        app,
        progress_callback=None,
    ):
        self.local_data_dir = Path(local_data_dir)
        self.remote_data_dir = Path(remote_data_dir)
        self.local_db_path = self.local_data_dir / "papers.db"
        self.remote_db_path = self.remote_data_dir / "papers.db"
        self.local_pdf_dir = self.local_data_dir / "pdfs"
        self.remote_pdf_dir = self.remote_data_dir / "pdfs"
        self.local_html_snapshots_dir = self.local_data_dir / "html_snapshots"
        self.remote_html_snapshots_dir = self.remote_data_dir / "html_snapshots"
        self.progress_callback = progress_callback
        self.app = app

        # Lock file paths
        self.local_lock_file = self.local_data_dir / ".papercli_sync.lock"
        self.remote_lock_file = self.remote_data_dir / ".papercli_sync.lock"

        # Track title changes during keep_both resolution for collection syncing
        self.title_mappings = (
            {}
        )  # Maps original_title -> new_title  # Maps original_title -> new_title
        self._column_cache: Dict[Tuple[str, str, str], bool] = {}

    def _acquire_locks(self) -> bool:
        """Acquire sync locks on both local and remote directories."""
        try:
            if self._check_existing_locks():
                return False

            lock_info = {
                "process_id": os.getpid(),
                "timestamp": datetime.now().isoformat(),
                "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
            }

            self.local_data_dir.mkdir(exist_ok=True)
            with open(self.local_lock_file, "w") as f:
                json.dump(lock_info, f)

            self.remote_data_dir.mkdir(exist_ok=True)
            with open(self.remote_lock_file, "w") as f:
                json.dump(lock_info, f)

            return True
        except Exception as e:
            self._release_locks()
            raise Exception(f"Failed to acquire sync locks: {str(e)}")

    def _check_existing_locks(self) -> bool:
        """Check if any sync locks exist and if they're still valid."""
        for lock_file in [self.local_lock_file, self.remote_lock_file]:
            if lock_file.exists():
                try:
                    with open(lock_file, "r") as f:
                        lock_info = json.load(f)

                    lock_time = datetime.fromisoformat(lock_info.get("timestamp", ""))
                    time_diff = datetime.now() - lock_time

                    if time_diff.total_seconds() > 1800:  # 30 minutes
                        lock_file.unlink()
                        continue

                    process_id = lock_info.get("process_id")
                    if process_id and self._is_process_running(process_id):
                        return True
                    else:
                        lock_file.unlink()
                except (json.JSONDecodeError, ValueError, KeyError):
                    lock_file.unlink()
        return False

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
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
                    pass

    def _database_has_column(self, db_path: Path, table: str, column: str) -> bool:
        """Check if a given table in the database has a specific column."""
        cache_key = (str(db_path), table, column)
        if cache_key in self._column_cache:
            return self._column_cache[cache_key]

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            has_column = any(row[1] == column for row in cursor.fetchall())
            self._column_cache[cache_key] = has_column
            return has_column
        finally:
            conn.close()

    def _database_has_uuid_column(self, db_path: Path) -> bool:
        """Determine whether the papers table contains a UUID column."""
        return self._database_has_column(db_path, "papers", "uuid")

    def _database_has_html_snapshot_column(self, db_path: Path) -> bool:
        """Determine whether the papers table contains an HTML snapshot column."""
        return self._database_has_column(db_path, "papers", "html_snapshot_path")

    def _lookup_paper_uuid(self, db_path: Path, title: str) -> Optional[str]:
        """Look up a paper's UUID by title within a specific database."""
        if not self._database_has_uuid_column(db_path):
            return None

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT uuid FROM papers WHERE title = ?", (title,))
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
            return None
        finally:
            conn.close()

    def _lookup_paper_uuid_in_databases(self, title: str) -> Optional[str]:
        """Look up a paper UUID across both local and remote databases."""
        uuid_value = self._lookup_paper_uuid(self.local_db_path, title)
        if uuid_value:
            return uuid_value
        return self._lookup_paper_uuid(self.remote_db_path, title)

    def _default_html_snapshot_path(self, filename: str) -> str:
        """Return the standardized relative path for an HTML snapshot file."""
        return filename

    def _update_html_snapshot_references(
        self,
        db_path: Path,
        papers: List[Dict[str, Optional[str]]],
        snapshot_path: str,
    ) -> None:
        """Ensure referenced papers point to the provided HTML snapshot path."""
        if not papers:
            return

        if not self._database_has_html_snapshot_column(db_path):
            ensure_schema_current(str(db_path), silent=True)
            self._column_cache.pop(
                (str(db_path), "papers", "html_snapshot_path"), None
            )
            if not self._database_has_html_snapshot_column(db_path):
                return

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            has_uuid = self._database_has_uuid_column(db_path)
            for entry in papers:
                updated = False
                uuid_value = entry.get("uuid")
                title = entry.get("title")

                if uuid_value and has_uuid:
                    cursor.execute(
                        "UPDATE papers SET html_snapshot_path = ? WHERE uuid = ?",
                        (snapshot_path, uuid_value),
                    )
                    updated = cursor.rowcount > 0

                if not updated and title:
                    cursor.execute(
                        "UPDATE papers SET html_snapshot_path = ? WHERE title = ?",
                        (snapshot_path, title),
                    )

            conn.commit()
        finally:
            conn.close()

    def _link_paper_to_collection(
        self,
        cursor: sqlite3.Cursor,
        target_db_path: Path,
        collection_id: int,
        paper_title: str,
        paper_uuid: Optional[str] = None,
    ) -> bool:
        """Link a paper to a collection using UUID when available, falling back to titles."""
        candidates: List[Tuple[str, str]] = []

        if paper_uuid:
            candidates.append(("uuid", paper_uuid))
        else:
            fallback_uuid = self._lookup_paper_uuid_in_databases(paper_title)
            if fallback_uuid:
                candidates.append(("uuid", fallback_uuid))

        candidates.append(("title", paper_title))

        if paper_title in self.title_mappings:
            candidates.append(("title", self.title_mappings[paper_title]))

        if paper_title.endswith(" (Remote Version)"):
            original_title = paper_title[: -len(" (Remote Version)")]
            candidates.append(("title", original_title))

        seen_values = set()
        for query_type, value in candidates:
            if not value or value in seen_values:
                continue
            seen_values.add(value)

            if query_type == "uuid":
                if not self._database_has_uuid_column(target_db_path):
                    continue
                cursor.execute("SELECT id FROM papers WHERE uuid = ?", (value,))
            else:
                cursor.execute("SELECT id FROM papers WHERE title = ?", (value,))

            row = cursor.fetchone()
            if row:
                cursor.execute(
                    "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                    (row[0], collection_id),
                )
                return True

        return False

    def sync(self, conflict_resolver=None, auto_sync_mode=False) -> SyncResult:
        """Simplified sync: generate operations, get user confirmation, execute sync."""
        result = SyncResult()

        # Clear title mappings from any previous sync
        self.title_mappings.clear()
        # Remember mode for downstream helpers (collections policy)
        self._auto_sync_mode = bool(auto_sync_mode)

        if self.app:
            self.app._add_log("sync_start", "Starting database synchronization")

        if not self._acquire_locks():
            if self.app:
                self.app._add_log(
                    "sync_error", "Another sync operation is already in progress"
                )
            raise Exception(
                "Another sync operation is already in progress. Please wait for it to complete."
            )

        try:
            # Fix absolute PDF paths to relative before sync to prevent conflicts
            if self.progress_callback:
                self.progress_callback("Converting absolute PDF paths to relative...")
            self._fix_absolute_pdf_paths()
            time.sleep(0.1)
            # Ensure remote directory exists
            if self.progress_callback:
                self.progress_callback("Creating remote directory...")
            self.remote_data_dir.mkdir(parents=True, exist_ok=True)
            self.remote_pdf_dir.mkdir(parents=True, exist_ok=True)
            self.remote_html_snapshots_dir.mkdir(parents=True, exist_ok=True)
            time.sleep(0.1)

            # Upgrade local database schema if needed
            if self.progress_callback:
                self.progress_callback("Checking local database schema...")
            local_upgraded = self._upgrade_database_schema(self.local_db_path)

            # If Alembic upgrade failed, try manual upgrade
            if not local_upgraded:
                if self.app:
                    self.app._add_log(
                        "sync_manual_upgrade_attempt",
                        "Alembic upgrade failed, attempting manual schema upgrade for local database",
                    )
                ensure_schema_current(str(self.local_db_path), silent=True)
            time.sleep(0.1)

            # If remote database doesn't exist, copy from local
            if not self.remote_db_path.exists():
                if self.app:
                    self.app._add_log(
                        "sync_init", "Remote database not found, copying from local"
                    )
                shutil.copy2(self.local_db_path, self.remote_db_path)
                papers_count = self._count_papers(self.local_db_path)
                result.changes_applied["papers_added"] = papers_count
                self._sync_pdfs_to_remote(result)
                if self.app:
                    self.app._add_log(
                        "sync_complete",
                        f"Initial sync complete: {papers_count} papers copied",
                    )
                return result

            # Upgrade remote database schema if needed
            if self.progress_callback:
                self.progress_callback("Checking remote database schema...")
            remote_upgraded = self._upgrade_database_schema(self.remote_db_path)

            # If Alembic upgrade failed, try manual upgrade
            if not remote_upgraded:
                if self.app:
                    self.app._add_log(
                        "sync_manual_upgrade_attempt",
                        "Alembic upgrade failed, attempting manual schema upgrade for remote database",
                    )
                ensure_schema_current(str(self.remote_db_path), silent=True)
            time.sleep(0.1)

            # Check schema compatibility (both auto and manual sync)
            local_has_uuid_col = self._database_has_uuid_column(self.local_db_path)
            remote_has_uuid_col = self._database_has_uuid_column(self.remote_db_path)

            if local_has_uuid_col and not remote_has_uuid_col:
                if auto_sync_mode:
                    error_msg = (
                        "Schema mismatch: Local has UUID column but remote does not. "
                        "Auto-sync paused. Please run manual sync to upgrade remote."
                    )
                else:
                    error_msg = (
                        "Schema mismatch: Local has UUID column but remote does not. "
                        "Auto-upgrade failed. Manually run: alembic upgrade head"
                    )
                if self.app:
                    self.app._add_log("sync_error", error_msg)
                raise Exception(error_msg)
            elif not local_has_uuid_col and remote_has_uuid_col:
                # Try manual upgrade as fallback
                if self.app:
                    self.app._add_log(
                        "sync_fix",
                        "Local database is older version. Attempting manual schema upgrade...",
                    )

                if ensure_schema_current(str(self.local_db_path), silent=True):
                    # Successfully added UUID column, re-check
                    local_has_uuid_col = self._database_has_uuid_column(self.local_db_path)
                    if local_has_uuid_col:
                        if self.app:
                            self.app._add_log(
                                "sync_fix_success",
                                "Successfully upgraded local database schema",
                            )
                    else:
                        error_msg = (
                            "Schema mismatch: Remote has UUID column but local does not. "
                            "Manual upgrade failed. Please run: python -m alembic upgrade head"
                        )
                        if self.app:
                            self.app._add_log("sync_error", error_msg)
                        raise Exception(error_msg)
                else:
                    error_msg = (
                        "Schema mismatch: Remote has UUID column but local does not. "
                        "Automatic upgrade failed. Please upgrade your local database by running:\n"
                        "  python -m alembic upgrade head\n"
                        "or delete the remote database to sync from scratch."
                    )
                    if self.app:
                        self.app._add_log("sync_error", error_msg)
                    raise Exception(error_msg)

            # If both have UUID column, sync UUIDs before operations
            if local_has_uuid_col and remote_has_uuid_col:
                if self.progress_callback:
                    self.progress_callback("Synchronizing UUIDs...")
                self._sync_uuids()
                time.sleep(0.1)

            # Step 1: Generate all operations needed
            if self.progress_callback:
                self.progress_callback("Analyzing differences...")
            operations = self._generate_sync_operations()
            if self.app:
                count_ops = len(operations)
                ops_text = _pluralizer.pluralize("sync operation", count_ops, True)
                self.app._add_log("sync_operations", f"Generated {ops_text}")
            time.sleep(0.1)

            if not operations:
                # No paper/PDF differences, but still check collections
                if self.progress_callback:
                    self.progress_callback("Synchronizing collections...")
                if self.app:
                    self.app._add_log(
                        "sync_collections_only",
                        "No paper/PDF changes, checking collections...",
                    )
                self._sync_collections_by_timestamp(result)
                if self.app:
                    changes = result.changes_applied
                    total_changes = sum(changes.values())
                    if total_changes > 0:
                        total_text = _pluralizer.pluralize(
                            "change", total_changes, True
                        )
                        self.app._add_log(
                            "sync_complete",
                            f"Collection sync complete: {total_text} applied",
                        )
                    else:
                        self.app._add_log(
                            "sync_complete", "No collection changes needed"
                        )
                return result

            # Step 2: Get user confirmation for conflicting papers/PDFs
            conflicts = [op for op in operations if op.operation_type == "conflict"]
            if conflicts and conflict_resolver:
                ui_conflicts = self._operations_to_conflicts(conflicts)
                resolved_conflicts = conflict_resolver(ui_conflicts)
                if resolved_conflicts is None:
                    result.cancelled = True
                    return result

                operations = self._resolve_conflicts_to_operations(
                    conflicts, resolved_conflicts, operations
                )

            # Step 3: Execute sync - Remote to Local, then Local overrides Remote
            if self.progress_callback:
                self.progress_callback("Synchronizing remote to local...")
            if self.app:
                remote_ops = [op for op in operations if op.target == "local"]
                ops_text = _pluralizer.pluralize("operation", len(remote_ops), True)
                self.app._add_log(
                    "sync_start",
                    f"Starting remote→local sync: {ops_text}",
                )
            self._sync_remote_to_local(operations, result)
            time.sleep(0.1)

            # Recover missing HTML snapshots even if no operations were scheduled
            self._repair_missing_assets("pdf", result)
            self._repair_missing_assets("html_snapshot", result)

            if self.progress_callback:
                self.progress_callback("Synchronizing local to remote...")
            if self.app:
                local_ops = [op for op in operations if op.target == "remote"]
                ops_text = _pluralizer.pluralize("operation", len(local_ops), True)
                self.app._add_log(
                    "sync_start",
                    f"Starting local→remote sync: {ops_text}",
                )
            self._sync_local_to_remote(operations, result)
            time.sleep(0.1)

            # Step 4: Handle collections automatically (by timestamp)
            if self.progress_callback:
                self.progress_callback("Synchronizing collections...")
            if self.app:
                self.app._add_log(
                    "sync_start", "Starting collection synchronization..."
                )
            self._sync_collections_by_timestamp(result)
            time.sleep(0.1)

            # Note: Orphan PDF cleanup removed - should only be done when explicitly requested by user
            # Use /doctor clean command to manually clean orphaned PDFs

        except Exception as e:
            result.errors.append(f"Sync failed: {str(e)}")
            if self.app:
                self.app._add_log("sync_error", f"Sync failed with error: {str(e)}")
        finally:
            self._release_locks()
            if self.app:
                if result.errors:
                    self.app._add_log(
                        "sync_failed",
                        f"Sync failed with {len(result.errors)} error(s): {'; '.join(result.errors[:3])}",
                    )
                else:
                    changes = result.changes_applied
                    total_changes = sum(changes.values())
                    if total_changes > 0:
                        # Build detailed change summary
                        change_details = []
                        if changes["papers_added"]:
                            c = changes["papers_added"]
                            change_details.append(
                                f"{_pluralizer.pluralize('paper', c, True)} added"
                            )
                        if changes["papers_updated"]:
                            c = changes["papers_updated"]
                            change_details.append(
                                f"{_pluralizer.pluralize('paper', c, True)} updated"
                            )
                        if changes["collections_added"]:
                            c = changes["collections_added"]
                            change_details.append(
                                f"{_pluralizer.pluralize('collection', c, True)} added"
                            )
                        if changes["collections_updated"]:
                            c = changes["collections_updated"]
                            change_details.append(
                                f"{_pluralizer.pluralize('collection', c, True)} updated"
                            )
                        if changes["pdfs_copied"]:
                            c = changes["pdfs_copied"]
                            change_details.append(
                                f"{_pluralizer.pluralize('PDF', c, True)} copied"
                            )
                        if changes["pdfs_updated"]:
                            c = changes["pdfs_updated"]
                            change_details.append(
                                f"{_pluralizer.pluralize('PDF', c, True)} updated"
                            )
                        if changes["html_snapshots_copied"]:
                            c = changes["html_snapshots_copied"]
                            change_details.append(
                                f"{_pluralizer.pluralize('HTML snapshot', c, True)} copied"
                            )

                        detailed_summary = "; ".join(change_details)
                        total_text = _pluralizer.pluralize(
                            "change", total_changes, True
                        )
                        self.app._add_log(
                            "sync_success",
                            f"Sync completed successfully: {total_text} ({detailed_summary})",
                        )

                        # Log specific items that were changed
                        for change_type, items in result.detailed_changes.items():
                            if items:
                                items_preview = items[:5]  # Show first 5 items
                                more_count = len(items) - len(items_preview)
                                items_str = ", ".join(item for item in items_preview)
                                if more_count > 0:
                                    items_str += f" and {more_count} more"
                                self.app._add_log(
                                    "sync_details",
                                    f"{change_type.replace('_', ' ').title()}: {items_str}",
                                )
                    else:
                        self.app._add_log(
                            "sync_success",
                            "Sync completed successfully: databases already in sync",
                        )

        return result

    def _generate_sync_operations(self) -> List[SyncOperation]:
        """Generate all sync operations needed to make databases identical."""
        operations = []

        # Get papers from both databases
        local_papers = self._get_papers_dict(self.local_db_path)
        remote_papers = self._get_papers_dict(self.remote_db_path)

        # Use UUID-based matching
        matched_remote_uuids = set()

        # Process local papers
        for local_uuid, local_paper in local_papers.items():
            if local_uuid in remote_papers:
                # Found matching paper by UUID
                remote_paper = remote_papers[local_uuid]
                matched_remote_uuids.add(local_uuid)

                # Check if they differ
                if self._papers_differ(local_paper, remote_paper):
                    operations.append(
                        SyncOperation(
                            "conflict",
                            "both",
                            "paper",
                            local_paper["title"],  # Use title for display
                            {"local": local_paper, "remote": remote_paper},
                        )
                    )
            else:
                # Paper only exists locally, add to remote
                operations.append(
                    SyncOperation(
                        "add", "remote", "paper", local_paper["title"], local_paper
                    )
                )

        # Process unmatched remote papers (papers only in remote)
        for remote_uuid, remote_paper in remote_papers.items():
            if remote_uuid not in matched_remote_uuids:
                operations.append(
                    SyncOperation(
                        "add", "local", "paper", remote_paper["title"], remote_paper
                    )
                )

        # Check file-based asset conflicts (PDFs and HTML snapshots)
        operations.extend(self._generate_asset_operations("pdf"))
        operations.extend(self._generate_asset_operations("html_snapshot"))

        return operations

    # --- PDF cleanup helpers ---
    def _get_referenced_pdf_names(self, db_path: Path) -> set:
        names: set = set()
        conn = None
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_path FROM papers WHERE pdf_path IS NOT NULL")
            for (pdf_path,) in cursor.fetchall():
                names.add(Path(pdf_path).name)
        finally:
            if conn is not None:
                conn.close()
        return names

    def _cleanup_orphan_pdfs(self, pdf_dir: Path, db_path: Path, label: str) -> None:
        if not pdf_dir.exists():
            return
        # Prefer existing DatabaseHealthService for local cleanup
        if label == "local":
            try:
                db_health = DatabaseHealthService(app=self.app)
                res = db_health.clean_orphaned_pdfs()
                deleted = int(res.get("deleted_pdfs", 0))
                if self.app and deleted:
                    self.app._add_log(
                        "sync_cleanup",
                        f"Deleted {_pluralizer.pluralize('orphan local PDF', deleted, True)}",
                    )
            except Exception as e:
                if self.app:
                    self.app._add_log(
                        "sync_cleanup_error",
                        f"Local orphan PDF cleanup failed: {e}",
                    )
            return

        referenced = self._get_referenced_pdf_names(db_path)
        deleted = 0
        for f in pdf_dir.glob("*.pdf"):
            if f.name not in referenced:
                f.unlink()
                deleted += 1
        if self.app and deleted:
            self.app._add_log(
                "sync_cleanup",
                f"Deleted {_pluralizer.pluralize(f'orphan {label} PDF', deleted, True)}",
            )

    def _build_pdf_map(
        self, db_path: Path, pdf_dir: Path
    ) -> Dict[str, Dict[str, object]]:
        """Collect referenced PDFs and their file info."""
        referenced: set[str] = set()
        papers = self._get_papers_dict(db_path)
        for paper in papers.values():
            pdf_path = paper.get("pdf_path")
            if not pdf_path:
                continue
            try:
                referenced.add(Path(pdf_path).name)
            except Exception:
                continue

        return {
            f.name: self._get_file_info(f)
            for f in pdf_dir.glob("*.pdf")
            if f.name in referenced
        }

    def _build_html_snapshot_map(
        self, db_path: Path, snapshots_dir: Path
    ) -> Dict[str, Dict[str, object]]:
        """Collect referenced HTML snapshots, file info, and paper metadata."""
        papers = self._get_papers_dict(db_path)
        references: Dict[str, List[Dict[str, Optional[str]]]] = {}
        for p in papers.values():
            html_path = p.get("html_snapshot_path")
            if not html_path:
                continue
            try:
                filename = Path(html_path).name
            except Exception:
                continue
            references.setdefault(filename, []).append(
                {
                    "uuid": p.get("uuid"),
                    "title": p.get("title"),
                    "stored_path": html_path,
                }
            )

        snapshot_map: Dict[str, Dict[str, object]] = {}
        for filename, entries in references.items():
            stored_paths = [
                entry.get("stored_path")
                for entry in entries
                if entry.get("stored_path")
            ]
            file_path = snapshots_dir / filename
            if not file_path.exists():
                for stored in stored_paths:
                    if not stored:
                        continue
                    alt_path = snapshots_dir / stored
                    if alt_path.exists():
                        file_path = alt_path
                        break
                else:
                    continue
            if stored_paths:
                relative_path = Path(stored_paths[0]).name
            else:
                relative_path = filename
            simplified_entries = [
                {"uuid": entry.get("uuid"), "title": entry.get("title")}
                for entry in entries
            ]
            snapshot_map[filename] = {
                "file": self._get_file_info(file_path),
                "papers": simplified_entries,
                "relative_path": relative_path,
                "stored_paths": stored_paths,
            }
        return snapshot_map

    def _get_asset_hash(self, asset_info: Dict[str, object]) -> Optional[str]:
        """Extract hash value from PDF or HTML snapshot metadata."""
        if not asset_info:
            return None
        if "file" in asset_info and isinstance(asset_info["file"], dict):
            return asset_info["file"].get("hash")
        return asset_info.get("hash")

    def _generate_asset_operations(self, asset_type: str) -> List[SyncOperation]:
        """Generate add/conflict operations for a file-based asset type."""
        if asset_type == "pdf":
            if not (
                self.local_pdf_dir.exists() and self.remote_pdf_dir.exists()
            ):
                return []
            local_assets = self._build_pdf_map(self.local_db_path, self.local_pdf_dir)
            remote_assets = self._build_pdf_map(
                self.remote_db_path, self.remote_pdf_dir
            )
        elif asset_type == "html_snapshot":
            self.local_html_snapshots_dir.mkdir(parents=True, exist_ok=True)
            self.remote_html_snapshots_dir.mkdir(parents=True, exist_ok=True)
            local_assets = self._build_html_snapshot_map(
                self.local_db_path, self.local_html_snapshots_dir
            )
            remote_assets = self._build_html_snapshot_map(
                self.remote_db_path, self.remote_html_snapshots_dir
            )
        else:
            return []

        operations: List[SyncOperation] = []

        # Assets present in both locations but differing by hash
        for filename in set(local_assets.keys()) & set(remote_assets.keys()):
            local_info = local_assets[filename]
            remote_info = remote_assets[filename]
            if self._get_asset_hash(local_info) != self._get_asset_hash(remote_info):
                operations.append(
                    SyncOperation(
                        "conflict",
                        "both",
                        asset_type,
                        filename,
                        {"local": local_info, "remote": remote_info},
                    )
                )

        # Assets only on local -> copy to remote
        for filename in local_assets.keys() - remote_assets.keys():
            operations.append(
                SyncOperation(
                    "add", "remote", asset_type, filename, local_assets[filename]
                )
            )

        # Assets only on remote -> copy to local
        for filename in remote_assets.keys() - local_assets.keys():
            operations.append(
                SyncOperation(
                    "add", "local", asset_type, filename, remote_assets[filename]
                )
            )

        return operations

    def _operations_to_conflicts(
        self, conflict_operations: List[SyncOperation]
    ) -> List[SyncConflict]:
        """Convert conflict operations to SyncConflict objects for UI compatibility."""
        conflicts = []
        for op in conflict_operations:
            conflict = SyncConflict(
                op.item_type, op.item_id, op.data["local"], op.data["remote"]
            )
            conflicts.append(conflict)
        return conflicts

    def _resolve_conflicts_to_operations(
        self,
        conflicts: List[SyncOperation],
        resolved_conflicts: Dict,
        all_operations: List[SyncOperation],
    ) -> List[SyncOperation]:
        """Convert user conflict resolutions back to concrete operations."""
        operations = []

        # Add non-conflict operations as-is
        operations.extend(
            [op for op in all_operations if op.operation_type != "conflict"]
        )

        # Convert each conflict resolution to operations
        for conflict_op in conflicts:
            conflict_id = f"{conflict_op.item_type}_{conflict_op.item_id}"
            resolution = resolved_conflicts.get(conflict_id, "keep_both")

            if resolution == "local":
                # Use local version: delete remote, add local to remote
                if self.app:
                    self.app._add_log(
                        "sync_conflicts",
                        f"Resolved conflict for {conflict_op.item_type} '{conflict_op.item_id}': using LOCAL version",
                    )
                operations.append(
                    SyncOperation(
                        "delete", "remote", conflict_op.item_type, conflict_op.item_id
                    )
                )
                operations.append(
                    SyncOperation(
                        "add",
                        "remote",
                        conflict_op.item_type,
                        conflict_op.item_id,
                        conflict_op.data["local"],
                    )
                )

            elif resolution == "remote":
                # Use remote version: delete local, add remote to local
                if self.app:
                    self.app._add_log(
                        "sync_conflicts",
                        f"Resolved conflict for {conflict_op.item_type} '{conflict_op.item_id}': using REMOTE version",
                    )
                operations.append(
                    SyncOperation(
                        "delete", "local", conflict_op.item_type, conflict_op.item_id
                    )
                )
                operations.append(
                    SyncOperation(
                        "add",
                        "local",
                        conflict_op.item_type,
                        conflict_op.item_id,
                        conflict_op.data["remote"],
                    )
                )

            elif resolution == "keep_both":
                # Keep both: add both to both databases with different names
                if conflict_op.item_type == "paper":
                    if self.app:
                        self.app._add_log(
                            "sync_conflicts",
                            f"Resolved conflict for paper '{conflict_op.item_id}': KEEPING BOTH versions",
                        )
                    # Local version keeps original title
                    operations.append(
                        SyncOperation(
                            "add",
                            "remote",
                            "paper",
                            conflict_op.item_id,
                            conflict_op.data["local"],
                        )
                    )
                    # Remote version gets modified title
                    remote_data = dict(conflict_op.data["remote"])
                    new_title = f"{conflict_op.item_id} (Remote Version)"
                    remote_data["title"] = new_title
                    # Track title mapping for collection syncing
                    self.title_mappings[conflict_op.item_id] = new_title
                    if self.app:
                        self.app._add_log(
                            "sync_conflicts",
                            f"Remote version renamed to: '{new_title}'",
                        )
                    operations.append(
                        SyncOperation("delete", "remote", "paper", conflict_op.item_id)
                    )
                    operations.append(
                        SyncOperation("add", "remote", "paper", new_title, remote_data)
                    )
                    operations.append(
                        SyncOperation("add", "local", "paper", new_title, remote_data)
                    )

                elif conflict_op.item_type == "pdf":
                    # Keep local PDF as-is, add remote with _remote suffix
                    if self.app:
                        self.app._add_log(
                            "sync_conflicts",
                            f"Resolved conflict for PDF '{conflict_op.item_id}': KEEPING BOTH versions",
                        )
                    base_name = Path(conflict_op.item_id).stem
                    extension = Path(conflict_op.item_id).suffix
                    remote_filename = f"{base_name}_remote{extension}"
                    if self.app:
                        self.app._add_log(
                            "sync_conflicts",
                            f"Remote PDF renamed to: '{remote_filename}'",
                        )
                    operations.append(
                        SyncOperation(
                            "add",
                            "local",
                            "pdf",
                            remote_filename,
                            conflict_op.data["remote"],
                        )
                    )
                    operations.append(
                        SyncOperation(
                            "add",
                            "remote",
                            "pdf",
                            remote_filename,
                            conflict_op.data["remote"],
                        )
                    )

        return operations

    def _sync_remote_to_local(
        self, operations: List[SyncOperation], result: SyncResult
    ):
        """Execute all operations that sync remote to local."""
        for op in operations:
            if op.target == "local":
                if op.operation_type == "add":
                    if op.item_type == "paper":
                        self._copy_paper_to_local(op.data)
                        result.changes_applied["papers_added"] += 1
                        result.detailed_changes["papers_added"].append(
                            f"'{op.item_id}' (from remote)"
                        )
                        # Log detailed paper information
                        if self.app:
                            authors = op.data.get("authors", "N/A")
                            venue = op.data.get("venue_full", "N/A")
                            year = op.data.get("year", "N/A")
                            self.app._add_log(
                                "sync_remote_to_local",
                                f"Added paper from remote: '{op.item_id}' by {authors} ({venue}, {year})",
                            )
                    elif op.item_type == "pdf":
                        metadata = op.data if isinstance(op.data, dict) else {}
                        if self._copy_asset_file(
                            "pdf",
                            op.item_id,
                            self.remote_pdf_dir,
                            self.local_pdf_dir,
                            metadata,
                        ):
                            result.changes_applied["pdfs_copied"] += 1
                            result.detailed_changes["pdfs_copied"].append(
                                f"'{op.item_id}' (from remote)"
                            )
                            if self.app:
                                self.app._add_log(
                                    "sync_remote_to_local",
                                    f"Copied PDF from remote: {op.item_id}",
                                )
                    elif op.item_type == "html_snapshot":
                        metadata = op.data if isinstance(op.data, dict) else {}
                        if self._copy_asset_file(
                            "html_snapshot",
                            op.item_id,
                            self.remote_html_snapshots_dir,
                            self.local_html_snapshots_dir,
                            metadata,
                        ):
                            self._handle_post_copy(
                                "html_snapshot",
                                metadata,
                                self.local_db_path,
                                op.item_id,
                                self.local_html_snapshots_dir,
                            )
                            result.changes_applied["html_snapshots_copied"] += 1
                            result.detailed_changes["html_snapshots_copied"].append(
                                f"'{op.item_id}' (from remote)"
                            )
                            if self.app:
                                self.app._add_log(
                                    "sync_remote_to_local",
                                    f"Copied HTML snapshot from remote: {op.item_id}",
                                )

                elif op.operation_type == "delete":
                    if op.item_type == "paper":
                        self._delete_paper_by_title(self.local_db_path, op.item_id)
                        if self.app:
                            self.app._add_log(
                                "sync_remote_to_local",
                                f"Updating local paper '{op.item_id}' with remote version",
                            )
                    elif op.item_type == "pdf":
                        pdf_path = self.local_pdf_dir / op.item_id
                        if pdf_path.exists():
                            pdf_path.unlink()
                            if self.app:
                                self.app._add_log(
                                    "sync_remote_to_local",
                                    f"Updating local PDF: {op.item_id} with remote version",
                                )
                    elif op.item_type == "html_snapshot":
                        html_path = self.local_html_snapshots_dir / op.item_id
                        if html_path.exists():
                            html_path.unlink()
                            if self.app:
                                self.app._add_log(
                                    "sync_remote_to_local",
                                    f"Updating local HTML snapshot: {op.item_id} with remote version",
                                )

    def _sync_local_to_remote(
        self, operations: List[SyncOperation], result: SyncResult
    ):
        """Execute all operations that sync local to remote."""
        for op in operations:
            if op.target == "remote":
                if op.operation_type == "add":
                    if op.item_type == "paper":
                        self._copy_paper_to_remote(op.data)
                        result.changes_applied["papers_added"] += 1
                        result.detailed_changes["papers_added"].append(
                            f"'{op.item_id}'"
                        )
                        # Log detailed paper information
                        if self.app:
                            authors = op.data.get("authors", "N/A")
                            venue = op.data.get("venue_full", "N/A")
                            year = op.data.get("year", "N/A")
                            self.app._add_log(
                                "sync_local_to_remote",
                                f"Added paper to remote: '{op.item_id}' by {authors} ({venue}, {year})",
                            )
                    elif op.item_type == "pdf":
                        metadata = op.data if isinstance(op.data, dict) else {}
                        if self._copy_asset_file(
                            "pdf",
                            op.item_id,
                            self.local_pdf_dir,
                            self.remote_pdf_dir,
                            metadata,
                        ):
                            result.changes_applied["pdfs_copied"] += 1
                            result.detailed_changes["pdfs_copied"].append(f"'{op.item_id}'")
                            if self.app:
                                self.app._add_log(
                                    "sync_local_to_remote",
                                    f"Copied PDF to remote: {op.item_id}",
                                )
                    elif op.item_type == "html_snapshot":
                        metadata = op.data if isinstance(op.data, dict) else {}
                        if self._copy_asset_file(
                            "html_snapshot",
                            op.item_id,
                            self.local_html_snapshots_dir,
                            self.remote_html_snapshots_dir,
                            metadata,
                        ):
                            self._handle_post_copy(
                                "html_snapshot",
                                metadata,
                                self.remote_db_path,
                                op.item_id,
                                self.remote_html_snapshots_dir,
                            )
                            result.changes_applied["html_snapshots_copied"] += 1
                            result.detailed_changes["html_snapshots_copied"].append(
                                f"'{op.item_id}'"
                            )
                            if self.app:
                                self.app._add_log(
                                    "sync_local_to_remote",
                                    f"Copied HTML snapshot to remote: {op.item_id}",
                                )

                elif op.operation_type == "delete":
                    if op.item_type == "paper":
                        self._delete_paper_by_title(self.remote_db_path, op.item_id)
                        if self.app:
                            self.app._add_log(
                                "sync_local_to_remote",
                                f"Updating remote paper '{op.item_id}' with local version",
                            )
                    elif op.item_type == "pdf":
                        pdf_path = self.remote_pdf_dir / op.item_id
                        if pdf_path.exists():
                            pdf_path.unlink()
                            if self.app:
                                self.app._add_log(
                                    "sync_local_to_remote",
                                    f"Updating remote PDF: {op.item_id} with local version",
                                )
                    elif op.item_type == "html_snapshot":
                        html_path = self.remote_html_snapshots_dir / op.item_id
                        if html_path.exists():
                            html_path.unlink()
                            if self.app:
                                self.app._add_log(
                                    "sync_local_to_remote",
                                    f"Updating remote HTML snapshot: {op.item_id} with local version",
                                )

    def _handle_post_copy(
        self,
        asset_type: str,
        metadata: Dict[str, object],
        target_db_path: Path,
        filename: str,
        target_dir: Path,
    ) -> None:
        """Apply metadata updates after copying a file-based asset."""
        if asset_type != "html_snapshot" or not isinstance(metadata, dict):
            return

        papers = metadata.get("papers", []) or []
        relative_path = metadata.get("relative_path") or self._default_html_snapshot_path(
            filename
        )

        self._update_html_snapshot_references(target_db_path, papers, relative_path)

        stored_paths = metadata.get("stored_paths") or []
        for stored in stored_paths:
            if not stored:
                continue
            try:
                alt_path = target_dir / stored
            except Exception:
                continue
            dest_path = target_dir / filename
            if alt_path == dest_path:
                continue
            if alt_path.exists():
                try:
                    alt_path.unlink()
                except Exception:
                    pass

    def _resolve_asset_source_path(
        self,
        asset_type: str,
        filename: str,
        source_dir: Path,
        metadata: Optional[Dict[str, object]],
    ) -> Path:
        """Determine the best source path for a sync asset."""
        candidates: List[Path] = []
        primary = source_dir / filename
        candidates.append(primary)

        if metadata:
            meta_path = metadata.get("path")
            if meta_path:
                try:
                    candidates.append(Path(meta_path))
                except Exception:
                    pass
            file_info = metadata.get("file")
            if isinstance(file_info, dict):
                file_meta_path = file_info.get("path")
                if file_meta_path:
                    try:
                        candidates.append(Path(file_meta_path))
                    except Exception:
                        pass
            if asset_type == "html_snapshot":
                for stored in metadata.get("stored_paths", []) or []:
                    if not stored:
                        continue
                    try:
                        candidates.append(source_dir / stored)
                        candidates.append(source_dir / Path(stored).name)
                    except Exception:
                        continue

        # Remove duplicates while preserving order
        seen: set = set()
        unique_candidates: List[Path] = []
        for candidate in candidates:
            try:
                key = candidate.resolve()
            except Exception:
                key = candidate
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)

        for candidate in unique_candidates:
            try:
                if candidate.exists():
                    return candidate
            except Exception:
                continue

        return primary

    def _copy_asset_file(
        self,
        asset_type: str,
        filename: str,
        source_dir: Path,
        destination_dir: Path,
        metadata: Optional[Dict[str, object]] = None,
    ) -> bool:
        """Copy a sync asset (PDF or HTML snapshot) from source to destination."""
        source_path = self._resolve_asset_source_path(
            asset_type, filename, source_dir, metadata
        )
        if not source_path.exists():
            if self.app:
                self.app._add_log(
                    "sync_asset_missing",
                    f"Source {asset_type} '{filename}' not found at {source_path}",
                )
            return False

        destination_path = destination_dir / filename
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        return True

    def _repair_missing_assets(self, asset_type: str, result: SyncResult) -> None:
        """Repair missing assets by copying them from remote when referenced."""
        if asset_type == "pdf":
            self.local_pdf_dir.mkdir(parents=True, exist_ok=True)
            self.remote_pdf_dir.mkdir(parents=True, exist_ok=True)

            remote_assets = self._build_pdf_map(
                self.remote_db_path, self.remote_pdf_dir
            )

            for filename, remote_info in remote_assets.items():
                destination_path = self.local_pdf_dir / filename
                if destination_path.exists():
                    continue

                if not self._copy_asset_file(
                    "pdf",
                    filename,
                    self.remote_pdf_dir,
                    self.local_pdf_dir,
                    remote_info,
                ):
                    continue

                result.changes_applied["pdfs_copied"] += 1
                result.detailed_changes["pdfs_copied"].append(
                    f"'{filename}' (recovered from remote)"
                )

                if self.app:
                    self.app._add_log(
                        "sync_pdf_repair",
                        f"Recovered missing PDF from remote: {filename}",
                    )

            return

        if asset_type == "html_snapshot":
            self.local_html_snapshots_dir.mkdir(parents=True, exist_ok=True)
            self.remote_html_snapshots_dir.mkdir(parents=True, exist_ok=True)

            remote_assets = self._build_html_snapshot_map(
                self.remote_db_path, self.remote_html_snapshots_dir
            )

            for filename, remote_info in remote_assets.items():
                destination_path = self.local_html_snapshots_dir / filename
                if destination_path.exists():
                    continue

                if not self._copy_asset_file(
                    "html_snapshot",
                    filename,
                    self.remote_html_snapshots_dir,
                    self.local_html_snapshots_dir,
                    remote_info,
                ):
                    continue

                self._handle_post_copy(
                    "html_snapshot",
                    remote_info,
                    self.local_db_path,
                    filename,
                    self.local_html_snapshots_dir,
                )

                result.changes_applied["html_snapshots_copied"] += 1
                result.detailed_changes["html_snapshots_copied"].append(
                    f"'{filename}' (recovered from remote)"
                )

                if self.app:
                    self.app._add_log(
                        "sync_html_snapshot_repair",
                        f"Recovered missing HTML snapshot from remote: {filename}",
                    )

            return

    def _map_paper_title(self, original_title: str) -> str:
        """Map paper title to its new title if it was renamed during keep_both resolution."""
        return self.title_mappings.get(original_title, original_title)

    def _sync_collections_by_timestamp(self, result: SyncResult):
        """Sync collections automatically using latest timestamp, exact name match only."""
        if self.app:
            self.app._add_log(
                "sync_collections_start", "Starting collection synchronization"
            )

        local_collections = self._get_collections_dict(self.local_db_path)
        remote_collections = self._get_collections_dict(self.remote_db_path)

        if self.app:
            local_text = _pluralizer.pluralize(
                "local collection", len(local_collections), True
            )
            remote_text = _pluralizer.pluralize(
                "remote collection", len(remote_collections), True
            )
            self.app._add_log(
                "sync_collections_info",
                f"Found {local_text}, {remote_text}",
            )

        # Create exact name-based lookups
        local_by_name = {
            col_data["name"]: (col_id, col_data)
            for col_id, col_data in local_collections.items()
        }
        remote_by_name = {
            col_data["name"]: (col_id, col_data)
            for col_id, col_data in remote_collections.items()
        }

        # Collections only in local - copy to remote
        for name in local_by_name.keys() - remote_by_name.keys():
            local_id, local_data = local_by_name[name]
            local_papers = self._get_collection_papers(self.local_db_path, local_id)
            self._copy_collection_to_remote(local_data, local_id)
            result.changes_applied["collections_added"] += 1
            result.detailed_changes["collections_added"].append(f"'{name}'")
            if self.app:
                paper_count = len(local_papers)
                self.app._add_log(
                    "sync_collections",
                    f"Added collection to remote: '{name}' with {_pluralizer.pluralize('paper', paper_count, True)}",
                )

        # Collections only in remote - copy to local
        for name in remote_by_name.keys() - local_by_name.keys():
            remote_id, remote_data = remote_by_name[name]
            remote_papers = self._get_collection_papers(self.remote_db_path, remote_id)
            self._copy_collection_to_local(remote_data, remote_id)
            result.changes_applied["collections_added"] += 1
            result.detailed_changes["collections_added"].append(
                f"'{name}' (from remote)"
            )
            if self.app:
                paper_count = len(remote_papers)
                self.app._add_log(
                    "sync_collections",
                    f"Added collection from remote: '{name}' with {_pluralizer.pluralize('paper', paper_count, True)}",
                )

        # Collections in both - resolve differences
        for name in local_by_name.keys() & remote_by_name.keys():
            local_id, local_data = local_by_name[name]
            remote_id, remote_data = remote_by_name[name]

            # Get papers in each collection
            local_papers = self._get_collection_papers(self.local_db_path, local_id)
            remote_papers = self._get_collection_papers(self.remote_db_path, remote_id)

            local_titles = set(local_papers.keys())
            remote_titles = set(remote_papers.keys())

            if local_titles != remote_titles:
                # Collections differ - merge union and include any "keep both" versions
                all_titles = local_titles | remote_titles  # Union of both sets

                # Check for any "keep both" papers that should be included
                # Look for papers with " (Remote Version)" suffix that correspond to papers in this collection
                keep_both_titles = set()
                for paper_title in list(all_titles):
                    # Check if there's a "Remote Version" of this paper that should be included
                    if paper_title in self.title_mappings:
                        remote_version_title = self.title_mappings[paper_title]
                        keep_both_titles.add(remote_version_title)
                    # Also check reverse mapping - if this is a remote version, include the original
                    elif paper_title.endswith(" (Remote Version)"):
                        original_title = paper_title.replace(" (Remote Version)", "")
                        if original_title in all_titles or self._paper_exists_in_db(
                            self.local_db_path, original_title
                        ):
                            keep_both_titles.add(original_title)

                # Add all keep_both papers to the collection
                all_titles = all_titles | keep_both_titles

                # Update both local and remote with the merged set
                self._replace_collection_in_local(local_data, all_titles)
                self._replace_collection_in_remote(local_data, all_titles)

                result.changes_applied["collections_updated"] += 1
                result.detailed_changes["collections_updated"].append(
                    f"'{name}' (merged local and remote)"
                )
                if self.app:
                    local_count = len(local_papers)
                    remote_count = len(remote_papers)
                    merged_count = len(all_titles)
                    keep_both_count = len(keep_both_titles)
                    self.app._add_log(
                        "sync_collections",
                        (
                            "Merged collection '"
                            + name
                            + "': "
                            + "local ("
                            + str(local_count)
                            + ") + "
                            + "remote ("
                            + str(remote_count)
                            + ") + "
                            + "keep_both ("
                            + str(keep_both_count)
                            + ") = "
                            + _pluralizer.pluralize("paper", merged_count, True)
                            + " total"
                        ),
                    )

    # Helper methods
    def _paper_exists_in_db(self, db_path: Path, title: str) -> bool:
        """Check if a paper with given title exists in the database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT 1 FROM papers WHERE title = ? LIMIT 1", (title,))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def _sync_uuids(self):
        """
        Synchronize UUIDs between local and remote databases.

        Strategy (two-phase approach to avoid conflicts):
        1. Match papers by title and determine target UUIDs
        2. First pass: Clear conflicting UUIDs using temporary values
        3. Second pass: Set all papers to their target UUIDs
        """
        local_conn = sqlite3.connect(self.local_db_path)
        local_conn.row_factory = sqlite3.Row
        local_cursor = local_conn.cursor()

        remote_conn = sqlite3.connect(self.remote_db_path)
        remote_conn.row_factory = sqlite3.Row
        remote_cursor = remote_conn.cursor()

        try:
            # Get all papers from both databases
            local_cursor.execute("SELECT id, title, uuid FROM papers")
            local_papers = {
                row["title"]: (row["id"], row["uuid"])
                for row in local_cursor.fetchall()
            }

            remote_cursor.execute("SELECT id, title, uuid FROM papers")
            remote_papers = {
                row["title"]: (row["id"], row["uuid"])
                for row in remote_cursor.fetchall()
            }

            # Phase 1: Determine target UUIDs for all papers
            local_updates = {}  # paper_id -> target_uuid
            remote_updates = {}  # paper_id -> target_uuid
            synced_count = 0

            # Process papers that exist in both databases
            for title in local_papers.keys():
                if title in remote_papers:
                    local_id, local_uuid = local_papers[title]
                    remote_id, remote_uuid = remote_papers[title]

                    # Determine which UUID to use
                    if local_uuid and remote_uuid:
                        # Both have UUIDs - use local as source of truth
                        if local_uuid != remote_uuid:
                            remote_updates[remote_id] = local_uuid
                            synced_count += 1
                    elif local_uuid and not remote_uuid:
                        # Only local has UUID - copy to remote
                        remote_updates[remote_id] = local_uuid
                        synced_count += 1
                    elif not local_uuid and remote_uuid:
                        # Only remote has UUID - copy to local
                        local_updates[local_id] = remote_uuid
                        synced_count += 1
                    elif not local_uuid and not remote_uuid:
                        # Neither has UUID - generate new one and set both
                        new_uuid = str(uuid.uuid4())
                        local_updates[local_id] = new_uuid
                        remote_updates[remote_id] = new_uuid
                        synced_count += 1

            # Handle papers only in local (generate UUID if needed)
            for title, (local_id, local_uuid) in local_papers.items():
                if title not in remote_papers and not local_uuid:
                    local_updates[local_id] = str(uuid.uuid4())

            # Handle papers only in remote (generate UUID if needed)
            for title, (remote_id, remote_uuid) in remote_papers.items():
                if title not in local_papers and not remote_uuid:
                    remote_updates[remote_id] = str(uuid.uuid4())

            # Phase 2: Clear conflicting UUIDs by setting them to temporary values
            # Collect all target UUIDs to avoid conflicts
            target_uuids = set(local_updates.values()) | set(remote_updates.values())

            # Generate safe temporary UUIDs (guaranteed not to conflict with targets)
            def generate_safe_temp_uuid():
                while True:
                    temp = str(uuid.uuid4())
                    if temp not in target_uuids:
                        return temp

            # Clear conflicting UUIDs in local database
            for paper_id, target_uuid in local_updates.items():
                # Check if another paper already has this UUID
                local_cursor.execute(
                    "SELECT id FROM papers WHERE uuid = ? AND id != ?",
                    (target_uuid, paper_id),
                )
                if local_cursor.fetchone():
                    # Set conflicting paper to temporary UUID
                    temp_uuid = generate_safe_temp_uuid()
                    local_cursor.execute(
                        "UPDATE papers SET uuid = ? WHERE uuid = ? AND id != ?",
                        (temp_uuid, target_uuid, paper_id),
                    )

            # Clear conflicting UUIDs in remote database
            for paper_id, target_uuid in remote_updates.items():
                # Check if another paper already has this UUID
                remote_cursor.execute(
                    "SELECT id FROM papers WHERE uuid = ? AND id != ?",
                    (target_uuid, paper_id),
                )
                if remote_cursor.fetchone():
                    # Set conflicting paper to temporary UUID
                    temp_uuid = generate_safe_temp_uuid()
                    remote_cursor.execute(
                        "UPDATE papers SET uuid = ? WHERE uuid = ? AND id != ?",
                        (temp_uuid, target_uuid, paper_id),
                    )

            # Commit conflict resolution
            local_conn.commit()
            remote_conn.commit()

            # Phase 3: Apply all UUID updates
            for paper_id, target_uuid in local_updates.items():
                local_cursor.execute(
                    "UPDATE papers SET uuid = ? WHERE id = ?",
                    (target_uuid, paper_id),
                )

            for paper_id, target_uuid in remote_updates.items():
                remote_cursor.execute(
                    "UPDATE papers SET uuid = ? WHERE id = ?",
                    (target_uuid, paper_id),
                )

            local_conn.commit()
            remote_conn.commit()

            if self.app and synced_count > 0:
                self.app._add_log(
                    "sync_uuid", f"Synchronized UUIDs for {synced_count} papers"
                )

        finally:
            local_conn.close()
            remote_conn.close()

    def _get_papers_dict(self, db_path: Path) -> Dict[str, Dict]:
        """Get papers from database as a dictionary keyed by UUID."""
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
                paper_dict = dict(row)
                # Use UUID as the key, fall back to title for old databases
                key = paper_dict.get("uuid") or paper_dict.get("title")
                papers[key] = paper_dict
        finally:
            conn.close()
        return papers

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

    def _get_collection_papers(
        self, db_path: Path, collection_id: int
    ) -> Dict[str, Optional[str]]:
        """Get mapping of paper titles to UUIDs (when available) for a collection."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            has_uuid = self._database_has_uuid_column(db_path)
            if has_uuid:
                cursor.execute(
                    """
                    SELECT p.title, p.uuid
                    FROM papers p
                    JOIN paper_collections pc ON p.id = pc.paper_id
                    WHERE pc.collection_id = ?
                    """,
                    (collection_id,),
                )
                rows = cursor.fetchall()
                return {title: uuid for title, uuid in rows}

            cursor.execute(
                """
                SELECT p.title
                FROM papers p
                JOIN paper_collections pc ON p.id = pc.paper_id
                WHERE pc.collection_id = ?
                """,
                (collection_id,),
            )
            rows = cursor.fetchall()
            return {title: None for (title,) in rows}
        finally:
            conn.close()

    def _papers_differ(self, local_paper: Dict, remote_paper: Dict) -> bool:
        """Check if two paper records differ in significant ways."""
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
            # Include PDF path so filename changes propagate during sync
            "pdf_path",
        ]

        for field in compare_fields:
            local_val = local_paper.get(field)
            remote_val = remote_paper.get(field)
            if not local_val and not remote_val:
                continue
            if local_val != remote_val:
                return True

        # Check authors
        local_authors = local_paper.get("authors", "")
        remote_authors = remote_paper.get("authors", "")
        if local_authors != remote_authors:
            return True

        return False

    def _get_file_info(self, file_path: Path) -> Dict:
        """Get file information including hash, size, and modification time."""
        if not file_path.exists():
            return {}

        stat = file_path.stat()
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        return {
            "hash": file_hash,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "path": str(file_path),
        }

    def _count_papers(self, db_path: Path) -> int:
        """Count papers in database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM papers")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _sync_pdfs_to_remote(self, result: SyncResult):
        """Copy PDFs from local to remote."""
        if not self.local_pdf_dir.exists():
            return

        for pdf_file in self.local_pdf_dir.glob("*.pdf"):
            remote_pdf = self.remote_pdf_dir / pdf_file.name
            if not remote_pdf.exists():
                shutil.copy2(pdf_file, remote_pdf)
                result.changes_applied["pdfs_copied"] += 1

    def _copy_paper_to_local(self, paper_data: Dict):
        """Copy a paper from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        try:
            paper_dict = dict(paper_data)
            if "added_date" not in paper_dict or not paper_dict["added_date"]:
                paper_dict["added_date"] = datetime.now().isoformat()
            if "modified_date" not in paper_dict or not paper_dict["modified_date"]:
                paper_dict["modified_date"] = datetime.now().isoformat()

            # Get available columns in target database
            cursor.execute("PRAGMA table_info(papers)")
            available_columns = {row[1] for row in cursor.fetchall()}

            # Generate UUID if target has uuid column but paper doesn't have one
            if "uuid" in available_columns and not paper_dict.get("uuid"):
                paper_dict["uuid"] = str(uuid.uuid4())

            # Check if paper with this UUID already exists
            if "uuid" in available_columns and paper_dict.get("uuid"):
                cursor.execute("SELECT id FROM papers WHERE uuid = ?", (paper_dict["uuid"],))
                existing = cursor.fetchone()
                if existing:
                    # Paper with this UUID already exists, skip insertion
                    return existing[0]

            # Insert paper (excluding id and authors, filtering None values, and checking column existence)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if (
                    field not in ["id", "authors"]
                    and value is not None
                    and field in available_columns
                ):
                    filtered_fields.append(field)
                    filtered_values.append(value)

            placeholders = ", ".join(["?"] * len(filtered_fields))
            field_names = ", ".join(filtered_fields)

            cursor.execute(
                f"INSERT INTO papers ({field_names}) VALUES ({placeholders})",
                filtered_values,
            )
            new_paper_id = cursor.lastrowid

            # Handle authors
            if "authors" in paper_data and paper_data["authors"]:
                author_names = (
                    paper_data["authors"].split(",") if paper_data["authors"] else []
                )
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        cursor.execute(
                            "INSERT OR IGNORE INTO authors (full_name) VALUES (?)",
                            (author_name,),
                        )
                        cursor.execute(
                            "SELECT id FROM authors WHERE full_name = ?", (author_name,)
                        )
                        author_id = cursor.fetchone()[0]
                        cursor.execute(
                            "INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                            (new_paper_id, author_id, i),
                        )

            conn.commit()
            return new_paper_id
        finally:
            conn.close()

    def _copy_paper_to_remote(self, paper_data: Dict):
        """Copy a paper from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()
        try:
            paper_dict = dict(paper_data)
            if "added_date" not in paper_dict or not paper_dict["added_date"]:
                paper_dict["added_date"] = datetime.now().isoformat()
            if "modified_date" not in paper_dict or not paper_dict["modified_date"]:
                paper_dict["modified_date"] = datetime.now().isoformat()

            # Get available columns in target database
            cursor.execute("PRAGMA table_info(papers)")
            available_columns = {row[1] for row in cursor.fetchall()}

            # Generate UUID if target has uuid column but paper doesn't have one
            if "uuid" in available_columns and not paper_dict.get("uuid"):
                paper_dict["uuid"] = str(uuid.uuid4())

            # Check if paper with this UUID already exists
            if "uuid" in available_columns and paper_dict.get("uuid"):
                cursor.execute("SELECT id FROM papers WHERE uuid = ?", (paper_dict["uuid"],))
                existing = cursor.fetchone()
                if existing:
                    # Paper with this UUID already exists, skip insertion
                    return existing[0]

            # Insert paper (excluding id and authors, filtering None values, and checking column existence)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if (
                    field not in ["id", "authors"]
                    and value is not None
                    and field in available_columns
                ):
                    filtered_fields.append(field)
                    filtered_values.append(value)

            placeholders = ", ".join(["?"] * len(filtered_fields))
            field_names = ", ".join(filtered_fields)

            cursor.execute(
                f"INSERT INTO papers ({field_names}) VALUES ({placeholders})",
                filtered_values,
            )
            new_paper_id = cursor.lastrowid

            # Handle authors
            if "authors" in paper_data and paper_data["authors"]:
                author_names = (
                    paper_data["authors"].split(",") if paper_data["authors"] else []
                )
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        cursor.execute(
                            "INSERT OR IGNORE INTO authors (full_name) VALUES (?)",
                            (author_name,),
                        )
                        cursor.execute(
                            "SELECT id FROM authors WHERE full_name = ?", (author_name,)
                        )
                        author_id = cursor.fetchone()[0]
                        cursor.execute(
                            "INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                            (new_paper_id, author_id, i),
                        )

            conn.commit()
            return new_paper_id
        finally:
            conn.close()

    def _delete_paper_by_title(self, db_path: Path, title: str):
        """Delete a paper from database by its title."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM papers WHERE title = ?", (title,))
            paper = cursor.fetchone()
            if paper:
                paper_id = paper[0]
                cursor.execute(
                    "DELETE FROM paper_authors WHERE paper_id = ?", (paper_id,)
                )
                cursor.execute(
                    "DELETE FROM paper_collections WHERE paper_id = ?", (paper_id,)
                )
                cursor.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                conn.commit()
        finally:
            conn.close()

    def _delete_collection_by_name(self, db_path: Path, name: str):
        """Delete a collection by name, including relationships."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM collections WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                collection_id = row[0]
                cursor.execute(
                    "DELETE FROM paper_collections WHERE collection_id = ?",
                    (collection_id,),
                )
                cursor.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
                conn.commit()
        finally:
            conn.close()

    def _copy_collection_to_local(
        self, collection_data: Dict, remote_collection_id: int
    ):
        """Copy a collection from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        try:
            created_at = collection_data.get("created_at") or datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO collections (name, description, created_at, last_modified) VALUES (?, ?, ?, ?)",
                (
                    collection_data["name"],
                    collection_data.get("description", ""),
                    created_at,
                    collection_data.get("last_modified"),
                ),
            )
            new_collection_id = cursor.lastrowid

            # Copy paper relationships
            remote_papers = self._get_collection_papers(
                self.remote_db_path, remote_collection_id
            )
            for paper_title, paper_uuid in remote_papers.items():
                linked = self._link_paper_to_collection(
                    cursor,
                    self.local_db_path,
                    new_collection_id,
                    paper_title,
                    paper_uuid,
                )
                if not linked and self.app:
                    self.app._add_log(
                        "sync_collections_warning",
                        f"Could not link paper '{paper_title}' to local collection '{collection_data['name']}'",
                    )

            conn.commit()
            return new_collection_id
        finally:
            conn.close()

    def _copy_collection_to_remote(
        self, collection_data: Dict, local_collection_id: int
    ):
        """Copy a collection from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()
        try:
            created_at = collection_data.get("created_at") or datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO collections (name, description, created_at, last_modified) VALUES (?, ?, ?, ?)",
                (
                    collection_data["name"],
                    collection_data.get("description", ""),
                    created_at,
                    collection_data.get("last_modified"),
                ),
            )
            new_collection_id = cursor.lastrowid

            # Copy paper relationships
            local_papers = self._get_collection_papers(
                self.local_db_path, local_collection_id
            )
            for paper_title, paper_uuid in local_papers.items():
                linked = self._link_paper_to_collection(
                    cursor,
                    self.remote_db_path,
                    new_collection_id,
                    paper_title,
                    paper_uuid,
                )
                if not linked and self.app:
                    self.app._add_log(
                        "sync_collections_warning",
                        f"Could not link paper '{paper_title}' to remote collection '{collection_data['name']}'",
                    )

            conn.commit()
            return new_collection_id
        finally:
            conn.close()

    def _is_local_collection_newer(self, local_modified, remote_modified):
        """Compare collection timestamps and return True if local is newer or same."""
        if not local_modified and not remote_modified:
            return True
        if local_modified and not remote_modified:
            return True
        if not local_modified and remote_modified:
            return False

        try:
            local_dt = (
                datetime.fromisoformat(local_modified)
                if isinstance(local_modified, str)
                else local_modified
            )
            remote_dt = (
                datetime.fromisoformat(remote_modified)
                if isinstance(remote_modified, str)
                else remote_modified
            )
            return local_dt >= remote_dt
        except (ValueError, TypeError):
            return True

    def _replace_collection_in_remote(self, local_collection_data, local_papers):
        """Replace remote collection with local version."""
        collection_name = local_collection_data["name"]
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()
        try:
            # Get the collection ID to delete paper relationships first
            cursor.execute(
                "SELECT id FROM collections WHERE name = ?", (collection_name,)
            )
            collection_row = cursor.fetchone()
            if collection_row:
                collection_id = collection_row[0]
                cursor.execute(
                    "DELETE FROM paper_collections WHERE collection_id = ?",
                    (collection_id,),
                )

            cursor.execute("DELETE FROM collections WHERE name = ?", (collection_name,))
            cursor.execute(
                "INSERT INTO collections (name, description, created_at, last_modified) VALUES (?, ?, ?, ?)",
                (
                    local_collection_data["name"],
                    local_collection_data.get("description", ""),
                    local_collection_data.get("created_at"),
                    local_collection_data.get("last_modified"),
                ),
            )
            new_collection_id = cursor.lastrowid

            for paper_title in local_papers:
                linked = self._link_paper_to_collection(
                    cursor,
                    self.remote_db_path,
                    new_collection_id,
                    paper_title,
                )
                if not linked and self.app:
                    self.app._add_log(
                        "sync_collections_warning",
                        f"Could not link paper '{paper_title}' while updating remote collection '{collection_name}'",
                    )
            conn.commit()
        finally:
            conn.close()

    def _replace_collection_in_local(self, remote_collection_data, remote_papers):
        """Replace local collection with remote version."""
        collection_name = remote_collection_data["name"]
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        try:
            # Get the collection ID to delete paper relationships first
            cursor.execute(
                "SELECT id FROM collections WHERE name = ?", (collection_name,)
            )
            collection_row = cursor.fetchone()
            if collection_row:
                collection_id = collection_row[0]
                cursor.execute(
                    "DELETE FROM paper_collections WHERE collection_id = ?",
                    (collection_id,),
                )

            cursor.execute("DELETE FROM collections WHERE name = ?", (collection_name,))
            cursor.execute(
                "INSERT INTO collections (name, description, created_at, last_modified) VALUES (?, ?, ?, ?)",
                (
                    remote_collection_data["name"],
                    remote_collection_data.get("description", ""),
                    remote_collection_data.get("created_at"),
                    remote_collection_data.get("last_modified"),
                ),
            )
            new_collection_id = cursor.lastrowid

            for paper_title in remote_papers:
                linked = self._link_paper_to_collection(
                    cursor,
                    self.local_db_path,
                    new_collection_id,
                    paper_title,
                )
                if not linked and self.app:
                    self.app._add_log(
                        "sync_collections_warning",
                        f"Could not link paper '{paper_title}' while updating local collection '{collection_name}'",
                    )
            conn.commit()
        finally:
            conn.close()

    # ---- Generic DB lookup helpers ----
    def _collection_id_by_name(self, db_path: Path, name: str) -> Optional[int]:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT id FROM collections WHERE name = ?", (name,))
            row = cur.fetchone()
            return int(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _paper_id_by_title(self, db_path: Path, title: str) -> Optional[int]:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT id FROM papers WHERE title = ?", (title,))
            row = cur.fetchone()
            return int(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _paper_title_by_id(self, db_path: Path, paper_id: int) -> Optional[str]:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT title FROM papers WHERE id = ?", (paper_id,))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _collection_name_by_id(
        self, db_path: Path, collection_id: int
    ) -> Optional[str]:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM collections WHERE id = ?", (collection_id,))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---- Remote collection membership helpers ----
    def _remote_collection_remove_titles(self, name: str, titles: List[str]) -> None:
        col_id = self._collection_id_by_name(self.remote_db_path, name)
        if col_id is None:
            return
        conn = sqlite3.connect(self.remote_db_path)
        try:
            cur = conn.cursor()
            for title in titles:
                pid = self._paper_id_by_title(self.remote_db_path, title)
                if pid is not None:
                    cur.execute(
                        "DELETE FROM paper_collections WHERE paper_id = ? AND collection_id = ?",
                        (pid, col_id),
                    )
            conn.commit()
        finally:
            conn.close()

    def _remote_collection_add_titles(self, name: str, titles: List[str]) -> None:
        col_id = self._collection_id_by_name(self.remote_db_path, name)
        if col_id is None:
            return
        conn = sqlite3.connect(self.remote_db_path)
        try:
            cur = conn.cursor()
            for title in titles:
                pid = self._paper_id_by_title(self.remote_db_path, title)
                if pid is not None:
                    cur.execute(
                        "INSERT OR IGNORE INTO paper_collections (paper_id, collection_id) VALUES (?, ?)",
                        (pid, col_id),
                    )
            conn.commit()
        finally:
            conn.close()

    def _fix_absolute_pdf_paths(self):
        """Fix absolute PDF paths to relative paths before sync."""
        try:
            db_health = DatabaseHealthService(app=self.app)
            fixed = db_health.fix_absolute_pdf_paths()
            if self.app and fixed["pdf_paths"] > 0:
                count = fixed["pdf_paths"]
                self.app._add_log(
                    "sync_prep",
                    f"Fixed {_pluralizer.pluralize('absolute PDF path', count, True)} to relative",
                )
        except Exception as e:
            if self.app:
                self.app._add_log(
                    "sync_prep_error", f"Failed to fix PDF paths: {str(e)}"
                )

    def _upgrade_database_schema(self, db_path: Path) -> bool:
        """Upgrade database schema using Alembic migrations. Returns True if successful."""
        try:
            # Try to find alembic.ini
            alembic_ini_path = "alembic.ini"
            alembic_dir = "alembic"

            if not os.path.exists(alembic_ini_path):
                # Look for it relative to the ng package
                ng_path = Path(ng.__file__).parent
                alembic_ini_path = ng_path / "alembic.ini"
                alembic_dir = ng_path / "alembic"

                if not alembic_ini_path.exists():
                    # Alembic not available, skip upgrade
                    return False

            alembic_cfg = Config(str(alembic_ini_path))
            alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
            alembic_cfg.set_main_option("script_location", str(alembic_dir))

            # Check current database revision
            engine = create_engine(f"sqlite:///{db_path}")
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current_rev = context.get_current_revision()

            # Get the head revision from scripts
            script = ScriptDirectory.from_config(alembic_cfg)
            head_rev = script.get_current_head()

            # Only upgrade if versions differ
            if current_rev == head_rev:
                # Already at latest version, skip
                return True

            # Check if schema is already correct but alembic version is wrong
            # (This can happen if migration was run manually or interrupted)
            if self._database_has_uuid_column(db_path) and head_rev == "10f8534b9062":
                # UUID column exists, just update alembic version
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "UPDATE alembic_version SET version_num = ?", (head_rev,)
                    )
                    conn.commit()
                    if self.app:
                        self.app._add_log(
                            "sync_db_fix",
                            f"Fixed alembic version for {db_path.name} (schema already correct)",
                        )
                    return True
                finally:
                    conn.close()

            if self.app:
                self.app._add_log(
                    "sync_db_upgrade",
                    f"Upgrading database schema: {db_path.name} from {current_rev or 'base'} to {head_rev}",
                )

            # Run upgrade to head
            command.upgrade(alembic_cfg, "head")

            if self.app:
                self.app._add_log(
                    "sync_db_upgrade_success",
                    f"Successfully upgraded database schema: {db_path.name}",
                )
            return True
        except Exception as e:
            # Log error but don't fail sync - will try manual fallback
            if self.app:
                self.app._add_log(
                    "sync_db_upgrade_failed",
                    f"Alembic upgrade failed for {db_path.name}: {str(e)}",
                )
            return False
