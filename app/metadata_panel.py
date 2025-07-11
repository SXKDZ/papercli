"""
Interactive metadata update panel for papers.
"""

from typing import List, Dict, Any, Optional
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl, BufferControl
from prompt_toolkit.widgets import Frame
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.shortcuts import message_dialog, button_dialog
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style

from .models import Paper


class MetadataPanel:
    """Interactive metadata update panel."""

    def __init__(self, papers: List[Paper]):
        self.papers = papers
        self.current_field = 0
        self.changes = {}
        self.editing_field = False
        self.fields = [
            ("title", "Title"),
            ("author_names", "Authors"),
            ("venue_full", "Venue (Full)"),
            ("venue_acronym", "Venue (Acronym)"),
            ("year", "Year"),
            ("abstract", "Abstract"),
            ("pdf_path", "PDF Path"),
            ("notes", "Notes"),
            ("paper_type", "Type"),
        ]

        # Create edit buffer for inline editing
        self.edit_buffer = Buffer()

        self.setup_layout()
        self.setup_key_bindings()
        self.setup_application()

    def get_current_value(self, field_name: str) -> str:
        """Get current value for a field."""
        if len(self.papers) == 1:
            paper = self.papers[0]
            value = getattr(paper, field_name, "")
            return str(value) if value is not None else ""
        else:
            # Multiple papers - show placeholder
            return f"<Multiple papers - {len(self.papers)} papers>"

    def get_preview_text(self) -> FormattedText:
        """Get preview text for current state."""
        text = []

        # Header
        if len(self.papers) == 1:
            text.append(
                ("class:header", f"Editing: {self.papers[0].title[:60]}...\n\n")
            )
        else:
            text.append(("class:header", f"Editing {len(self.papers)} papers\n\n"))

        # Fields
        for i, (field_name, field_label) in enumerate(self.fields):
            current_value = self.get_current_value(field_name)
            changed_value = self.changes.get(field_name)

            # Highlight current field
            if i == self.current_field:
                style = "class:selected"
                prefix = "► "
            else:
                style = "class:field"
                prefix = "  "

            # Show field name
            text.append((style, f"{prefix}{field_label:<15}: "))

            # Show value or edit indicator
            if self.editing_field and i == self.current_field:
                text.append(
                    (
                        "class:editing",
                        "[EDITING - Press Enter to save, Escape to cancel]",
                    )
                )
            elif changed_value is not None:
                text.append(("class:changed", f"{changed_value} "))
                text.append(("class:original", f"(was: {current_value[:40]}...)"))
            else:
                text.append(
                    (
                        "class:value",
                        current_value[:60] + ("..." if len(current_value) > 60 else ""),
                    )
                )

            text.append(("", "\n"))

        # Instructions
        text.append(("", "\n"))
        text.append(("class:help", "Controls:\n"))
        text.append(("class:help", "  ↑↓: Navigate fields\n"))
        text.append(("class:help", "  Enter: Edit field\n"))
        text.append(("class:help", "  Del: Clear field\n"))
        text.append(("class:help", "  Ctrl+S: Save changes\n"))
        text.append(("class:help", "  Ctrl+R: Reset changes\n"))
        text.append(("class:help", "  Esc: Cancel\n"))

        if self.changes:
            text.append(("", "\n"))
            text.append(
                ("class:warning", f"You have {len(self.changes)} unsaved changes")
            )

        return FormattedText(text)

    def setup_layout(self):
        """Setup the layout."""
        self.preview_window = Window(
            content=FormattedTextControl(text=lambda: self.get_preview_text()),
            wrap_lines=True,
        )

        # Edit window for inline editing
        self.edit_window = Window(
            content=BufferControl(buffer=self.edit_buffer), height=3
        )

        # Conditional edit window that only shows when editing
        edit_container = ConditionalContainer(
            content=Frame(self.edit_window, title="Edit Field"),
            filter=Condition(lambda: self.editing_field),
        )

        self.layout = Layout(
            HSplit(
                [Frame(self.preview_window, title="Metadata Editor"), edit_container]
            )
        )

    def setup_key_bindings(self):
        """Setup key bindings."""
        self.kb = KeyBindings()

        @self.kb.add("up")
        def move_up(event):
            if not self.editing_field and self.current_field > 0:
                self.current_field -= 1
                event.app.invalidate()

        @self.kb.add("down")
        def move_down(event):
            if not self.editing_field and self.current_field < len(self.fields) - 1:
                self.current_field += 1
                event.app.invalidate()

        @self.kb.add("enter")
        def handle_enter(event):
            if self.editing_field:
                # Save the edited value
                field_name, field_label = self.fields[self.current_field]
                new_value = self.edit_buffer.text
                original_value = self.get_current_value(field_name)

                if new_value != original_value:
                    self.changes[field_name] = new_value
                elif field_name in self.changes:
                    # Remove from changes if reverted to original
                    del self.changes[field_name]

                # Exit edit mode
                self.editing_field = False
                self.edit_buffer.text = ""
                event.app.invalidate()
            else:
                # Enter edit mode
                field_name, field_label = self.fields[self.current_field]
                current_value = self.changes.get(
                    field_name, self.get_current_value(field_name)
                )

                self.editing_field = True
                self.edit_buffer.text = current_value if len(self.papers) == 1 else ""
                event.app.invalidate()

                # Focus the edit buffer
                event.app.layout.focus(self.edit_buffer)

        @self.kb.add("delete")
        def clear_field(event):
            field_name, field_label = self.fields[self.current_field]
            self.changes[field_name] = ""
            event.app.invalidate()

        @self.kb.add("c-s")
        def save_changes(event):
            if self.changes:
                # Confirm changes
                changes_text = "\n".join(
                    [f"  {field}: {value}" for field, value in self.changes.items()]
                )
                confirm = button_dialog(
                    title="Confirm Changes",
                    text=f"Apply the following changes to {len(self.papers)} paper(s)?\n\n{changes_text}",
                    buttons=[
                        ("yes", "Yes, apply changes"),
                        ("no", "No, continue editing"),
                    ],
                ).run()

                if confirm == "yes":
                    event.app.exit(result=self.changes)
            else:
                message_dialog(title="No Changes", text="No changes to save.").run()

        @self.kb.add("c-r")
        def reset_changes(event):
            if self.changes:
                confirm = button_dialog(
                    title="Reset Changes",
                    text="Are you sure you want to reset all changes?",
                    buttons=[("yes", "Yes, reset"), ("no", "No, keep changes")],
                ).run()

                if confirm == "yes":
                    self.changes.clear()
                    event.app.invalidate()

        @self.kb.add("escape")
        def handle_escape(event):
            if self.editing_field:
                # Cancel edit mode without saving
                self.editing_field = False
                self.edit_buffer.text = ""
                event.app.invalidate()
            elif self.changes:
                confirm = button_dialog(
                    title="Unsaved Changes",
                    text="You have unsaved changes. Exit without saving?",
                    buttons=[
                        ("yes", "Yes, exit without saving"),
                        ("no", "No, continue editing"),
                    ],
                ).run()

                if confirm == "yes":
                    event.app.exit(result=None)
            else:
                event.app.exit(result=None)

    def setup_application(self):
        """Setup the application."""
        style = Style(
            [
                ("header", "bold #ffffff bg:#4a90e2"),
                ("selected", "bold #ffffff bg:#007acc"),
                ("field", "#ffffff"),
                ("value", "#aaaaaa"),
                ("changed", "bold #00ff00"),
                ("original", "#888888 italic"),
                ("editing", "bold #ffff00 bg:#8800aa"),
                ("help", "#00aa00"),
                ("warning", "bold #ff8800"),
            ]
        )

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=style,
            full_screen=True,
            mouse_support=False,
        )

    def show(self) -> Optional[Dict[str, Any]]:
        """Show the metadata panel and return changes or None if cancelled."""
        return self.app.run()


def show_metadata_panel(papers: List[Paper]) -> Optional[Dict[str, Any]]:
    """Show metadata panel for papers."""
    panel = MetadataPanel(papers)
    return panel.show()
