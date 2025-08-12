"""Auto-sync utility for triggering sync after edits."""

import os

from .sync import SyncService


def trigger_auto_sync(app=None) -> bool:
    """
    Trigger auto-sync if enabled.

    Args:
        app: Optional app instance for logging

    Returns:
        True if sync was attempted (regardless of success), False if auto-sync disabled
    """
    auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
    if not auto_sync:
        return False

    remote_path = os.getenv("PAPERCLI_REMOTE_PATH")
    if not remote_path:
        if app:
            app._add_log(
                "auto_sync_skipped", "Auto-sync enabled but no remote path configured"
            )
        return False

    try:
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        local_path = os.path.dirname(db_manager.db_path)

        sync_service = SyncService(local_path, remote_path, app=app)

        def auto_conflict_resolver(conflicts):
            """Automatically resolve conflicts by preferring local versions."""
            if not conflicts:
                return {}

            resolutions = {}
            for conflict in conflicts:
                conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
                resolutions[conflict_id] = "local"  # Always prefer local for auto-sync

            if app:
                app._add_log(
                    "auto_sync_conflicts",
                    f"Auto-resolved {len(conflicts)} conflicts by preferring local versions",
                )

            return resolutions

        # Perform the sync
        result = sync_service.sync(conflict_resolver=auto_conflict_resolver)

        if app:
            if result.get("success", False):
                app._add_log("auto_sync_success", "Auto-sync completed successfully")
            else:
                error_msg = result.get("error", "Unknown error")
                app._add_log("auto_sync_error", f"Auto-sync failed: {error_msg}")

        return True

    except Exception as e:
        if app:
            app._add_log("auto_sync_exception", f"Auto-sync failed with exception: {e}")
        return True  # We attempted sync, even if it failed
