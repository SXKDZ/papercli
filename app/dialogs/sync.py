"""Sync-related dialogs for conflict resolution and sync summaries."""

from typing import Dict, List, Optional

from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Dimension,
    HSplit,
    Layout,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.containers import ScrollOffsets
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Frame

from ..services.sync_service import SyncConflict, SyncResult


class SyncConflictDialog:
    """Dialog for resolving sync conflicts."""
    
    def __init__(self, conflicts: List[SyncConflict]):
        self.conflicts = conflicts
        self.current_conflict_index = 0
        self.resolutions: Dict[str, str] = {}  # conflict_id -> resolution
        self.result = None  # Will be set to resolutions dict or None if cancelled
        self.use_all_local = False
        self.use_all_remote = False
        
        # Create key bindings
        self.bindings = KeyBindings()
        self._setup_key_bindings()
        
        # Create layout
        self.layout = self._create_layout()
        
    def _setup_key_bindings(self):
        """Setup key bindings for the dialog."""
        
        @self.bindings.add("escape")
        def _(event):
            """Cancel the dialog."""
            self.result = None
            get_app().exit()
            
        @self.bindings.add("q")
        def _(event):
            """Cancel the dialog."""
            self.result = None
            get_app().exit()
            
        @self.bindings.add("l")
        def _(event):
            """Use local version for current conflict."""
            if self.conflicts:
                conflict = self.conflicts[self.current_conflict_index]
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = "local"
                self._next_conflict()
                
        @self.bindings.add("r")
        def _(event):
            """Use remote version for current conflict."""
            if self.conflicts:
                conflict = self.conflicts[self.current_conflict_index]
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = "remote"
                self._next_conflict()
                
        @self.bindings.add("a", "l")
        def _(event):
            """Use all local versions."""
            self.use_all_local = True
            for conflict in self.conflicts:
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = "local"
            self.result = self.resolutions
            get_app().exit()
            
        @self.bindings.add("a", "r")
        def _(event):
            """Use all remote versions."""
            self.use_all_remote = True
            for conflict in self.conflicts:
                self.resolutions[f"{conflict.conflict_type}_{conflict.item_id}"] = "remote"
            self.result = self.resolutions
            get_app().exit()
            
        @self.bindings.add("n")
        def _(event):
            """Next conflict."""
            self._next_conflict()
            
        @self.bindings.add("p")
        def _(event):
            """Previous conflict."""
            self._prev_conflict()
            
    def _next_conflict(self):
        """Move to next conflict or finish if all resolved."""
        if self.current_conflict_index < len(self.conflicts) - 1:
            self.current_conflict_index += 1
        else:
            # All conflicts resolved
            self.result = self.resolutions
            get_app().exit()
            
    def _prev_conflict(self):
        """Move to previous conflict."""
        if self.current_conflict_index > 0:
            self.current_conflict_index -= 1
            
    def _create_layout(self):
        """Create the dialog layout."""
        if not self.conflicts:
            return Layout(
                Frame(
                    Window(
                        FormattedTextControl("No conflicts to resolve."),
                        align=WindowAlign.CENTER
                    ),
                    title="Sync Conflicts"
                )
            )
            
        # Current conflict info
        conflict_info = Window(
            FormattedTextControl(self._get_conflict_text),
            wrap_lines=True,
            scroll_offsets=ScrollOffsets(top=1, bottom=1)
        )
        
        # Navigation info
        nav_info = Window(
            FormattedTextControl(self._get_navigation_text),
            height=Dimension.exact(1),
            align=WindowAlign.CENTER
        )
        
        # Instructions
        instructions = Window(
            FormattedTextControl(self._get_instructions_text),
            height=Dimension.exact(6),
            align=WindowAlign.LEFT
        )
        
        return Layout(
            Frame(
                HSplit([
                    nav_info,
                    Window(height=Dimension.exact(1)),  # Spacer
                    conflict_info,
                    Window(height=Dimension.exact(1)),  # Spacer
                    instructions
                ]),
                title="Resolve Sync Conflicts"
            )
        )
        
    def _get_conflict_text(self):
        """Get the current conflict details as formatted text."""
        if not self.conflicts:
            return "No conflicts."
            
        conflict = self.conflicts[self.current_conflict_index]
        
        lines = []
        lines.append(("class:conflict-header", f"Conflict: {conflict.conflict_type.title()} #{conflict.item_id}"))
        lines.append(("", "\n\n"))
        
        if conflict.conflict_type == "paper":
            lines.extend(self._format_paper_conflict(conflict))
        elif conflict.conflict_type == "pdf":
            lines.extend(self._format_pdf_conflict(conflict))
            
        return lines
        
    def _format_paper_conflict(self, conflict: SyncConflict):
        """Format paper conflict details."""
        lines = []
        
        for field, diff in conflict.differences.items():
            lines.append(("class:field-name", f"{field.replace('_', ' ').title()}:"))
            lines.append(("", "\n"))
            lines.append(("class:local-value", f"  Local:  {diff['local'] or 'None'}"))
            lines.append(("", "\n"))
            lines.append(("class:remote-value", f"  Remote: {diff['remote'] or 'None'}"))
            lines.append(("", "\n\n"))
            
        return lines
        
    def _format_pdf_conflict(self, conflict: SyncConflict):
        """Format PDF conflict details."""
        lines = []
        lines.append(("class:field-name", f"PDF File: {conflict.item_id}"))
        lines.append(("", "\n\n"))
        
        local_info = conflict.local_data
        remote_info = conflict.remote_data
        
        lines.append(("class:local-value", "Local:"))
        lines.append(("", "\n"))
        lines.append(("", f"  Size: {local_info.get('size', 0):,} bytes"))
        lines.append(("", "\n"))
        lines.append(("", f"  Modified: {local_info.get('modified', 'Unknown')}"))
        lines.append(("", "\n"))
        lines.append(("", f"  MD5: {local_info.get('hash', 'Unknown')}"))
        lines.append(("", "\n\n"))
        
        lines.append(("class:remote-value", "Remote:"))
        lines.append(("", "\n"))
        lines.append(("", f"  Size: {remote_info.get('size', 0):,} bytes"))
        lines.append(("", "\n"))
        lines.append(("", f"  Modified: {remote_info.get('modified', 'Unknown')}"))
        lines.append(("", "\n"))
        lines.append(("", f"  MD5: {remote_info.get('hash', 'Unknown')}"))
        lines.append(("", "\n\n"))
        
        return lines
        
    def _get_navigation_text(self):
        """Get navigation information."""
        total = len(self.conflicts)
        current = self.current_conflict_index + 1
        return f"Conflict {current} of {total}"
        
    def _get_instructions_text(self):
        """Get instruction text."""
        return [
            ("class:instruction", "Choose which version to keep:"),
            ("", "\n"),
            ("class:key", "L"), ("", " - Use Local version"),
            ("", "\n"),
            ("class:key", "R"), ("", " - Use Remote version"),
            ("", "\n"),
            ("class:key", "AL"), ("", " - Use All Local (resolve all remaining)"),
            ("", "\n"),
            ("class:key", "AR"), ("", " - Use All Remote (resolve all remaining)"),
            ("", "\n"),
            ("class:key", "ESC/Q"), ("", " - Cancel sync"),
        ]


