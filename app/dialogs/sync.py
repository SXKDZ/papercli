"Sync-related dialogs for conflict resolution and sync summaries."

import difflib
import os
import threading
from io import StringIO
from typing import Callable, Dict, List

from prompt_toolkit.application import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, UIContent, UIControl, Window
from prompt_toolkit.layout.containers import ConditionalContainer, ScrollOffsets
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..services import SyncConflict, SyncService


class ConflictDisplayControl(UIControl):
    """A UI control to display sync conflicts with a side-by-side, word-level diff."""

    def __init__(self, get_conflict_info_func: Callable[[], tuple]):
        self.get_conflict_info_func = get_conflict_info_func

    def _create_diff_text(
        self, local_str: str, remote_str: str, field_name: str
    ) -> (Text, Text):
        """Generates concise diff showing only differences with context."""
        if local_str == remote_str:
            return Text(local_str, no_wrap=False), Text(remote_str, no_wrap=False)

        local_words = local_str.split()
        remote_words = remote_str.split()
        matcher = difflib.SequenceMatcher(None, local_words, remote_words, autojunk=False)

        local_text = Text(no_wrap=False, justify="left")
        remote_text = Text(no_wrap=False, justify="left")

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                # Get context around difference
                context_start = max(0, min(i1, j1) - 5)
                local_end = min(len(local_words), i2 + 5)
                remote_end = min(len(remote_words), j2 + 5)
                
                local_snippet = local_words[context_start:local_end]
                remote_snippet = remote_words[context_start:remote_end]
                
                # Truncate if too long
                if len(local_snippet) > 25:
                    local_snippet = local_snippet[:25]
                if len(remote_snippet) > 25:
                    remote_snippet = remote_snippet[:25]

                self._add_diff_snippet(local_text, remote_text, local_snippet, remote_snippet, context_start > 0)
                break

        return local_text, remote_text

    def _add_diff_snippet(self, local_text, remote_text, local_snippet, remote_snippet, has_prefix):
        """Add diff snippet with highlighting to text objects."""
        if has_prefix:
            local_text.append("... ")
            remote_text.append("... ")

        snippet_matcher = difflib.SequenceMatcher(None, local_snippet, remote_snippet)
        for tag, i1, i2, j1, j2 in snippet_matcher.get_opcodes():
            local_chunk = " ".join(local_snippet[i1:i2])
            remote_chunk = " ".join(remote_snippet[j1:j2])

            if tag == "equal":
                local_text.append(local_chunk + " ")
                remote_text.append(remote_chunk + " ")
            elif tag == "replace":
                local_text.append(local_chunk + " ", style="red")
                remote_text.append(remote_chunk + " ", style="green")
            elif tag == "delete":
                local_text.append(local_chunk + " ", style="red")
            elif tag == "insert":
                remote_text.append(remote_chunk + " ", style="green")

    def create_content(self, width: int, height: int) -> UIContent:
        conflict_info = self.get_conflict_info_func()
        if not conflict_info or not conflict_info[0]:
            return UIContent(
                get_line=lambda i: [("", "No conflict to display")], line_count=1
            )

        conflict, index, total = conflict_info

        output = StringIO()
        console = Console(
            file=output,
            force_terminal=True,
            width=width,
            legacy_windows=False,
            _environ={},
        )

        # --- 1. High-Level Conflict Information ---
        title = conflict.item_id
        paper_id = conflict.local_data.get("id") or conflict.remote_data.get("id")

        header_text = f"Conflict {index} of {total}: {title} (Paper #{paper_id})"
        console.print(Text(header_text, justify="center", style="bold"))
        console.print()

        # --- 2. Side-by-Side Grid for Differences (No Boxes) ---
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=1)

        grid.add_row(Text("LOCAL", style="bold"), Text("REMOTE", style="bold"))
        grid.add_row()  # Spacer

        if conflict.conflict_type == "paper":
            # Exclude internal fields that users shouldn't see in conflicts
            excluded_fields = {"id", "created_at", "updated_at"}
            field_order = [
                "title",
                "authors",
                "abstract",
                "doi",
                "arxiv_id",
                "venue_full",
                "publication_year",
                "notes",
                "tags",
                "read_status",
                "priority",
            ]
            all_fields = field_order + sorted(
                [
                    f
                    for f in conflict.differences.keys()
                    if f not in field_order and f not in excluded_fields
                ]
            )

            for field in all_fields:
                if field not in conflict.differences or field in excluded_fields:
                    continue
                diff = conflict.differences[field]
                local_val, remote_val = str(diff.get("local", "")), str(
                    diff.get("remote", "")
                )
                if local_val == remote_val:
                    continue

                local_content, remote_content = self._create_diff_text(
                    local_val, remote_val, field
                )
                field_title = field.replace("_", " ").title()

                grid.add_row(Text(field_title), Text(field_title))
                grid.add_row(local_content, remote_content)
                grid.add_row()  # Spacer

        elif conflict.conflict_type == "pdf":
            details = {
                "File Size": (
                    f'{conflict.local_data.get("size", "N/A"):,}',
                    f'{conflict.remote_data.get("size", "N/A"):,}',
                ),
                "Modified": (
                    str(conflict.local_data.get("modified", "N/A")),
                    str(conflict.remote_data.get("modified", "N/A")),
                ),
                "Hash": (
                    str(conflict.local_data.get("hash", "N/A")),
                    str(conflict.remote_data.get("hash", "N/A")),
                ),
            }
            for field, (local_val, remote_val) in details.items():
                if local_val == remote_val:
                    continue
                local_text, remote_text = self._create_diff_text(
                    local_val, remote_val, field
                )
                grid.add_row(Text(field), Text(field))
                grid.add_row(local_text, remote_text)
                grid.add_row()

        console.print(grid)

        # --- 3. Conversion to prompt_toolkit format ---
        ansi_output = output.getvalue()
        try:

            formatted_text = to_formatted_text(ANSI(ansi_output))
        except Exception:
            formatted_text = [("", ansi_output)]

        lines = []
        current_line = []
        for style, text in formatted_text:
            text_lines = text.split("\n")
            for i, part in enumerate(text_lines):
                if i > 0:
                    lines.append(current_line)
                    current_line = []
                if part:
                    current_line.append((style, part))
        if current_line:
            lines.append(current_line)

        def get_line(i: int):
            return lines[i] if i < len(lines) else [("", "")]

        return UIContent(get_line=get_line, line_count=len(lines))


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


        self.auto_sync_mode = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"

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
        self.papers_total = 0
        self.collections_total = 0
        self.pdfs_total = 0
        self.should_focus_close = False

        self._setup_key_bindings()
        self._create_layout()
        self.start_sync()

    def _setup_key_bindings(self):
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

        # Conflict resolution keys (only active when conflicts are shown)
        @kb.add("l", eager=True)
        def _(event):
            """Use local version for current conflict."""
            if self.show_conflicts and self.conflicts:
                self._resolve_current("local")

        @kb.add("r", eager=True)
        def _(event):
            """Use remote version for current conflict."""
            if self.show_conflicts and self.conflicts:
                self._resolve_current("remote")

        @kb.add("b", eager=True)
        def _(event):
            """Keep both versions for current conflict."""
            if self.show_conflicts and self.conflicts:
                self._resolve_current("keep_both")

        @kb.add("L", eager=True)
        def _(event):
            """Use local version for all remaining conflicts."""
            if self.show_conflicts:
                self._resolve_all("local")

        @kb.add("R", eager=True)
        def _(event):
            """Use remote version for all remaining conflicts."""
            if self.show_conflicts:
                self._resolve_all("remote")

        @kb.add("A", eager=True)
        def _(event):
            """Keep all versions for all remaining conflicts."""
            if self.show_conflicts:
                self._resolve_all("keep_both")



        self.key_bindings = kb

    def _create_layout(self):
        self.conflict_display = ConflictDisplayControl(
            lambda: (
                (
                    self.conflicts[self.current_conflict_index],
                    self.current_conflict_index + 1,
                    len(self.conflicts),
                )
                if self.show_conflicts and self.conflicts
                else (None, 0, 0)
            )
        )

        self.body_content = HSplit(
            [
                Window(
                    FormattedTextControl(
                        self._get_progress_and_status, show_cursor=False
                    ),
                    height=Dimension(min=5, max=6),
                    wrap_lines=True,
                    align="center",
                ),
                ConditionalContainer(
                    Window(
                        self.conflict_display,
                        height=Dimension(min=15, max=30),
                        wrap_lines=True,
                        scroll_offsets=ScrollOffsets(top=2, bottom=2),
                    ),
                    filter=Condition(lambda: self.show_conflicts),
                ),
                ConditionalContainer(
                    Window(
                        FormattedTextControl(self._get_summary_text),
                        height=Dimension(min=5, max=15),
                        wrap_lines=True,
                        scroll_offsets=ScrollOffsets(top=1, bottom=1),
                    ),
                    filter=Condition(
                        lambda: self.show_summary and self._has_detailed_changes()
                    ),
                ),
                Window(
                    FormattedTextControl(self._get_instructions),
                    height=Dimension(min=2, max=5),
                    wrap_lines=True,
                ),
            ]
        )

        # Create buttons with consistent width
        button_width = 13
        self.cancel_button = Button(text="Close", handler=self._handle_close, width=button_width)

        # Create conflict resolution buttons using a helper
        self.local_button = Button(text="Local", handler=lambda: self._resolve_current("local"), width=button_width)
        self.remote_button = Button(text="Remote", handler=lambda: self._resolve_current("remote"), width=button_width)
        self.keep_both_button = Button(text="Both", handler=lambda: self._resolve_current("keep_both"), width=button_width)
        self.all_local_button = Button(text="All Local", handler=lambda: self._resolve_all("local"), width=button_width)
        self.all_remote_button = Button(text="All Remote", handler=lambda: self._resolve_all("remote"), width=button_width)
        self.all_both_button = Button(text="Keep All", handler=lambda: self._resolve_all("keep_both"), width=button_width)

        # Use all buttons with conditional visibility - simpler approach
        all_buttons = [
            ConditionalContainer(
                self.local_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.remote_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.keep_both_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.all_local_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.all_remote_button, filter=Condition(lambda: self.show_conflicts)
            ),
            ConditionalContainer(
                self.all_both_button, filter=Condition(lambda: self.show_conflicts)
            ),
            self.cancel_button,  # Always visible
        ]

        self.dialog = Dialog(
            title=self._get_dynamic_title,
            body=self.body_content,
            buttons=all_buttons,
            with_background=False,
            modal=True,
            width=Dimension(min=139, max=139),
        )

        # Apply key bindings to dialog

        self.dialog.key_bindings = self.key_bindings


    def _get_dynamic_title(self):
        if self.sync_cancelled:
            return "Syncing with Remote Database - Cancelled"
        elif self.sync_complete:
            if self.sync_result and self.sync_result.errors:
                return "Syncing with Remote Database - Completed with Errors"
            elif self.conflicts and not self.resolutions:
                return "Syncing with Remote Database - Conflicts Found"
            else:
                return "Syncing with Remote Database - Completed Successfully"
        return "Syncing with Remote Database"

    def _resolve_current(self, resolution: str):
        """Resolve the current conflict and move to next unresolved conflict."""
        self._resolve_conflict(resolution)

        # Move to next unresolved conflict
        self._next_unresolved_conflict()
        get_app().invalidate()

    def _resolve_all(self, resolution: str):
        """Resolve all conflicts and complete the sync."""
        for conflict in self.conflicts:
            self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                resolution
            )

        # All conflicts resolved, finish conflict resolution
        self.show_conflicts = False
        # Don't mark as complete yet - let sync service finish applying resolutions
        self.progress_text = "Applying conflict resolutions..."
        self.conflict_resolution_event.set()
        get_app().invalidate()

    def _next_unresolved_conflict(self):
        """Move to next conflict that hasn't been resolved yet."""
        original_index = self.current_conflict_index

        # First try to find next unresolved conflict
        for i in range(self.current_conflict_index + 1, len(self.conflicts)):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                return

        # If no unresolved conflicts after current, look before current
        for i in range(0, self.current_conflict_index):
            conflict = self.conflicts[i]
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            if conflict_id not in self.resolutions:
                self.current_conflict_index = i
                return

        # All conflicts resolved, finish conflict resolution
        self.show_conflicts = False
        # Don't mark as complete yet - let sync service finish applying resolutions
        self.progress_text = "Applying conflict resolutions..."
        self.conflict_resolution_event.set()

    def _get_progress_and_status(self):
        lines = []
        
        # Handle focus change request if needed
        if self.should_focus_close and self.sync_complete and self.show_summary:
            self.should_focus_close = False
            try:
                # Direct focus change - this is called during UI rendering so it's safe
                get_app().layout.focus(self.cancel_button)
            except Exception as e:
                if self.log_callback:
                    self.log_callback("focus_error", f"Failed to focus Close button: {e}")

        # Progress bar
        bar_width = 122
        filled = int((self.progress_percentage / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        percentage_text = f"{self.progress_percentage:>3}%"
        progress_line = f"   [{bar}]  {percentage_text}   \n"
        lines.append(("", progress_line))

        # Status text (close to progress bar)
        if self.sync_cancelled:
            lines.append(("class:progress-message", "Status: Sync was cancelled"))
        elif self.sync_complete and self.sync_result and not self.show_conflicts:
            # Show final summary in the same position as progress status
            lines.append(
                ("class:progress-message", f"Status: {self.sync_result.get_summary()}")
            )
        elif not self.sync_complete or self.show_conflicts:
            if self.show_conflicts:
                progress_with_counts = f"Resolving {len(self.conflicts)} conflicts ({len(self.resolutions)} resolved)"
            else:
                progress_with_counts = self.progress_text
                if "papers" in self.progress_text.lower() and self.papers_total > 0:
                    progress_with_counts = (
                        f"Synchronizing {self.papers_total} papers..."
                    )
                elif (
                    "collections" in self.progress_text.lower()
                    and self.collections_total > 0
                ):
                    progress_with_counts = (
                        f"Synchronizing {self.collections_total} collections..."
                    )
                elif "pdf" in self.progress_text.lower() and self.pdfs_total > 0:
                    progress_with_counts = f"Synchronizing {self.pdfs_total} PDFs..."
                else:
                    progress_with_counts = self.progress_text

            lines.append(("class:progress-message", f"Status: {progress_with_counts}"))

        return lines

    def _get_summary_text(self):
        if not self.sync_result:
            return [("", "No summary available.")]

        lines = []
        # Don't show summary here - it's now shown in progress status
        
        # Show errors if any
        if self.sync_result.errors:
            lines.append(("class:error bold", "ERRORS:"))
            for error in self.sync_result.errors:
                lines.append(("class:error", f"\n  • {error}"))

        # Add detailed changes if available, organized by Local/Remote
        if hasattr(self.sync_result, "detailed_changes") and any(
            self.sync_result.detailed_changes.values()
        ):
            # Add spacing only if there were errors above
            if self.sync_result.errors:
                lines.append(("", "\n"))
            # Separate local and remote changes
            local_changes = {}
            remote_changes = {}

            for change_type, items in self.sync_result.detailed_changes.items():
                if items:
                    local_items = []
                    remote_items = []

                    for item in items:
                        # Remove redundant resolution text
                        clean_item = (
                            item.replace(" (used local version)", "")
                            .replace(" (used remote version)", "")
                            .replace(" (from remote)", "")
                        )

                        if "(used remote version)" in item or "(from remote)" in item:
                            # This was added/updated from remote to local
                            remote_items.append(clean_item)
                        else:
                            # This was added/updated from local to remote
                            local_items.append(clean_item)

                    if local_items:
                        local_changes[change_type] = local_items
                    if remote_items:
                        remote_changes[change_type] = remote_items

            # Display Local changes
            if local_changes:
                lines.append(("class:info bold", "LOCAL → REMOTE:"))
                for change_type, items in local_changes.items():
                    category = change_type.replace("_", " ").title()
                    # Fix PDF capitalization
                    if "Pdfs" in category:
                        category = category.replace("Pdfs", "PDFs")
                    lines.append(("", f"\n  {category}:"))
                    for item in items[:8]:  # Show up to 8 items per category
                        lines.append(("", f"\n    • {item}"))
                    if len(items) > 8:
                        lines.append(("", f"\n    ... and {len(items) - 8} more"))

            # Display Remote changes
            if remote_changes:
                if (
                    local_changes
                ):  # Only add extra spacing if there were local changes above
                    lines.append(("", "\n"))
                    lines.append(("class:info bold", "\nREMOTE → LOCAL:"))
                else:
                    lines.append(("class:info bold", "REMOTE → LOCAL:"))
                for change_type, items in remote_changes.items():
                    category = change_type.replace("_", " ").title()
                    # Fix PDF capitalization
                    if "Pdfs" in category:
                        category = category.replace("Pdfs", "PDFs")
                    lines.append(("", f"\n  {category}:"))
                    for item in items[:8]:  # Show up to 8 items per category
                        lines.append(("", f"\n    • {item}"))
                    if len(items) > 8:
                        lines.append(("", f"\n    ... and {len(items) - 8} more"))


        return lines

    def _has_detailed_changes(self):
        """Check if there are detailed changes or errors to display."""
        if not self.sync_result:
            return False
        # Show summary if there are errors or detailed changes
        return (
            (self.sync_result.errors and len(self.sync_result.errors) > 0) or
            (hasattr(self.sync_result, "detailed_changes") and any(
                self.sync_result.detailed_changes.values()
            ))
        )

    def _get_instructions(self):
        """Get instructions text for the dialog."""
        if self.show_conflicts:
            return [("", "L=Local, R=Remote, B=Both | Shift+L/R/A=All | Esc=Cancel")]
        return []

    def _resolve_conflict(self, resolution: str):
        if self.show_conflicts and self.conflicts:
            conflict = self.conflicts[self.current_conflict_index]
            self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = (
                resolution
            )

    def _handle_close(self):
        if not self.sync_complete:
            self.sync_cancelled = True
        self.callback(self.sync_result if self.sync_complete else None)

    def start_sync(self):
        def sync_worker():
            try:

                def conflict_resolver(conflicts):
                    if conflicts and not self.sync_cancelled:
                        self.conflicts = conflicts
                        if self.auto_sync_mode:
                            return {
                                f"{c.conflict_type}_{c.item_id}": "keep_both"
                                for c in conflicts
                            }

                        self.show_conflicts = True
                        get_app().invalidate()
                        self.conflict_resolution_event.wait()
                        return self.resolutions
                    return {}

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
                    if self.sync_result:
                        # Always show summary after completion, regardless of conflict state
                        self.show_summary = True
                        self.show_conflicts = False
                        # Set flag to focus Close button after UI updates
                        self.should_focus_close = True
                    get_app().invalidate()

            except Exception as e:
                if not self.sync_cancelled:
                    self.sync_complete = True
                    self.progress_text = f"Sync failed: {str(e)}"
                    get_app().invalidate()

        self.sync_thread = threading.Thread(target=sync_worker, daemon=True)
        self.sync_thread.start()

    def get_initial_focus(self):
        return self.cancel_button

    def __pt_container__(self):
        return self.dialog
