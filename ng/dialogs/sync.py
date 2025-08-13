import os
import threading
from typing import Callable, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static, TabbedContent, TabPane

from ng.services import SyncConflict, SyncService


class SyncDialog(ModalScreen):
    """A modal dialog for sync progress with conflict resolution."""

    DEFAULT_CSS = """
    SyncDialog {
        align: center middle;
        layer: dialog;
    }
    SyncDialog > Container {
        width: 90%;
        height: 70%;
        max-width: 140;
        max-height: 35;
        border: solid $accent;
        background: $panel;
    }
    SyncDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    SyncDialog #progress-section {
        height: 4;
        padding: 1;
    }
    SyncDialog #progress-bar {
        height: 1;
        margin: 0 1;
    }
    SyncDialog #status-text {
        height: 1;
        text-align: center;
        margin: 1 1 0 1;
    }
    SyncDialog #content-tabs {
        height: 1fr;
        margin: 0 1;
        border: solid $border;
    }
    SyncDialog TabPane {
        padding: 1;
    }
    SyncDialog #conflict-info {
        height: 1fr;
        border: solid $border;
    }
    SyncDialog #detailed-info {
        height: 1fr;
        border: solid $border;
    }
    SyncDialog #conflict-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }
    SyncDialog #main-buttons {
        height: 3;
        align: center middle;
        padding: 0;
    }
    SyncDialog Button {
        margin: 0 1;
        min-width: 12;
        content-align: center middle;
        text-align: center;
    }
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel/Close"),
        ("l", "use_local", "Use Local"),
        ("r", "use_remote", "Use Remote"),
        ("b", "keep_both", "Keep Both"),
        ("shift+l", "all_local", "All Local"),
        ("shift+r", "all_remote", "All Remote"),
        ("shift+a", "all_both", "All Both"),
    ]

    # Reactive variables
    progress_percentage = reactive(0)
    status_text = reactive("Preparing sync...")
    show_conflicts = reactive(False)
    sync_complete = reactive(False)
    conflicts_resolved = reactive(False)

    def __init__(
        self,
        callback: Callable = None,
        local_path: str = "",
        remote_path: str = "",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.callback = callback
        self.local_path = local_path
        self.remote_path = remote_path

        # Sync state
        self.conflicts: List[SyncConflict] = []
        self.current_conflict_index = 0
        self.resolutions: Dict[str, str] = {}
        self.sync_result = None
        self.sync_thread = None
        self.sync_cancelled = False
        self.conflict_resolution_event = threading.Event()

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("Syncing with Remote Database", classes="dialog-title")
            
            # Progress section at top
            with Vertical(id="progress-section"):
                yield ProgressBar(total=100, show_percentage=True, id="progress-bar")
                yield Static("", id="status-text")

            # Content switcher with tabs
            with TabbedContent(id="content-tabs"):
                with TabPane("Sync Progress", id="progress-tab"):
                    yield Static("Sync operations will be shown here.", id="detailed-info")

                with TabPane("Conflict Resolution", id="conflict-tab", disabled=True):
                    yield Static("No conflicts to resolve.", id="conflict-info")

            # Conflict resolution buttons (hidden initially)
            with Horizontal(id="conflict-buttons", classes="hidden"):
                yield Button("Use Local (L)", id="local-button", variant="default")
                yield Button("Use Remote (R)", id="remote-button", variant="default") 
                yield Button("Keep Both (B)", id="keep-both-button", variant="default")
                yield Button("All Local (Shift+L)", id="all-local-button", variant="warning")
                yield Button("All Remote (Shift+R)", id="all-remote-button", variant="warning")
                yield Button("Keep All (Shift+A)", id="all-both-button", variant="success")

            # Main buttons
            with Horizontal(id="main-buttons"):
                yield Button("Cancel", id="cancel-button", variant="error")

    def on_mount(self) -> None:
        """Start sync operation when dialog opens."""
        self.start_sync()

    def watch_progress_percentage(self, percentage: int) -> None:
        """Update progress bar when percentage changes."""
        try:
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(progress=percentage)
        except:
            pass

    def watch_status_text(self, text: str) -> None:
        """Update status text when it changes."""
        try:
            status_widget = self.query_one("#status-text", Static)
            status_widget.update(text)
        except:
            pass

    def watch_show_conflicts(self, show: bool) -> None:
        """Show/hide conflict resolution UI."""
        try:
            if show and self.conflicts:
                # Enable conflict tab
                content_tabs = self.query_one("#content-tabs", TabbedContent)
                conflict_tab = self.query_one("#conflict-tab")
                conflict_tab.disabled = False
                content_tabs.active = "conflict-tab"
                
                # Show conflict buttons
                conflict_buttons = self.query_one("#conflict-buttons")
                conflict_buttons.remove_class("hidden")
                
                # Update conflict info
                self._update_conflict_display()
            else:
                # Hide conflict buttons
                try:
                    conflict_buttons = self.query_one("#conflict-buttons")
                    conflict_buttons.add_class("hidden")
                except:
                    pass
        except:
            pass

    def watch_sync_complete(self, complete: bool) -> None:
        """Update UI when sync completes."""
        if complete:
            try:
                # Update button text
                cancel_button = self.query_one("#cancel-button", Button)
                cancel_button.label = "Close"
                cancel_button.variant = "primary"
                
                # Show summary in detailed info
                if self.sync_result:
                    self._update_summary_display()
            except:
                pass

    def _update_conflict_display(self) -> None:
        """Update the conflict display with current conflict info."""
        if not self.conflicts or self.current_conflict_index >= len(self.conflicts):
            return

        try:
            conflict = self.conflicts[self.current_conflict_index]
            conflict_info = self.query_one("#conflict-info", Static)
            
            # Build conflict display text
            lines = []
            lines.append(f"Conflict {self.current_conflict_index + 1} of {len(self.conflicts)}")
            lines.append(f"Item: {conflict.item_id}")
            lines.append(f"Type: {conflict.conflict_type}")
            lines.append("")
            
            if conflict.conflict_type == "paper":
                lines.append("Differences:")
                for field, diff in conflict.differences.items():
                    if field not in {"id", "created_at", "updated_at"}:
                        local_val = str(diff.get("local", ""))[:100]
                        remote_val = str(diff.get("remote", ""))[:100]
                        lines.append(f"  {field}:")
                        lines.append(f"    Local:  {local_val}")
                        lines.append(f"    Remote: {remote_val}")
                        lines.append("")
            elif conflict.conflict_type == "pdf":
                lines.append("PDF File Differences:")
                lines.append(f"  Local size:  {conflict.local_data.get('size', 'N/A')} bytes")
                lines.append(f"  Remote size: {conflict.remote_data.get('size', 'N/A')} bytes")
                lines.append(f"  Local modified:  {conflict.local_data.get('modified', 'N/A')}")
                lines.append(f"  Remote modified: {conflict.remote_data.get('modified', 'N/A')}")

            lines.append("")
            lines.append("Choose: L=Local, R=Remote, B=Keep Both")
            
            conflict_info.update("\n".join(lines))
        except Exception:
            pass

    def _update_summary_display(self) -> None:
        """Update the detailed info with sync summary."""
        if not self.sync_result:
            return

        try:
            detailed_info = self.query_one("#detailed-info", Static)
            
            lines = []
            lines.append("SYNC COMPLETED")
            lines.append("=" * 50)
            lines.append("")
            lines.append(self.sync_result.get_summary())
            
            if hasattr(self.sync_result, 'detailed_changes'):
                lines.append("")
                lines.append("Detailed Changes:")
                for change_type, items in self.sync_result.detailed_changes.items():
                    if items:
                        lines.append(f"  {change_type.replace('_', ' ').title()}: {len(items)}")
                        for item in items[:5]:  # Show first 5 items
                            lines.append(f"    - {item}")
                        if len(items) > 5:
                            lines.append(f"    ... and {len(items) - 5} more")

            if self.sync_result.errors:
                lines.append("")
                lines.append("Errors:")
                for error in self.sync_result.errors:
                    lines.append(f"  - {error}")
            
            detailed_info.update("\n".join(lines))
        except Exception:
            pass

    def start_sync(self):
        """Start the sync operation in a background thread."""
        def sync_worker():
            try:
                def conflict_resolver(conflicts):
                    if conflicts and not self.sync_cancelled:
                        self.conflicts = conflicts
                        self.show_conflicts = True
                        self.conflict_resolution_event.wait()
                        return self.resolutions
                    return {}

                def progress_updater(message, counts=None):
                    if not self.sync_cancelled:
                        self.status_text = message
                        
                        # Map progress messages to percentages
                        progress_map = {
                            "Creating remote directory": 10,
                            "Checking remote database": 20,
                            "Detecting conflicts": 30,
                            "Synchronizing papers": 50,
                            "Synchronizing collections": 70,
                            "Synchronizing PDF files": 85,
                            "Finalizing sync": 95,
                        }
                        
                        for step, percentage in progress_map.items():
                            if step in message:
                                self.progress_percentage = percentage
                                break

                sync_service = SyncService(
                    self.local_path,
                    self.remote_path,
                    progress_callback=progress_updater,
                )
                
                self.sync_result = sync_service.sync(conflict_resolver=conflict_resolver)

                if not self.sync_cancelled:
                    self.sync_complete = True
                    self.progress_percentage = 100
                    self.status_text = "Sync completed successfully"
                    self.show_conflicts = False

            except Exception as e:
                if not self.sync_cancelled:
                    self.sync_complete = True
                    self.status_text = f"Sync failed: {str(e)}"

        self.sync_thread = threading.Thread(target=sync_worker, daemon=True)
        self.sync_thread.start()

    def action_cancel(self) -> None:
        """Cancel sync or close dialog."""
        if not self.sync_complete:
            self.sync_cancelled = True
            self.status_text = "Sync cancelled"
            
        if self.callback:
            self.callback(self.sync_result if self.sync_complete else None)
        self.dismiss(self.sync_result if self.sync_complete else None)

    def action_use_local(self) -> None:
        """Use local version for current conflict."""
        if self.show_conflicts and self.conflicts:
            self._resolve_current("local")

    def action_use_remote(self) -> None:
        """Use remote version for current conflict."""
        if self.show_conflicts and self.conflicts:
            self._resolve_current("remote")

    def action_keep_both(self) -> None:
        """Keep both versions for current conflict."""
        if self.show_conflicts and self.conflicts:
            self._resolve_current("keep_both")

    def action_all_local(self) -> None:
        """Use local version for all remaining conflicts."""
        if self.show_conflicts:
            self._resolve_all("local")

    def action_all_remote(self) -> None:
        """Use remote version for all remaining conflicts."""
        if self.show_conflicts:
            self._resolve_all("remote")

    def action_all_both(self) -> None:
        """Keep both versions for all remaining conflicts."""
        if self.show_conflicts:
            self._resolve_all("keep_both")

    def _resolve_current(self, resolution: str):
        """Resolve current conflict and move to next."""
        if not self.conflicts:
            return
            
        conflict = self.conflicts[self.current_conflict_index]
        self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = resolution
        
        # Move to next unresolved conflict
        self._next_unresolved_conflict()

    def _resolve_all(self, resolution: str):
        """Resolve all conflicts and continue sync."""
        for conflict in self.conflicts:
            self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = resolution
        
        self.show_conflicts = False
        self.status_text = "Applying conflict resolutions..."
        self.conflict_resolution_event.set()

    def _next_unresolved_conflict(self):
        """Move to next unresolved conflict or finish if all resolved."""
        original_index = self.current_conflict_index
        
        # Find next unresolved conflict
        for i in range(self.current_conflict_index + 1, len(self.conflicts)):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                self._update_conflict_display()
                return
        
        # Check conflicts before current index
        for i in range(0, self.current_conflict_index):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                self._update_conflict_display()
                return
        
        # All conflicts resolved
        self.show_conflicts = False
        self.status_text = "Applying conflict resolutions..."
        self.conflict_resolution_event.set()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-button":
            self.action_cancel()
        elif event.button.id == "local-button":
            self.action_use_local()
        elif event.button.id == "remote-button":
            self.action_use_remote()
        elif event.button.id == "keep-both-button":
            self.action_keep_both()
        elif event.button.id == "all-local-button":
            self.action_all_local()
        elif event.button.id == "all-remote-button":
            self.action_all_remote()
        elif event.button.id == "all-both-button":
            self.action_all_both()