class SyncSummaryDialog:
    """Dialog for showing sync operation summary."""
    
    def __init__(self, result: SyncResult):
        self.result = result
        
        # Create key bindings
        self.bindings = KeyBindings()
        self._setup_key_bindings()
        
        # Create layout
        self.layout = self._create_layout()
        
    def _setup_key_bindings(self):
        """Setup key bindings for the dialog."""
        
        @self.bindings.add("escape")
        @self.bindings.add("q")
        @self.bindings.add("enter")
        def _(event):
            """Close the dialog."""
            get_app().exit()
            
    def _create_layout(self):
        """Create the dialog layout."""
        # Summary content
        summary_content = Window(
            FormattedTextControl(self._get_summary_text),
            wrap_lines=True,
            scroll_offsets=ScrollOffsets(top=1, bottom=1)
        )
        
        # Instructions
        instructions = Window(
            FormattedTextControl([
                ("class:instruction", "Press "), 
                ("class:key", "ESC"), 
                ("class:instruction", " or "), 
                ("class:key", "Enter"), 
                ("class:instruction", " to close")
            ]),
            height=Dimension.exact(1),
            align=WindowAlign.CENTER
        )
        
        return Layout(
            Frame(
                HSplit([
                    summary_content,
                    Window(height=Dimension.exact(1)),  # Spacer
                    instructions
                ]),
                title="Sync Summary"
            )
        )
        
    def _get_summary_text(self):
        """Get sync summary as formatted text."""
        lines = []
        
        # Overall status
        if self.result.cancelled:
            lines.append(("class:error", "❌ Sync was cancelled"))
            lines.append(("", "\n\n"))
            lines.append(("", "No changes were made to local or remote data."))
            return lines
            
        if self.result.errors:
            lines.append(("class:error", "❌ Sync completed with errors"))
            lines.append(("", "\n\n"))
            for error in self.result.errors:
                lines.append(("class:error", f"Error: {error}"))
                lines.append(("", "\n"))
            lines.append(("", "\n"))
            
        if not self.result.errors and not self.result.has_conflicts():
            lines.append(("class:success", "✅ Sync completed successfully"))
            lines.append(("", "\n\n"))
            
        # Changes summary
        changes = self.result.changes_applied
        total_changes = sum(changes.values())
        
        if total_changes == 0:
            lines.append(("", "No changes were needed - local and remote are in sync."))
        else:
            lines.append(("class:summary-header", "Changes Applied:"))
            lines.append(("", "\n\n"))
            
            if changes['papers_added'] > 0:
                lines.append(("class:change-item", f"📄 {changes['papers_added']} papers added"))
                lines.append(("", "\n"))
            if changes['papers_updated'] > 0:
                lines.append(("class:change-item", f"📝 {changes['papers_updated']} papers updated"))
                lines.append(("", "\n"))
            if changes['collections_added'] > 0:
                lines.append(("class:change-item", f"📁 {changes['collections_added']} collections added"))
                lines.append(("", "\n"))
            if changes['collections_updated'] > 0:
                lines.append(("class:change-item", f"📂 {changes['collections_updated']} collections updated"))
                lines.append(("", "\n"))
            if changes['pdfs_copied'] > 0:
                lines.append(("class:change-item", f"📎 {changes['pdfs_copied']} PDF files synchronized"))
                lines.append(("", "\n"))
                
        # Conflicts resolved
        if self.result.has_conflicts():
            lines.append(("", "\n"))
            lines.append(("class:warning", f"⚠️  {len(self.result.conflicts)} conflicts were encountered"))
            lines.append(("", "\n"))
            lines.append(("", "These conflicts need to be resolved before sync can complete."))
            
        return lines


# Style for sync dialogs
sync_dialog_style = Style.from_dict({
    'conflict-header': '#00aaff bold',
    'field-name': '#ffaa00 bold',
    'local-value': '#00ff00',
    'remote-value': '#ff6600',
    'instruction': '#ffffff',
    'key': '#00aaff bold',
    'success': '#00ff00 bold',
    'error': '#ff0000 bold',
    'warning': '#ffaa00 bold',
    'summary-header': '#00aaff bold',
    'change-item': '#00ff00',
})