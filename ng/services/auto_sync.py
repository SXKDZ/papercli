from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ng.services import SyncService
from pluralizer import Pluralizer


class AutoSyncService:
    """Background auto-sync worker with a simple operation queue.

    - When enabled (PAPERCLI_AUTO_SYNC=true) and a remote path is set,
      a background thread wakes up every N seconds (default 5) and, if there
      are pending operations, performs a sync using SyncService.
    - All conflicts are resolved in favor of local changes during auto-sync.
    - The queue stores atomic operation markers for observability; we use it
      as a trigger to run sync and clear it on success.
    """

    def __init__(self, app):
        self.app = app
        self._ops_lock = threading.Lock()
        self._ops: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._interval_seconds = self._read_interval()
        self._pluralizer = Pluralizer()

    # Public API
    def enqueue(self, op: Dict[str, Any] | None = None) -> None:
        """Enqueue an operation marker and wake the worker."""
        with self._ops_lock:
            self._ops.append(op or {"type": "db_change"})
        if isinstance(op, dict):
            res = op.get("resource", op.get("type", "unknown"))
            action = op.get("op", "change")
            self.app._add_log(
                "auto_sync_enqueue",
                f"Queued auto-sync op: {res}::{action}",
            )
        else:
            self.app._add_log("auto_sync_enqueue", "Queued auto-sync op")
        self._wake_event.set()

    def start_if_enabled(self) -> None:
        """Start the worker thread if auto-sync is enabled in config."""
        if not self._should_run():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._interval_seconds = self._read_interval()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()
        self.app._add_log(
            "auto_sync_start",
            f"Auto-sync started (every {self._interval_seconds}s)",
        )

    def stop(self) -> None:
        """Stop the worker thread."""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._wake_event.set()
            self._thread.join(timeout=0.5)
            self.app._add_log("auto_sync_stop", "Auto-sync stopped")

    def on_config_changed(self, changes: Dict[str, str]) -> None:
        """React to relevant config changes and (re)configure the worker."""
        relevant_keys = {
            "PAPERCLI_AUTO_SYNC",
            "PAPERCLI_REMOTE_PATH",
            "PAPERCLI_AUTO_SYNC_INTERVAL",
        }
        if not (set(changes.keys()) & relevant_keys):
            return

        # Update interval if changed
        self._interval_seconds = self._read_interval()

        # Decide whether to (re)start or stop
        if self._should_run():
            if self._thread and self._thread.is_alive():
                # Wake the thread to apply interval sooner
                self._wake_event.set()
                self.app._add_log(
                    "auto_sync_reconfig",
                    f"Auto-sync reconfigured (every {self._interval_seconds}s)",
                )
            else:
                self.start_if_enabled()
        else:
            self.stop()

    # Internals
    def _should_run(self) -> bool:
        def _truthy(val: str) -> bool:
            v = (val or "").strip().strip("'\"").lower()
            return v in {"1", "true", "yes", "on"}

        enabled = _truthy(os.getenv("PAPERCLI_AUTO_SYNC", "false"))
        remote = (os.getenv("PAPERCLI_REMOTE_PATH", "") or "").strip().strip("'\"")
        return enabled and bool(remote)

    def _read_interval(self) -> int:
        try:
            raw = (
                (os.getenv("PAPERCLI_AUTO_SYNC_INTERVAL", "5") or "")
                .strip()
                .strip("'\"")
            )
            return max(1, int(raw))
        except Exception:
            return 5

    def _resolve_conflicts_local(self, conflicts) -> Dict[str, str]:
        """Resolve all conflicts in favor of local changes."""
        resolutions: Dict[str, str] = {}
        for c in conflicts:
            conflict_id = (
                f"{getattr(c, 'conflict_type', 'item')}_{getattr(c, 'item_id', '')}"
            )
            resolutions[conflict_id] = "local"
        return resolutions

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            # Wait for interval or until we are explicitly woken up
            self._wake_event.wait(timeout=self._interval_seconds)
            self._wake_event.clear()

            if self._stop_event.is_set():
                break

            # Quick checks
            if not self._should_run():
                # If disabled mid-flight, keep sleeping
                continue

            # Snapshot and clear ops
            with self._ops_lock:
                pending_ops = list(self._ops)
                self._ops.clear()

            if pending_ops:
                summary: Dict[str, int] = {}
                for op in pending_ops:
                    if isinstance(op, dict):
                        key = (
                            f"{op.get('resource', 'unknown')}::{op.get('op', 'change')}"
                        )
                    else:
                        key = "unknown::change"
                    summary[key] = summary.get(key, 0) + 1
                parts = [f"{k} x{v}" for k, v in summary.items()]
                self.app._add_log(
                    "auto_sync_queue", f"Processing ops: {'; '.join(parts)}"
                )

            if not pending_ops:
                # Nothing to do this tick
                continue

            try:
                local_data_dir = Path(self.app.db_path).parent
                remote_path = Path(
                    os.path.expanduser(os.getenv("PAPERCLI_REMOTE_PATH", "").strip())
                )

                # If there are placeholder PDF entries still extracting metadata, skip syncing
                if self._has_pending_metadata_extractions(local_data_dir / "papers.db"):
                    with self._ops_lock:
                        # Put the ops back to try again later
                        self._ops = pending_ops + self._ops
                    count = self._count_pending_metadata(local_data_dir / "papers.db")
                    text = self._pluralizer.pluralize("placeholder PDF", count, True)
                    self.app._add_log(
                        "auto_sync_skip", f"Skipping auto-sync while {text} pending"
                    )
                    continue

                count = len(pending_ops)
                item_text = self._pluralizer.pluralize("change", count, True)
                self.app._add_log(
                    "auto_sync_tick",
                    f"Auto-sync: processing {item_text}",
                )

                sync_service = SyncService(
                    local_data_dir=str(local_data_dir),
                    remote_data_dir=str(remote_path),
                    app=self.app,
                )

                # Pre-apply intent-aware deletes on remote for papers
                self._apply_intended_remote_deletes(sync_service, pending_ops)

                # Run sync with local-wins resolution strategy
                result = sync_service.sync(
                    conflict_resolver=lambda conflicts: self._resolve_conflicts_local(
                        conflicts
                    ),
                    auto_sync_mode=True,
                )

                # Lightweight UI refresh if any changes pulled from remote
                if result and not result.cancelled:
                    self.app.call_from_thread(self.app.load_papers)

            except Exception as e:
                # Re-queue operations for retry and log error
                with self._ops_lock:
                    self._ops = pending_ops + self._ops
                self.app._add_log("auto_sync_error", f"Auto-sync failed: {e}")

    def _has_pending_metadata_extractions(self, db_path: Path) -> bool:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(1) FROM papers WHERE title LIKE ?",
                ("%extracting metadata%",),
            )
            count = cursor.fetchone()[0] or 0
            return count > 0
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _count_pending_metadata(self, db_path: Path) -> int:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(1) FROM papers WHERE title LIKE ?",
                ("%extracting metadata%",),
            )
            count = cursor.fetchone()[0] or 0
            return int(count)
        except Exception:
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _apply_intended_remote_deletes(
        self, sync_service: SyncService, pending_ops: List[Dict[str, Any]]
    ):
        """Delete remote entities (papers, collections) intentionally deleted locally.

        We look for paper delete ops ('delete' / 'bulk_delete') and collection delete ops
        and remove those from the remote DB (and PDFs) before running the full sync.
        """
        paper_titles: List[str] = []
        paper_pdf_names: List[Optional[str]] = []
        collection_names: List[str] = []
        # Track intent-level collection membership changes
        coll_remove_items: List[Dict[str, Any]] = []  # {name, titles}
        coll_add_items: List[Dict[str, Any]] = []  # {name, titles}

        for op in pending_ops:
            if not isinstance(op, dict):
                continue
            res = op.get("resource")
            action = op.get("op")
            if res == "paper":
                if action == "delete":
                    t = op.get("title")
                    if t:
                        paper_titles.append(t)
                        paper_pdf_names.append(op.get("pdf_filename"))
                elif action == "bulk_delete":
                    for item in op.get("items", []) or []:
                        if isinstance(item, dict) and item.get("title"):
                            paper_titles.append(item["title"])
                            paper_pdf_names.append(item.get("pdf_filename"))
            elif res == "collection" and action == "delete":
                name = op.get("id") or op.get("name")
                if isinstance(name, str) and name:
                    collection_names.append(name)
            elif res == "collection" and action == "bulk_delete":
                for name in op.get("names", []) or []:
                    if isinstance(name, str) and name:
                        collection_names.append(name)
            elif res == "collection" and action in {"add_papers", "remove_papers"}:
                name = op.get("name")
                ids = op.get("paper_ids") or []
                titles = []
                for pid in ids:
                    try:
                        pid_int = int(pid)
                    except Exception:
                        continue
                    t = sync_service._paper_title_by_id(
                        sync_service.local_db_path, pid_int
                    )
                    if t:
                        titles.append(t)
                if name and titles:
                    if action == "remove_papers":
                        coll_remove_items.append({"name": name, "titles": titles})
                    else:
                        coll_add_items.append({"name": name, "titles": titles})
            elif res == "collection" and action in {"add_paper", "remove_paper"}:
                col_id = op.get("collection_id")
                pap_id = op.get("paper_id")
                if col_id is not None and pap_id is not None:
                    name = sync_service._collection_name_by_id(
                        sync_service.local_db_path, int(col_id)
                    )
                    title = sync_service._paper_title_by_id(
                        sync_service.local_db_path, int(pap_id)
                    )
                    if name and title:
                        item = {"name": name, "titles": [title]}
                        if action == "remove_paper":
                            coll_remove_items.append(item)
                        else:
                            coll_add_items.append(item)

        # Perform paper deletions on remote
        for idx, title in enumerate(paper_titles):
            sync_service._delete_paper_by_title(sync_service.remote_db_path, title)
            pdf_name = paper_pdf_names[idx] if idx < len(paper_pdf_names) else None
            if pdf_name:
                remote_pdf = sync_service.remote_pdf_dir / pdf_name
                if remote_pdf.exists():
                    remote_pdf.unlink()
            if self.app:
                self.app._add_log(
                    "auto_sync_remote_delete", f"Deleted remote paper: '{title}'"
                )

        # Perform collection deletions on remote
        for name in collection_names:
            sync_service._delete_collection_by_name(sync_service.remote_db_path, name)
            self.app._add_log(
                "auto_sync_remote_delete_collection",
                f"Deleted remote collection: '{name}'",
            )

        # Apply intended collection membership changes on remote
        for item in coll_remove_items:
            sync_service._remote_collection_remove_titles(item["name"], item["titles"])
            n = len(item["titles"])
            self.app._add_log(
                "auto_sync_remote_collection",
                f"Removed {self._pluralizer.pluralize('paper', n, True)} from remote collection '{item['name']}'",
            )
        for item in coll_add_items:
            sync_service._remote_collection_add_titles(item["name"], item["titles"])
            n = len(item["titles"])
            self.app._add_log(
                "auto_sync_remote_collection",
                f"Added {self._pluralizer.pluralize('paper', n, True)} to remote collection '{item['name']}'",
            )

    # ---- Helpers for collection membership intents ----
