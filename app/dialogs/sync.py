"""Sync-related dialogs for conflict resolution and sync summaries."""

import threading
from typing import Callable
from typing import Dict
from typing import List

from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension
from prompt_toolkit.layout import HSplit
from prompt_toolkit.layout import Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.containers import ScrollOffsets
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button
from prompt_toolkit.widgets import Dialog

from ..services import SyncConflict


class SyncProgressDialog:
    """Dialog showing sync progress with expandable conflict resolution."""

    def __init__(
        self,
        callback: Callable,
        local_path: str,
        remote_path: str,
        status_updater: Callable = None,
        log_callback: Callable = None,
    ):
        self.callback = callback
        self.local_path = local_path
        self.remote_path = remote_path
        self.status_updater = status_updater
        self.log_callback = log_callback

        # Check auto-sync mode
        import os

        self.auto_sync_mode = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"

        # Dialog state
        self.progress_text = "Checking remote database..."
        self.conflicts: List[SyncConflict] = []
        self.current_conflict_index = 0
        self.resolutions: Dict[str, str] = {}
        self.sync_result = None
        self.sync_thread = None
        self.show_conflicts = False
        self.show_summary = False
        self.sync_cancelled = False
        self.sync_complete = False
        self.progress_percentage = 0
        self.conflict_resolution_event = threading.Event()
        # Progress counters
        self.papers_total = 0
        self.papers_processed = 0
        self.collections_total = 0
        self.collections_processed = 0
        self.pdfs_total = 0
        self.pdfs_processed = 0

        # Create key bindings first
        self._setup_key_bindings()

        # Create dialog layout
        self._create_layout()

        # Start sync immediately
        self.start_sync()

    def _setup_key_bindings(self):
        """Setup key bindings for the dialog."""
        kb = KeyBindings()

        @kb.add("escape", eager=True)
        @kb.add(" ")  # Space for cancel
        def _(event):
            """Cancel the sync operation or close dialog."""
            if not self.sync_complete and not self.show_conflicts:
                # Cancel sync immediately
                self.sync_cancelled = True
                self.progress_text = "Sync cancelled"
                self.callback(None)
            else:
                # Close dialog (works for summary, conflicts, or completed sync)
                self.callback(self.sync_result if self.sync_complete else None)

        @kb.add("c")
        def _(event):
            """Confirm conflict resolutions and continue sync."""
            if self.show_conflicts and len(self.resolutions) == len(self.conflicts):
                self.show_conflicts = False
                self.sync_complete = True
                self.conflict_resolution_event.set()
                event.app.invalidate()

        # Conflict resolution keys (only active when conflicts are shown)
        @kb.add("l")
        def _(event):
            """Use local version for current conflict."""
            if self.show_conflicts and self.conflicts:
                conflict = self.conflicts[self.current_conflict_index]
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                    "local"
                )
                self._next_conflict()

                event.app.invalidate()

        @kb.add("r")
        def _(event):
            """Use remote version for current conflict."""
            if self.show_conflicts and self.conflicts:
                conflict = self.conflicts[self.current_conflict_index]
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                    "remote"
                )
                self._next_conflict()

                event.app.invalidate()

        @kb.add("b")
        @kb.add("k")
        def _(event):
            """Keep both versions for current conflict."""
            if self.show_conflicts and self.conflicts:
                conflict = self.conflicts[self.current_conflict_index]
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                    "keep_both"
                )
                self._next_conflict()

                event.app.invalidate()

        @kb.add("L")
        def _(event):
            """Use local version for all remaining conflicts."""
            if self.show_conflicts:
                for conflict in self.conflicts:
                    self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                        "local"
                    )
                self.show_conflicts = False
                self.sync_complete = True

                event.app.invalidate()

        @kb.add("R")
        def _(event):
            """Use remote version for all remaining conflicts."""
            if self.show_conflicts:
                for conflict in self.conflicts:
                    self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                        "remote"
                    )
                self.show_conflicts = False
                self.sync_complete = True

                event.app.invalidate()

        @kb.add("A")
        def _(event):
            """Keep all versions for all remaining conflicts."""
            if self.show_conflicts:
                for conflict in self.conflicts:
                    self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                        "keep_both"
                    )
                self.show_conflicts = False
                self.sync_complete = True

                event.app.invalidate()

        @kb.add("n")
        def _(event):
            """Next conflict."""
            if self.show_conflicts:
                self._next_conflict()

                event.app.invalidate()

        @kb.add("p")
        def _(event):
            """Previous conflict."""
            if self.show_conflicts:
                self._prev_conflict()

                event.app.invalidate()

        @kb.add("right")
        def _(event):
            """Next conflict."""
            if self.show_conflicts:
                self._next_conflict()

                event.app.invalidate()

        @kb.add("left")
        def _(event):
            """Previous conflict."""
            if self.show_conflicts:
                self._prev_conflict()

                event.app.invalidate()

        # Block all other keys during sync progress
        @kb.add("<any>")
        def _(event):
            """Block all other key input during sync."""
            # Only allow the specific keys we've already defined above
            # This prevents typing in the main input while sync is running
            pass

        # Store key bindings for the dialog
        self.key_bindings = kb

    def _create_layout(self):
        """Create the dialog layout."""
        # Create conditions for visibility
        conflicts_visible = Condition(lambda: self.show_conflicts)
        summary_visible = Condition(lambda: self.show_summary)

        # Create the three-part layout as specified:
        # 1. Top: Progress bar (vertically centered, almost full width)
        # 2. Middle: Large text area (status + conflicts + summary)
        # 3. Bottom: Buttons (handled separately in Dialog)

        self.body_content = HSplit(
            [
                # Part 1: Progress bar at top (vertically centered, almost full width)
                Window(
                    FormattedTextControl(
                        self._get_progress_bar_only,
                    ),
                    height=Dimension(min=3, max=3),  # Fixed height for progress bar
                    wrap_lines=False,
                    align="center",  # Center the progress bar
                ),
                # Part 2: Large text area in middle (combines status, conflicts, summary)
                Window(
                    FormattedTextControl(self._get_combined_text_content),
                    height=Dimension(min=15, max=30),  # Large text area
                    wrap_lines=True,
                    scroll_offsets=ScrollOffsets(top=1, bottom=1),
                ),
            ]
        )

        # Create conflict resolution buttons (always present but conditionally visible)
        self.local_button = Button(
            text="Use Local", handler=self._create_resolution_handler("local")
        )
        self.remote_button = Button(
            text="Use Remote", handler=self._create_resolution_handler("remote")
        )
        self.both_button = Button(
            text="Keep Both", handler=self._create_resolution_handler("keep_both")
        )
        self.all_local_button = Button(
            text="All Local", handler=self._create_all_resolution_handler("local")
        )
        self.all_remote_button = Button(
            text="All Remote", handler=self._create_all_resolution_handler("remote")
        )
        self.keep_all_button = Button(
            text="Keep All", handler=self._create_all_resolution_handler("keep_both")
        )

        # Create cancel button
        self.cancel_button = Button(text="Cancel", handler=self._handle_close)

        # Create dialog with all buttons
        # Conflict resolution buttons (6 buttons with spacing before cancel)
        conflict_buttons = [
            ConditionalContainer(
                self.local_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.remote_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.both_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.all_local_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.all_remote_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.keep_all_button, filter=Condition(lambda: self.show_conflicts)
            ),
        ]

        # Add spacing and cancel button
        all_buttons = conflict_buttons + [self.cancel_button]

        self.dialog = Dialog(
            title=self._get_dynamic_title,
            body=self.body_content,
            buttons=all_buttons,
            with_background=False,
            modal=True,
            width=Dimension(min=139, max=139),
        )

    def _get_dynamic_title(self):
        """Get dynamic title based on sync state."""
        if self.sync_complete:
            if self.sync_result and self.sync_result.errors:
                return "Syncing with Remote Database - Completed with Errors"
            elif self.conflicts and not self.resolutions:
                return "Syncing with Remote Database - Conflicts Found"
            else:
                return "Syncing with Remote Database - Completed Successfully"
        else:
            return "Syncing with Remote Database"

    def _get_progress_bar_only(self):
        """Get only the progress bar for the top section with the specified internal spacing."""
        # A fixed width for the bar portion to keep the UI stable.
        # This width is chosen to fit within the Dialog's max width (160) and allow centering.
        bar_width = 122

        filled = int((self.progress_percentage / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        percentage_text = f"{self.progress_percentage:>3}%"

        # Create the complete progress text with your specified spacing.
        # The Window's `align="center"` will handle the horizontal centering of this entire string.
        progress_line = f"   [{bar}]  {percentage_text}   "

        return [("", progress_line)]

    def _get_combined_text_content(self):
        """Get all text content for the middle section (status + conflicts + summary + instructions)."""
        lines = []

        # Add status text
        if not self.sync_complete:
            lines.append(("", "\n"))  # Some spacing from progress bar

            # Show progress with counts
            progress_with_counts = self.progress_text
            if "papers" in self.progress_text.lower() and self.papers_total > 0:
                progress_with_counts = (
                    f"Status: Synchronizing {self.papers_total} papers..."
                )
            elif (
                "collections" in self.progress_text.lower()
                and self.collections_total > 0
            ):
                progress_with_counts = (
                    f"Status: Synchronizing {self.collections_total} collections..."
                )
            elif "pdf" in self.progress_text.lower() and self.pdfs_total > 0:
                progress_with_counts = (
                    f"Status: Synchronizing {self.pdfs_total} PDFs..."
                )
            else:
                progress_with_counts = f"Status: {self.progress_text}"

            lines.append(("class:progress-message", progress_with_counts))
            lines.append(("", "\n\n"))

        # Add conflict details if showing conflicts
        if self.show_conflicts:
            lines.extend(self._get_conflict_text())
            lines.append(("", "\n"))

        # Add summary if showing summary
        if self.show_summary:
            lines.extend(self._get_summary_text())
            lines.append(("", "\n"))

        # Add instructions
        instruction_lines = self._get_instructions()
        if instruction_lines:
            lines.extend(instruction_lines)

        return lines

    def _get_progress_text(self):
        """Get the progress text as formatted text."""
        lines = []

        if self.sync_complete:
            if self.sync_result and self.sync_result.errors:
                lines.append(("class:error", "❌ Sync completed with errors"))
                lines.append(("", "\n"))
                lines.append(
                    ("class:error", f"Errors: {', '.join(self.sync_result.errors)}")
                )
            elif self.conflicts and not self.resolutions:
                lines.append(
                    ("class:warning", f"⚠️ Sync found {len(self.conflicts)} conflicts")
                )
                lines.append(("", "\n"))
                lines.append(
                    ("", "Conflicts need to be resolved before completing sync.")
                )
            else:
                # Sync completed - show summary without extra lines
                if self.conflicts and self.resolutions:
                    lines.append(("", f"Resolved {len(self.conflicts)} conflicts"))
        else:
            # Just show progress text without redundant progress bar (top bar is sufficient)
            lines.append(("", "\n"))

            # Show progress with counts - if processed is 0, show total only
            progress_with_counts = self.progress_text
            if "papers" in self.progress_text.lower() and self.papers_total > 0:
                progress_with_counts = f"Synchronizing {self.papers_total} papers..."
            elif (
                "collections" in self.progress_text.lower()
                and self.collections_total > 0
            ):
                progress_with_counts = (
                    f"Synchronizing {self.collections_total} collections..."
                )
            elif "pdf" in self.progress_text.lower() and self.pdfs_total > 0:
                progress_with_counts = f"Synchronizing {self.pdfs_total} PDFs..."
            lines.append(("class:progress-message", progress_with_counts))

        return lines

    def _get_conflict_text(self):
        """Get the current conflict details as formatted text."""
        conflict = self.conflicts[self.current_conflict_index]
        lines = []

        # Conflict header
        db_id = conflict.local_data.get("id") or conflict.remote_data.get("id")
        title = conflict.item_id  # The user confirmed item_id is the title

        lines.append(
            (
                "class:conflict-header",
                f"Conflict {self.current_conflict_index + 1} of {len(self.conflicts)}",
            )
        )
        lines.append(("", "\n"))
        lines.append(
            (
                "class:conflict-type",
                f"Type: {conflict.conflict_type.title()} (ID: {db_id})",
            )
        )
        lines.append(
            (
                "class:paper-title",
                f"Title: {title}",
            )
        )
        lines.append(("", "\n\n"))

        # Conflict details - treat PDF conflicts as part of paper conflicts
        if conflict.conflict_type in ["paper", "pdf"]:
            lines.extend(self._format_paper_conflict(conflict))

        return lines

    def _format_paper_conflict(self, conflict: SyncConflict):
        """Format paper/PDF conflict details."""
        lines = []

        if conflict.conflict_type == "pdf":
            # PDF conflict - show as PDF file conflict
            lines.append(("class:paper-title", f"PDF File: {conflict.item_id}"))
            lines.append(("", "\n\n"))

            # Show PDF-specific information
            local_info = conflict.local_data
            remote_info = conflict.remote_data

            # Compare file information
            local_size = local_info.get("size", 0)
            remote_size = remote_info.get("size", 0)
            size_diff = abs(local_size - remote_size)

            lines.append(("class:section-header", "PDF Information:"))
            lines.append(("", "\n"))

            if size_diff > 0:
                if local_size > remote_size:
                    lines.append(
                        ("class:info", f"Local file is {size_diff:,} bytes larger")
                    )
                else:
                    lines.append(
                        ("class:info", f"Remote file is {size_diff:,} bytes larger")
                    )
                lines.append(("", "\n"))

            lines.append(
                ("class:warning", "⚠️ Files have different content (hash mismatch)")
            )
            lines.append(("", "\n\n"))

            # Show local PDF info
            lines.append(("class:local-version", "Local PDF:"))
            lines.append(("", "\n"))
            lines.append(("", f"  Size: {local_size:,} bytes"))
            lines.append(("", "\n"))
            lines.append(("", f"  Modified: {local_info.get('modified', 'Unknown')}"))
            lines.append(("", "\n"))
            lines.append(("", f"  Hash: {local_info.get('hash', 'Unknown')[:16]}..."))
            lines.append(("", "\n\n"))

            # Show remote PDF info
            lines.append(("class:remote-version", "Remote PDF:"))
            lines.append(("", "\n"))
            lines.append(("", f"  Size: {remote_size:,} bytes"))
            lines.append(("", "\n"))
            lines.append(("", f"  Modified: {remote_info.get('modified', 'Unknown')}"))
            lines.append(("", "\n"))
            lines.append(("", f"  Hash: {remote_info.get('hash', 'Unknown')[:16]}..."))
            lines.append(("", "\n\n"))

        else:
            # Paper conflict - show paper title first
            title = conflict.local_data.get("title") or conflict.remote_data.get(
                "title", "Unknown Paper"
            )
            lines.append(
                (
                    "class:paper-title",
                    f"Paper: {title[:80]}{'...' if len(title) > 80 else ''}",
                )
            )
            lines.append(("", "\n\n"))

        # Only show field differences for paper conflicts, not PDF conflicts
        if conflict.conflict_type == "paper":
            # Group differences by importance
            important_fields = ["title", "abstract", "authors", "doi", "arxiv_id"]
        metadata_fields = [
            "venue_full",
            "venue_short",
            "publication_year",
            "paper_type",
        ]
        user_fields = ["notes", "tags", "read_status", "priority", "summary"]

        def format_field_group(field_names, group_title):
            group_lines = []
            has_content = False

            for field in field_names:
                if field in conflict.differences:
                    has_content = True
                    diff = conflict.differences[field]

                    # Format field name
                    display_name = field.replace("_", " ").title()
                    group_lines.append(("class:field-name", f"{display_name}:"))
                    group_lines.append(("", "\n"))

                    # Format local value
                    local_val = (
                        str(diff["local"] or "") if diff["local"] is not None else ""
                    )
                    local_display = local_val[:80] + (
                        "..." if len(local_val) > 80 else ""
                    )
                    group_lines.append(
                        ("class:local-version", f"  Local:  {local_display}")
                    )
                    group_lines.append(("", "\n"))

                    # Format remote value
                    remote_val = (
                        str(diff["remote"] or "") if diff["remote"] is not None else ""
                    )
                    remote_display = remote_val[:80] + (
                        "..." if len(remote_val) > 80 else ""
                    )
                    group_lines.append(
                        ("class:remote-version", f"  Remote: {remote_display}")
                    )
                    group_lines.append(("", "\n\n"))

            if has_content:
                return (
                    [("class:section-header", f"{group_title}:")]
                    + [("", "\n")]
                    + group_lines
                )
            return []

        # Add field groups
        lines.extend(format_field_group(important_fields, "Key Information"))
        lines.extend(format_field_group(metadata_fields, "Publication Details"))
        lines.extend(format_field_group(user_fields, "User Data"))

        # Check for PDF hash conflicts
        local_pdf = conflict.local_data.get("pdf_path")
        remote_pdf = conflict.remote_data.get("pdf_path")
        if local_pdf or remote_pdf:
            lines.append(("class:section-header", "PDF Information:"))
            lines.append(("", "\n"))
            if local_pdf and remote_pdf and local_pdf == remote_pdf:
                lines.append(
                    (
                        "class:warning",
                        "⚠️ Same PDF filename but different content hashes",
                    )
                )
                lines.append(("", "\n"))
            lines.append(
                ("class:local-version", f"  Local PDF:  {local_pdf or 'None'}")
            )
            lines.append(("", "\n"))
            lines.append(
                ("class:remote-version", f"  Remote PDF: {remote_pdf or 'None'}")
            )
            lines.append(("", "\n\n"))

        return lines

    def _get_summary_text(self):
        """Get the sync summary as formatted text."""
        if not self.sync_result:
            return "No summary available."

        lines = []

        if self.sync_result.errors:
            lines.append(
                ("class:error", f"Completed with {len(self.sync_result.errors)} errors")
            )
            lines.append(("", "\n"))
        elif self.sync_result.has_conflicts():
            lines.append(
                (
                    "class:warning",
                    f"Completed with {len(self.sync_result.conflicts)} conflicts resolved",
                )
            )
            lines.append(("", "\n"))

        # Two-list summary as specified: Local and Remote
        detailed = self.sync_result.detailed_changes
        local_changes = []
        remote_changes = []

        # Categorize changes into Local and Remote operations
        for category, items in detailed.items():
            if items:
                for item in items:
                    display_item = f"{category.replace('_', ' ').title()}: {item}"
                    if "(from remote)" in item:
                        remote_changes.append(display_item)
                    elif "(kept both versions)" in item:
                        # This is a new local entry created to keep both, so it's a local change
                        local_changes.append(display_item)
                    else:
                        # Default to local change (applied to remote)
                        local_changes.append(display_item)

        # Show Local changes
        if local_changes:
            lines.append(("class:section-header", "Local Changes (Applied to Remote):"))
            lines.append(("", "\n"))
            for change in local_changes[:10]:  # Limit to first 10
                lines.append(("", f"  • {change}"))
                lines.append(("", "\n"))
            if len(local_changes) > 10:
                lines.append(
                    ("class:info", f"  ... and {len(local_changes) - 10} more")
                )
                lines.append(("", "\n"))
            lines.append(("", "\n"))

        # Show Remote changes
        if remote_changes:
            lines.append(("class:section-header", "Remote Changes (Applied to Local):"))
            lines.append(("", "\n"))
            for change in remote_changes[:10]:  # Limit to first 10
                lines.append(("", f"  • {change}"))
                lines.append(("", "\n"))
            if len(remote_changes) > 10:
                lines.append(
                    ("class:info", f"  ... and {len(remote_changes) - 10} more")
                )
                lines.append(("", "\n"))
            lines.append(("", "\n"))

        # If no changes in either direction
        if not local_changes and not remote_changes:
            lines.append(
                ("class:info", "No changes were needed - databases are in sync")
            )
            lines.append(("", "\n"))

        # Errors if any
        if self.sync_result.errors:
            lines.append(("class:section-header", "Errors:"))
            lines.append(("", "\n"))
            for error in self.sync_result.errors:
                lines.append(("class:error", f"  • {error}"))
                lines.append(("", "\n"))

        return lines

    def _get_instructions(self):
        """Get instruction text based on current state."""
        lines = []

        if self.show_conflicts:
            lines.append(
                (
                    "class:instruction",
                    "Shortcuts: [L] Use Local  [R] Use Remote  [K] Keep Both",
                )
            )
            lines.append(("", "\n"))
            lines.append(
                (
                    "class:instruction",
                    "All Actions: [Shift+L] All Local  [Shift+R] All Remote  [A] Keep All",
                )
            )
            lines.append(("", "\n"))
            lines.append(
                (
                    "class:instruction",
                    "Navigate: ← → [N]ext [P]rev | [Esc] Close",
                )
            )

        return lines

    def _next_conflict(self):
        """Move to next conflict or finish if all resolved."""
        if self.current_conflict_index < len(self.conflicts) - 1:
            self.current_conflict_index += 1
        else:
            # All conflicts resolved, finish conflict resolution
            self.show_conflicts = False
            self.conflict_resolution_event.set()  # Wake up the sync thread

    def _prev_conflict(self):
        """Move to previous conflict."""
        if self.current_conflict_index > 0:
            self.current_conflict_index -= 1

    def _create_resolution_handler(self, resolution: str):
        """Create a handler for conflict resolution buttons."""

        def handler():
            self._resolve_conflict(resolution)

        return handler

    def _create_all_resolution_handler(self, resolution: str):
        """Create a handler for all-conflict resolution buttons."""

        def handler():
            self._resolve_all_conflicts(resolution)

        return handler

    def _resolve_conflict(self, resolution: str):
        """Resolve the current conflict."""
        if self.show_conflicts and self.conflicts:
            conflict = self.conflicts[self.current_conflict_index]
            self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                resolution
            )
            self._next_conflict()

    def _resolve_all_conflicts(self, resolution: str):
        """Resolve all remaining conflicts with the given resolution."""
        if self.show_conflicts:
            for conflict in self.conflicts:
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                    resolution
                )
            self.show_conflicts = False
            self.sync_complete = True
            self.conflict_resolution_event.set()

    def start_sync(self):
        """Start the sync operation in a background thread."""

        def sync_worker():
            try:
                from ..services import SyncService

                # Create a conflict resolver that will set conflicts and expand the dialog
                def conflict_resolver(conflicts):
                    if conflicts and not self.sync_cancelled:
                        self.conflicts = conflicts

                        if self.auto_sync_mode:
                            # Auto-sync mode: automatically resolve all conflicts as "keep_both"
                            self.progress_text = f"Auto-sync mode: keeping all {len(conflicts)} conflicting items"
                            get_app().invalidate()

                            # Auto-resolve all conflicts
                            auto_resolutions = {}
                            for conflict in conflicts:
                                conflict_id = (
                                    f"{conflict.conflict_type}_{conflict.item_id}"
                                )
                                auto_resolutions[conflict_id] = "keep_both"

                            # Brief pause to show the auto-resolution message
                            import time

                            time.sleep(0.2)

                            return auto_resolutions
                        else:
                            # Manual mode: show conflicts for user resolution
                            self.show_conflicts = True
                            self.progress_text = (
                                f"Found {len(conflicts)} conflicts requiring resolution"
                            )
                            get_app().invalidate()

                            # Wait for the user to resolve conflicts
                            self.conflict_resolution_event.wait()
                            return self.resolutions
                    return {}

                # Run sync with progress updates
                def progress_updater(message, counts=None):
                    if not self.sync_cancelled:
                        self.progress_text = message

                        # Update counts if provided
                        if counts:
                            self.papers_total = counts.get("papers_total", 0)
                            self.papers_processed = counts.get("papers_processed", 0)
                            self.collections_total = counts.get("collections_total", 0)
                            self.collections_processed = counts.get(
                                "collections_processed", 0
                            )
                            self.pdfs_total = counts.get("pdfs_total", 0)
                            self.pdfs_processed = counts.get("pdfs_processed", 0)

                        # Update percentage based on step
                        steps = [
                            "Creating remote directory",
                            "Checking remote database",
                            "Detecting conflicts",
                            "Synchronizing papers",
                            "Synchronizing collections",
                            "Synchronizing PDF files",
                            "Finalizing sync",
                        ]
                        for i, step in enumerate(steps):
                            if step in message:
                                self.progress_percentage = int(
                                    ((i + 1) / len(steps)) * 100
                                )
                                break
                        # Debug delay to see progress bar (0.5s as requested)
                        import time

                        time.sleep(0.2)
                        get_app().invalidate()

                sync_service = SyncService(
                    self.local_path,
                    self.remote_path,
                    progress_callback=progress_updater,
                    log_callback=self.log_callback,
                )
                self.sync_result = sync_service.sync(
                    conflict_resolver=conflict_resolver,
                    auto_sync_mode=self.auto_sync_mode,
                )

                if not self.sync_cancelled:
                    self.sync_complete = True
                    self.progress_percentage = 100
                    self.progress_text = "Sync completed"

                    # Update status bar immediately if status updater is provided
                    if self.status_updater:
                        if self.sync_result.errors:
                            self.status_updater(
                                f"Sync completed with errors: {self.sync_result.errors[0]}",
                                "error",
                            )
                        elif self.sync_result.has_conflicts():
                            self.status_updater(
                                "Sync completed with conflicts resolved", "success"
                            )
                        else:
                            self.status_updater("Finalizing sync", "success")

                    # Auto-show summary after sync completion
                    if self.sync_result:
                        self.show_summary = True

                    get_app().invalidate()

            except Exception as e:
                if not self.sync_cancelled:
                    self.sync_complete = True
                    self.progress_text = f"Sync failed: {str(e)}"
                    get_app().invalidate()

        self.sync_thread = threading.Thread(target=sync_worker, daemon=True)
        self.sync_thread.start()

    def get_initial_focus(self):
        """Return the initial focus element."""
        return self.cancel_button

    def _handle_close(self):
        """Handle close button press."""
        if self.sync_complete or self.sync_cancelled:
            self.callback(self.sync_result if self.sync_complete else None)
        else:
            # Cancel sync immediately
            self.sync_cancelled = True
            self.progress_text = "Sync cancelled"
            # Close dialog immediately on cancel
            self.callback(None)

    def __pt_container__(self):
        return self.dialog
