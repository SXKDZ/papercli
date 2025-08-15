import difflib
import os
import threading
from typing import Callable, Dict, List

from pluralizer import Pluralizer
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, ProgressBar, Static

from ng.services import SyncConflict, SyncService


class SyncDialog(ModalScreen):
    """A modal dialog for sync progress with conflict resolution."""

    class ConflictsFound(Message):
        """Message sent when conflicts are detected."""

        def __init__(self, conflicts: List[SyncConflict]) -> None:
            super().__init__()
            self.conflicts = conflicts

    class ProgressUpdate(Message):
        """Message sent when progress updates."""

        def __init__(self, message: str, percentage: int) -> None:
            super().__init__()
            self.message = message
            self.percentage = percentage

    class SyncComplete(Message):
        """Message sent when sync completes."""

        def __init__(self, success: bool, error_msg: str = None) -> None:
            super().__init__()
            self.success = success
            self.error_msg = error_msg

    DEFAULT_CSS = """
    SyncDialog {
        align: center middle;
        layer: dialog;
    }
    SyncDialog > Container {
        width: 80%;
        height: 26%;
        border: solid $accent;
        background: $panel;
    }
    SyncDialog.conflict-mode > Container {
        height: 75%;
    }
    SyncDialog.summary-mode > Container {
        height: 60%;
    }
    SyncDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    SyncDialog .column-title {
        text-style: bold;
        text-align: center;
        height: 1;
        background: $accent-darken-1;
        color: $text;
    }
    SyncDialog #progress-section {
        height: 5;
        padding: 1;
        width: 100%;
    }
    SyncDialog #progress-container {
        height: 1;
        width: 100%;
        padding: 0 1;
    }
    SyncDialog #progress-bar {
        width: 100%;
        height: 1;
    }
    SyncDialog #progress-bar > Bar {
        width: 90%;
        padding: 0 1;
    }
    SyncDialog #progress-bar > PercentageStatus {
        width: 5%;
        padding: 0 1;
        text-align: left;
    }
    SyncDialog #progress-bar > ETAStatus {
        width: 5%;
        padding: 0 1;
        text-align: right;
    }
    SyncDialog #status-text {
        height: 1;
        text-align: center;
        margin: 0 1;
    }
    SyncDialog #content-container {
        height: 1fr;
        margin: 0 1 1 1;
        border: none;
    }
    SyncDialog #progress-content, 
    SyncDialog #conflict-content {
        padding: 0;
        height: 1fr;
    }
    SyncDialog #conflict-layout {
        height: 1fr;
        width: 100%;
    }
    SyncDialog #local-panel, 
    SyncDialog #remote-panel {
        width: 45%;
        padding: 0;
        border: solid $primary;
    }
    SyncDialog #local-scroll, 
    SyncDialog #remote-scroll,
    SyncDialog #summary-scroll {
        height: 1fr;
        width: 100%;
        padding: 0 1 1 1;
    }
    SyncDialog #resolution-panel {
        width: 10%;
        align: center middle;
        padding: 1;
    }
    SyncDialog #conflict-info, 
    SyncDialog #detailed-info {
        height: 1fr;
    }
    SyncDialog #conflict-buttons, 
    SyncDialog #main-buttons {
        align: center middle;
        padding: 0;
    }
    SyncDialog #conflict-buttons {
        height: auto;
        width: 100%;
    }
    SyncDialog #main-buttons {
        height: 3;
    }
    SyncDialog Button {
        margin: 0 1;
        min-width: 12;
        content-align: center middle;
        text-align: center;
    }
    SyncDialog #conflict-buttons Button {
        margin: 1 0;
        min-width: 8;
        width: 100%;
    }
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel/Close"),
        ("enter", "close_if_complete", "OK"),
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
        self.pluralizer = Pluralizer()

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
                with Horizontal(id="progress-container"):
                    yield ProgressBar(
                        total=100, show_percentage=True, id="progress-bar"
                    )
                yield Static("", id="status-text")

            # Single content container that switches between progress and conflicts
            with Container(id="content-container"):
                with Container(id="progress-content", classes="hidden"):
                    pass  # Empty progress content
                with Container(id="summary-content", classes="hidden"):
                    with VerticalScroll(id="summary-scroll"):
                        yield Markdown("", id="summary-md")
                with Container(id="conflict-content", classes="hidden"):
                    with Horizontal(id="conflict-layout"):
                        # Left: Local
                        with Container(id="local-panel"):
                            yield Static("Local Version", classes="column-title")
                            with VerticalScroll(id="local-scroll"):
                                yield Markdown(
                                    "_Loading conflict data..._", id="local-md"
                                )
                        # Middle: Remote
                        with Container(id="remote-panel"):
                            yield Static("Remote Version", classes="column-title")
                            with VerticalScroll(id="remote-scroll"):
                                yield Markdown(
                                    "_Loading conflict data..._", id="remote-md"
                                )
                        # Right: Resolution buttons stacked vertically
                        with Container(id="resolution-panel"):
                            with Vertical(id="conflict-buttons", classes="hidden"):
                                yield Button(
                                    "Use Local", id="local-button", variant="default"
                                )
                                yield Button(
                                    "Use Remote", id="remote-button", variant="default"
                                )
                                yield Button(
                                    "Keep Both",
                                    id="keep-both-button",
                                    variant="default",
                                )
                                yield Button(
                                    "All Local",
                                    id="all-local-button",
                                    variant="warning",
                                )
                                yield Button(
                                    "All Remote",
                                    id="all-remote-button",
                                    variant="warning",
                                )
                                yield Button(
                                    "Keep All", id="all-both-button", variant="success"
                                )

            # Conflict resolution buttons are embedded in the middle panel now
            # Main buttons
            with Horizontal(id="main-buttons"):
                yield Button("Cancel", id="cancel-button", variant="error")

    def on_mount(self) -> None:
        """Start sync operation when dialog opens."""
        # Reset internal state each time the dialog is mounted
        self._reset_state()
        self.start_sync()

    def watch_progress_percentage(self, percentage: int) -> None:
        """Update progress bar when percentage changes."""
        try:
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(progress=percentage)
        except Exception:
            pass

    def watch_status_text(self, text: str) -> None:
        """Update status text when it changes."""
        try:
            status_widget = self.query_one("#status-text", Static)

            # Create detailed status like in app version
            if self.show_conflicts:
                total_conflicts = len(self.conflicts)
                current_index = self.current_conflict_index + 1
                conflict_word = self.pluralizer.pluralize(
                    "conflict", total_conflicts, True
                )
                status_text = f"Status: Resolving {current_index} of {conflict_word}"
            else:
                status_text = f"Status: {text}"

            status_widget.update(status_text)
        except Exception:
            pass

    def watch_show_conflicts(self, show: bool) -> None:
        """Show/hide conflict resolution UI."""
        self.app._add_log(
            "sync_show_conflicts",
            f"watch_show_conflicts called with show={show}, conflicts={len(self.conflicts) if self.conflicts else 0}",
        )
        try:
            progress_content = self.query_one("#progress-content")
            conflict_content = self.query_one("#conflict-content")

            if show and self.conflicts:
                self.app._add_log("sync_ui_switch", "Switching to conflict view")
                # Switch to conflict view FIRST
                conflict_content.remove_class("hidden")
                progress_content.add_class("hidden")

                # Add conflict mode class for larger height
                self.add_class("conflict-mode")
                self.remove_class("summary-mode")

                # Show conflict buttons (stacked vertically in resolution panel)
                conflict_buttons = self.query_one("#conflict-buttons")
                conflict_buttons.remove_class("hidden")
                self.app._add_log(
                    "sync_ui_elements",
                    "Removed hidden class from conflict content and buttons",
                )

                # Update conflict info AFTER making visible
                self._update_conflict_display()
            else:
                self.app._add_log(
                    "sync_ui_switch",
                    f"Not switching to conflict view - show={show}, conflicts={len(self.conflicts) if self.conflicts else 0}",
                )
                # Switch back to progress/summary view
                conflict_content.add_class("hidden")
                progress_content.remove_class("hidden")

                # Remove conflict mode class
                self.remove_class("conflict-mode")

                # Hide conflict buttons
                try:
                    conflict_buttons = self.query_one("#conflict-buttons")
                    conflict_buttons.add_class("hidden")
                except Exception:
                    pass
        except Exception:
            pass

    def watch_sync_complete(self, complete: bool) -> None:
        """Update UI when sync completes."""
        if complete:
            try:
                # Update button text
                cancel_button = self.query_one("#cancel-button", Button)
                cancel_button.label = "OK"
                cancel_button.variant = "primary"

                # Add summary mode class for medium height
                self.add_class("summary-mode")
                self.remove_class("conflict-mode")

                # Show summary in detailed info
                if self.sync_result:
                    self._update_summary_display()
            except Exception:
                pass

    def _update_conflict_display(self) -> None:
        """Update the conflict display with current conflict info."""
        if not self.conflicts or self.current_conflict_index >= len(self.conflicts):
            # No conflicts to display
            return

        try:
            conflict = self.conflicts[self.current_conflict_index]
            self.app._add_log(
                "sync_conflict_display",
                f"Updating conflict display for conflict {self.current_conflict_index + 1} of {len(self.conflicts)}, type: {conflict.conflict_type}",
            )
            local_md = self.query_one("#local-md", Markdown)
            remote_md = self.query_one("#remote-md", Markdown)
            self.app._add_log(
                "sync_conflict_widgets",
                f"Found markdown widgets - local: {local_md is not None}, remote: {remote_md is not None}",
            )

            local_paper_id = conflict.local_data.get("id")
            local_paper_title = conflict.local_data.get("title", "Unknown Title")
            remote_paper_id = conflict.remote_data.get("id")
            remote_paper_title = conflict.remote_data.get("title", "Unknown Title")

            if conflict.conflict_type == "paper":
                self.app._add_log(
                    "sync_conflict_paper",
                    f"Processing paper conflict - differences: {list(conflict.differences.keys())}",
                )

                def build_side_with_diffs(side: str) -> str:
                    parts: list[str] = [
                        (
                            f"**Paper #{local_paper_id}:** {local_paper_title}\n\n"
                            if side == "local"
                            else f"**Paper #{remote_paper_id}:** {remote_paper_title}\n\n"
                        ),
                        # type_line,
                        "#### Differences\n",
                    ]

                    # Sort fields to ensure consistent order and prioritize important fields
                    sorted_fields = sorted(
                        conflict.differences.items(),
                        key=lambda x: (x[0] != "notes", x[0]),
                    )

                    for field, diff in sorted_fields:
                        if field in {"id", "created_at"}:
                            continue

                        local_value = str(diff.get("local", ""))
                        remote_value = str(diff.get("remote", ""))

                        # For short structured fields, just display the value without diff processing
                        current_value = str(diff.get(side, ""))
                        if (
                            field
                            in {
                                "modified_date",
                                "added_date",
                                "year",
                                "volume",
                                "issue",
                                "pages",
                            }
                            or len(current_value) < 100
                        ):
                            diff_content = f"    {current_value}"
                        else:
                            diff_content = self._create_highlighted_diff(
                                local_value, remote_value, side
                            )
                        parts.append(
                            f"- **{field.replace('_', ' ').title()}:**\n\n{diff_content}\n"
                        )
                    return "\n".join(parts)

                local_content = build_side_with_diffs("local")
                remote_content = build_side_with_diffs("remote")
                self.app._add_log(
                    "sync_conflict_content",
                    f"Local content length: {len(local_content)}, Remote content length: {len(remote_content)}",
                )
                local_md.update(local_content)
                remote_md.update(remote_content)
                self.app._add_log(
                    "sync_conflict_updated", "Markdown widgets updated successfully"
                )
            elif conflict.conflict_type == "pdf":
                local_info = conflict.local_data
                remote_info = conflict.remote_data
                local_md.update(
                    f"**Paper #{local_paper_id}:** {local_paper_title}\n\n"
                    + "#### PDF Differences\n"
                    + "\n".join(
                        [
                            f"- **File Size:** {local_info.get('size', 'N/A')}",
                            f"- **Modified:** {local_info.get('modified', 'N/A')}",
                            f"- **Hash:** {local_info.get('hash', 'N/A')}",
                        ]
                    )
                )
                remote_md.update(
                    f"**Paper #{remote_paper_id}:** {remote_paper_title}\n\n"
                    + "#### PDF Differences\n"
                    + "\n".join(
                        [
                            f"- **File Size:** {remote_info.get('size', 'N/A')}",
                            f"- **Modified:** {remote_info.get('modified', 'N/A')}",
                            f"- **Hash:** {remote_info.get('hash', 'N/A')}",
                        ]
                    )
                )
        except Exception as e:
            # Show error in the panels if update fails
            try:
                local_md = self.query_one("#local-md", Markdown)
                remote_md = self.query_one("#remote-md", Markdown)
                error_msg = f"## Error Loading Conflict\n\n{str(e)}"
                local_md.update(error_msg)
                remote_md.update(error_msg)
            except Exception:
                pass

    def _create_highlighted_diff(
        self, local_text: str, remote_text: str, side: str
    ) -> str:
        """Create highlighted diff showing all differences with 5 words context, max 5 lines."""
        if local_text == remote_text:
            return (
                f"    {local_text[:100]}..."
                if len(local_text) > 100
                else f"    {local_text}"
            )

        # Split into words for better diff granularity
        local_words = local_text.split()
        remote_words = remote_text.split()

        # Use difflib to find differences
        matcher = difflib.SequenceMatcher(None, local_words, remote_words)
        current_words = local_words if side == "local" else remote_words

        # Collect all difference ranges for the current side
        diff_ranges = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                # Determine which indices to use based on the side
                if side == "local":
                    diff_start, diff_end = i1, i2
                else:
                    diff_start, diff_end = j1, j2
                diff_ranges.append((diff_start, diff_end))

        if not diff_ranges:
            # If no differences found, show truncated text (max 5 lines)
            text = " ".join(current_words)
            if len(text) > 400:  # Rough estimate for 5 lines
                text = text[:400] + "..."
            return f"    {text}"

        # Find the overall range that encompasses all differences with context
        min_diff = min(start for start, _ in diff_ranges)
        max_diff = max(end for _, end in diff_ranges)

        # Get context around all differences (5 words before first and after last)
        context_start = max(0, min_diff - 5)
        context_end = min(len(current_words), max_diff + 5)

        # Build the context with highlighting for all differences
        context_words = []
        for i in range(context_start, context_end):
            if i < len(current_words):
                word = current_words[i]
                # Check if this word is in any difference range
                is_different = any(start <= i < end for start, end in diff_ranges)
                if is_different:
                    # Use bold for differences (markdown doesn't support color in Textual)
                    context_words.append(f"**{word}**")
                else:
                    context_words.append(word)

        # Join words and split into lines for display (max 5 lines)
        full_text = " ".join(context_words)

        # Check if text was truncated at word level
        text_was_truncated = context_end < len(current_words)
        text_was_truncated_start = context_start > 0

        # Split into approximately equal chunks (roughly 80 chars per line)
        lines = []
        words = full_text.split()
        current_line = []
        current_length = 0
        words_remaining = words[:]

        for i, word in enumerate(words):
            # Estimate word length (accounting for bold markup)
            word_length = len(word.replace("**", ""))
            if current_length + word_length + 1 > 80 and current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_length
            else:
                current_line.append(word)
                current_length += word_length + 1

            # Stop if we have 5 lines
            if len(lines) >= 5:
                # Mark remaining words for ellipsis
                words_remaining = words[i + 1 :]
                break

        # Add remaining words to last line if we haven't hit the line limit
        if current_line and len(lines) < 5:
            lines.append(" ".join(current_line))
            words_remaining = []

        # Limit to 5 lines
        if len(lines) > 5:
            lines = lines[:5]
            words_remaining = True  # Mark that we truncated

        # Add trailing ellipsis if ANY truncation occurred
        needs_ellipsis = text_was_truncated or words_remaining

        if lines and needs_ellipsis:
            lines[-1] += " ..."

        # Add leading ellipsis if we truncated from start
        if text_was_truncated_start and lines:
            lines[0] = "... " + lines[0]

        # Format each line with indentation
        formatted_lines = [f"    {line}" for line in lines]
        return "\n".join(formatted_lines)

    def _update_conflict_status(self) -> None:
        """Update status text to reflect current conflict position."""
        if self.show_conflicts and self.conflicts:
            resolved_count = len(self.resolutions)
            total_conflicts = len(self.conflicts)
            current_index = self.current_conflict_index + 1
            conflict_word = self.pluralizer.pluralize("conflict", total_conflicts)
            self.status_text = f"Resolving {total_conflicts} {conflict_word} - {current_index} of {total_conflicts} ({resolved_count} resolved)"

    def _show_summary(self) -> None:
        """Show sync summary in the summary content panel."""
        try:
            # Hide other content and show summary
            progress_content = self.query_one("#progress-content")
            conflict_content = self.query_one("#conflict-content")
            summary_content = self.query_one("#summary-content")

            progress_content.add_class("hidden")
            conflict_content.add_class("hidden")
            summary_content.remove_class("hidden")

            # Always use summary-mode height when showing summary
            self.add_class("summary-mode")
            self.remove_class("conflict-mode")

            # Update summary content
            self._update_summary_display()
        except Exception:
            pass

    def _update_summary_display(self) -> None:
        """Update the summary markdown with sync results."""
        if not self.sync_result:
            return

        try:
            summary_md = self.query_one("#summary-md", Markdown)

            md_lines: list[str] = []
            md_lines.append("## Sync Completed\n")
            md_lines.append(self.sync_result.get_summary() + "\n")

            # Only show detailed changes if there are actual changes
            has_changes = False
            if hasattr(self.sync_result, "detailed_changes"):
                for change_type, items in self.sync_result.detailed_changes.items():
                    if items:
                        has_changes = True
                        break

            if has_changes:
                md_lines.append("### Detailed Changes\n")
                for change_type, items in self.sync_result.detailed_changes.items():
                    if items:
                        # Map change types to proper titles with correct pluralization
                        title_mapping = {
                            "pdfs_copied": f"PDFs Copied: {len(items)}",
                            "pdfs_updated": f"PDFs Updated: {len(items)}",
                            "papers_added": f"Papers Added: {len(items)}",
                            "papers_updated": f"Papers Updated: {len(items)}",
                            "collections_synced": f"Collections Synced: {len(items)}",
                        }

                        if change_type in title_mapping:
                            display_title = title_mapping[change_type]
                        else:
                            # Fallback for any unmapped types
                            display_title = (
                                f"{change_type.replace('_', ' ').title()}: {len(items)}"
                            )

                        md_lines.append(f"- **{display_title}**\n")
                        for item in items[:5]:
                            md_lines.append(f"  - {item}\n")
                        if len(items) > 5:
                            md_lines.append(f"  - ... and {len(items) - 5} more\n")

            if self.sync_result.errors:
                md_lines.append("\n### Errors\n")
                for error in self.sync_result.errors:
                    md_lines.append(f"- {error}\n")

            summary_md.update("\n".join(md_lines))
        except Exception:
            pass

    def start_sync(self):
        """Start the sync operation in a background thread."""

        def sync_worker():
            try:

                def conflict_resolver(conflicts):
                    self.app._add_log(
                        "sync_conflict_resolver",
                        f"conflict_resolver called with {len(conflicts) if conflicts else 0} conflicts",
                    )
                    if conflicts:
                        if self.sync_cancelled:
                            return None
                        self.app._add_log(
                            "sync_conflict_found",
                            f"Found {len(conflicts)} conflicts, setting show_conflicts=True",
                        )

                        # Send signal to main thread
                        self.post_message(self.ConflictsFound(conflicts))

                        # Wait for conflict resolution
                        self.app._add_log(
                            "sync_conflict_wait", "Waiting for conflict resolution..."
                        )
                        self.conflict_resolution_event.wait()

                        if self.sync_cancelled:
                            return None
                        return self.resolutions
                    return {}

                def progress_updater(message, counts=None):
                    if not self.sync_cancelled:
                        # Map progress messages from service to percentages
                        progress_map = [
                            ("Converting absolute PDF paths to relative", 5),
                            ("Creating remote directory", 10),
                            ("Analyzing differences", 30),
                            ("Synchronizing remote to local", 50),
                            ("Synchronizing local to remote", 70),
                            ("Synchronizing collections", 90),
                        ]

                        percentage = 0
                        for step, pct in progress_map:
                            if step in message:
                                percentage = pct
                                break

                        # Send signal to main thread
                        self.post_message(self.ProgressUpdate(message, percentage))

                sync_service = SyncService(
                    self.local_path,
                    self.remote_path,
                    progress_callback=progress_updater,
                )

                self.sync_result = sync_service.sync(
                    conflict_resolver=conflict_resolver
                )

                if not self.sync_cancelled:
                    # Send completion signal to main thread
                    self.post_message(self.SyncComplete(True))
                else:
                    # Mark result as cancelled if available so UI doesn't show completed
                    if self.sync_result is not None and hasattr(
                        self.sync_result, "cancelled"
                    ):
                        self.sync_result.cancelled = True

            except Exception as e:
                if not self.sync_cancelled:
                    # Send error signal to main thread
                    self.post_message(self.SyncComplete(False, str(e)))

        self.sync_thread = threading.Thread(target=sync_worker, daemon=True)
        self.sync_thread.start()

    def action_close_if_complete(self) -> None:
        """Close dialog if sync is complete, otherwise do nothing."""
        if self.sync_complete:
            self.action_cancel()

    def action_cancel(self) -> None:
        """Cancel sync or close dialog."""
        if not self.sync_complete:
            self.sync_cancelled = True
            self.status_text = "Sync cancelled"
            # Unblock any waiting conflict resolver and let the worker exit
            try:
                self.conflict_resolution_event.set()
            except Exception:
                pass
            # Best-effort join to allow locks to be released
            try:
                if self.sync_thread and self.sync_thread.is_alive():
                    self.sync_thread.join(timeout=0.1)
            except Exception:
                pass
            # Clean up residual lock files so a new sync can start immediately
            self._cleanup_sync_locks()

        if self.callback:
            self.callback(self.sync_result if self.sync_complete else None)
        self.dismiss(self.sync_result if self.sync_complete else None)

    def _cleanup_sync_locks(self) -> None:
        """Remove sync lock files to allow immediate re-run after cancel."""
        try:
            for base_dir in [self.local_path, self.remote_path]:
                if not base_dir:
                    continue
                lock_path = os.path.join(base_dir, ".papercli_sync.lock")
                if os.path.exists(lock_path):
                    os.remove(lock_path)
        except Exception:
            # Ignore cleanup failures
            pass

    def on_sync_dialog_conflicts_found(self, message: ConflictsFound) -> None:
        """Handle conflicts found signal."""
        self.conflicts = message.conflicts
        conflict_word = self.pluralizer.pluralize("conflict", len(self.conflicts))
        self.status_text = f"Found {len(self.conflicts)} {conflict_word} - resolving 1 of {len(self.conflicts)}..."
        self.show_conflicts = True
        self.app._add_log(
            "sync_conflict_signal",
            f"Conflicts signal received - conflicts={len(self.conflicts)}, show_conflicts={self.show_conflicts}",
        )

    def on_sync_dialog_progress_update(self, message: ProgressUpdate) -> None:
        """Handle progress update signal."""
        self.status_text = message.message
        self.progress_percentage = message.percentage

    def on_sync_dialog_sync_complete(self, message: SyncComplete) -> None:
        """Handle sync completion signal."""
        self.sync_complete = True
        if message.success:
            self.progress_percentage = 100
            self.status_text = "Sync completed successfully"
            self.show_conflicts = False
            self._show_summary()
        else:
            self.status_text = f"Sync failed: {message.error_msg}"

    def _reset_state(self) -> None:
        """Reset reactive and internal state for a fresh sync run."""
        self.progress_percentage = 0
        self.status_text = "Preparing sync..."
        self.show_conflicts = False
        self.sync_complete = False
        self.conflicts_resolved = False
        self.conflicts = []
        self.current_conflict_index = 0
        self.resolutions = {}
        self.sync_result = None
        self.sync_cancelled = False
        self.conflict_resolution_event = threading.Event()

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
        # Update status to reflect current conflict
        self._update_conflict_status()

    def _resolve_all(self, resolution: str):
        """Resolve all conflicts and continue sync."""
        for conflict in self.conflicts:
            self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                resolution
            )

        self.show_conflicts = False
        self.status_text = "Applying conflict resolutions..."
        self.conflict_resolution_event.set()

    def _next_unresolved_conflict(self):
        """Move to next unresolved conflict or finish if all resolved."""

        # Find next unresolved conflict
        for i in range(self.current_conflict_index + 1, len(self.conflicts)):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                self._update_conflict_display()
                self._update_conflict_status()
                return

        # Check conflicts before current index
        for i in range(0, self.current_conflict_index):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                self._update_conflict_display()
                self._update_conflict_status()
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
