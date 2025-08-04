"""Auto-sync utility for triggering sync after edits."""

import os

from .sync import SyncService


def trigger_auto_sync(log_callback=None) -> bool:
    """
    Trigger auto-sync if enabled.

    Args:
        log_callback: Optional callback function for logging

    Returns:
        True if sync was attempted (regardless of success), False if auto-sync disabled
    """
    auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
    if not auto_sync:
        return False

    remote_path = os.getenv("PAPERCLI_REMOTE_PATH")
    if not remote_path:
        if log_callback:
            log_callback(
                "auto_sync_skipped", "Auto-sync enabled but no remote path configured"
            )
        return False

    try:
        from ..db.database import get_db_manager

        db_manager = get_db_manager()
        local_path = os.path.dirname(db_manager.db_path)

        sync_service = SyncService(local_path, remote_path)

        def auto_conflict_resolver(conflicts):
            """Automatically resolve conflicts by preferring local versions."""
            if not conflicts:
                return {}

            resolutions = {}
            for conflict in conflicts:
                conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
                resolutions[conflict_id] = "local"  # Always prefer local for auto-sync

            if log_callback:
                log_callback(
                    "auto_sync_conflicts",
                    f"Auto-resolved {len(conflicts)} conflicts by keeping local versions",
                )
            return resolutions

        result = sync_service.sync(conflict_resolver=auto_conflict_resolver)

        if log_callback:
            if result.cancelled:
                log_callback("auto_sync_cancelled", "Auto-sync was cancelled")
            elif result.errors:
                log_callback("auto_sync_error", f"Auto-sync failed: {result.errors[0]}")
            else:
                log_callback("auto_sync_success", result.get_summary())

        return True

    except Exception as e:
        if log_callback:
            log_callback("auto_sync_error", f"Auto-sync failed: {str(e)}")
        return True  # We attempted sync even though it failed
