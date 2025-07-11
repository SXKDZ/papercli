"""
Advanced collection management dialog with three-column layout.
"""

from typing import List, Optional
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, Frame, TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.dimension import Dimension
from .models import Paper, Collection
from .services import CollectionService


class EditableList:
    """An editable list component where each item becomes a text box when focused."""

    def __init__(self, items: List[str], on_select=None, on_edit=None, editable=True):
        self.items = items[:]
        self.selected_index = 0
        self.on_select = on_select
        self.on_edit = on_edit
        self.editable = editable
        self.editing_mode = False
        self.edit_text = ""

        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            key_bindings=self._get_key_bindings(),
            focusable=True,
        )

    def set_items(self, items: List[str]):
        self.items = items[:]
        self.selected_index = (
            min(self.selected_index, len(self.items) - 1) if self.items else 0
        )
        self._trigger_select()

    def add_item(self, item: str):
        self.items.append(item)
        self._trigger_select()

    def remove_current_item(self):
        if 0 <= self.selected_index < len(self.items):
            del self.items[self.selected_index]
            if self.selected_index >= len(self.items):
                self.selected_index = len(self.items) - 1
            self._trigger_select()

    def get_current_item(self) -> Optional[str]:
        if 0 <= self.selected_index < len(self.items):
            return self.items[self.selected_index]
        return None

    def _trigger_select(self):
        if self.on_select:
            self.on_select(self.get_current_item())

    def _get_formatted_text(self):
        if not self.items:
            return FormattedText([("class:empty", "No items")])

        result = []
        for i, item in enumerate(self.items):
            if i == self.selected_index:
                if self.editing_mode:
                    # Show edit cursor
                    result.append(("class:selected", f"> {self.edit_text}"))
                else:
                    # Show selection
                    result.append(("class:selected", f"> {item}"))
            else:
                result.append(("", f"  {item}"))
            result.append(("", "\n"))
        return FormattedText(result)

    def _get_key_bindings(self):
        kb = KeyBindings()

        @kb.add("up")
        def move_up(event):
            if not self.editing_mode and self.selected_index > 0:
                self.selected_index -= 1
                self._trigger_select()

        @kb.add("down")
        def move_down(event):
            if not self.editing_mode and self.selected_index < len(self.items) - 1:
                self.selected_index += 1
                self._trigger_select()

        @kb.add("enter")
        def enter_edit(event):
            if self.editable and not self.editing_mode:
                current = self.get_current_item()
                if current:
                    self.editing_mode = True
                    self.edit_text = current

        @kb.add("escape")
        def escape_edit(event):
            if self.editing_mode:
                self.editing_mode = False
                self.edit_text = ""
            else:
                # Pass escape to parent
                event.app.layout.focus_previous()

        @kb.add("c-s")  # Ctrl+S to save edit
        def save_edit(event):
            if self.editing_mode and self.edit_text.strip():
                if 0 <= self.selected_index < len(self.items):
                    old_item = self.items[self.selected_index]
                    self.items[self.selected_index] = self.edit_text.strip()
                    if self.on_edit:
                        self.on_edit(old_item, self.edit_text.strip())
                self.editing_mode = False
                self.edit_text = ""
                self._trigger_select()

        @kb.add("backspace")
        def handle_backspace(event):
            if self.editing_mode:
                self.edit_text = self.edit_text[:-1]

        @kb.add("delete")
        def handle_delete(event):
            if self.editing_mode:
                # Delete doesn't change text at cursor in this simple implementation
                pass

        @kb.add("c-c")  # Ctrl+C to cancel edit
        def cancel_edit(event):
            if self.editing_mode:
                self.editing_mode = False
                self.edit_text = ""

        # Handle text input during editing
        @kb.add("<any>")
        def handle_character(event):
            if self.editing_mode and event.data and len(event.data) == 1:
                char = event.data
                if char.isprintable():
                    self.edit_text += char

        return kb

    def __pt_container__(self):
        return Window(content=self.control)


class CollectionDialog:
    """A comprehensive collection management dialog with three columns."""

    def __init__(
        self,
        collections: List[Collection],
        papers: List[Paper],
        callback,
        status_bar=None,
    ):
        self.callback = callback
        self.status_bar = status_bar
        self.all_collections = collections
        self.all_papers = papers
        self.current_collection = None
        self.collection_service = CollectionService()

        # Track changes for saving
        self.collection_changes = {}  # {old_name: new_name}
        self.paper_moves = (
            []
        )  # [(paper_id, collection_name, action)] where action is 'add' or 'remove'
        self.new_collections = []  # [collection_name]

        # Initialize lists
        collection_names = [c.name for c in collections] + ["+ New Collection"]
        self.collections_list = EditableList(
            collection_names,
            on_select=self.on_collection_select,
            on_edit=self.on_collection_edit,
        )

        self.papers_in_collection_list = EditableList(
            [], on_select=self.on_paper_select, editable=False
        )

        all_paper_titles = [
            p.title[:50] + "..." if len(p.title) > 50 else p.title for p in papers
        ]
        self.other_papers_list = EditableList(
            all_paper_titles, on_select=self.on_paper_select, editable=False
        )

        # Paper details display
        self.paper_details = TextArea(
            text="Select a paper to view details",
            read_only=True,
            height=Dimension(min=4, max=6),
            wrap_lines=True,
        )

        # Action buttons between lists
        add_button = Button(text="← Add", handler=self.add_paper_to_collection)
        remove_button = Button(
            text="Remove →", handler=self.remove_paper_from_collection
        )

        button_container = HSplit(
            [
                Window(height=2),  # More spacer
                add_button,
                Window(height=2),  # More spacer
                remove_button,
                Window(height=2),  # More spacer
            ],
            width=Dimension(min=15, preferred=18),
        )

        # Main layout with three columns
        main_body = VSplit(
            [
                # Column 1: Collections
                Frame(
                    title="Collections",
                    body=self.collections_list,
                    width=Dimension(min=30, preferred=35),
                ),
                # Column 2: Papers in selected collection
                Frame(
                    title="Papers in Collection",
                    body=self.papers_in_collection_list,
                    width=Dimension(min=35, preferred=45),
                ),
                # Buttons between columns 2 and 3
                button_container,
                # Column 3: All other papers
                Frame(
                    title="All Papers",
                    body=self.other_papers_list,
                    width=Dimension(min=35, preferred=45),
                ),
            ]
        )

        # Help text
        help_text = Window(
            content=FormattedTextControl(
                text="Collections: Enter=Edit, Ctrl+S=Save, Esc=Cancel | Navigation: Tab=Next Column, Shift+Tab=Previous"
            ),
            height=1,
        )

        # Complete dialog layout
        dialog_body = HSplit(
            [
                help_text,
                main_body,
                # Paper details at bottom
                Frame(title="Paper Details", body=self.paper_details),
            ]
        )

        # Store references to focusable components for TAB navigation
        self.focusable_components = [
            self.collections_list,
            self.papers_in_collection_list,
            self.other_papers_list,
        ]
        self.current_focus_index = 0

        # Create dialog
        self.dialog = Dialog(
            title="Collection Management",
            body=dialog_body,
            buttons=[
                Button(text="Save", handler=self.save_changes),
                Button(text="Save & Close", handler=self.save_and_close),
                Button(text="Cancel", handler=self.cancel),
            ],
            width=Dimension(min=120, preferred=140),
            with_background=True,
            key_bindings=self._create_dialog_key_bindings(),
        )

        # Initialize with first collection if available
        if collections:
            self.on_collection_select(collections[0].name)

    def _create_dialog_key_bindings(self):
        """Create key bindings for dialog navigation."""
        kb = KeyBindings()

        @kb.add("tab")
        def focus_next(event):
            self.current_focus_index = (self.current_focus_index + 1) % len(
                self.focusable_components
            )
            event.app.layout.focus(self.focusable_components[self.current_focus_index])

        @kb.add("s-tab")  # Shift+Tab
        def focus_previous(event):
            self.current_focus_index = (self.current_focus_index - 1) % len(
                self.focusable_components
            )
            event.app.layout.focus(self.focusable_components[self.current_focus_index])

        return kb

    def on_collection_select(self, collection_name: str):
        """Handle collection selection."""
        if not collection_name:
            return

        if collection_name == "+ New Collection":
            # Clear papers for new collection
            self.current_collection = None
            self.papers_in_collection_list.set_items([])
            self.other_papers_list.set_items(
                [
                    p.title[:50] + "..." if len(p.title) > 50 else p.title
                    for p in self.all_papers
                ]
            )
            return

        # Find the selected collection
        self.current_collection = next(
            (c for c in self.all_collections if c.name == collection_name), None
        )
        if not self.current_collection:
            return

        # Update papers lists
        papers_in_collection = [
            p.title[:50] + "..." if len(p.title) > 50 else p.title
            for p in self.current_collection.papers
        ]
        papers_in_collection_ids = {p.id for p in self.current_collection.papers}
        other_papers = [
            p.title[:50] + "..." if len(p.title) > 50 else p.title
            for p in self.all_papers
            if p.id not in papers_in_collection_ids
        ]

        self.papers_in_collection_list.set_items(papers_in_collection)
        self.other_papers_list.set_items(other_papers)

    def on_collection_edit(self, old_name: str, new_name: str):
        """Handle collection name editing."""
        if not new_name.strip():
            return

        new_name = new_name.strip()

        if old_name == "+ New Collection":
            # Create new collection
            if (
                new_name not in [c.name for c in self.all_collections]
                and new_name not in self.new_collections
            ):
                self.new_collections.append(new_name)
                # Update the collections list display
                current_names = (
                    [c.name for c in self.all_collections]
                    + self.new_collections
                    + ["+ New Collection"]
                )
                self.collections_list.set_items(current_names)
        else:
            # Rename existing collection
            if new_name != old_name:
                # Check if new name already exists
                existing_names = [
                    c.name for c in self.all_collections if c.name != old_name
                ] + self.new_collections
                if new_name not in existing_names:
                    self.collection_changes[old_name] = new_name
                    # Update the collection in memory
                    collection = next(
                        (c for c in self.all_collections if c.name == old_name), None
                    )
                    if collection:
                        collection.name = new_name
                    # Update the collections list display
                    current_names = (
                        [c.name for c in self.all_collections]
                        + self.new_collections
                        + ["+ New Collection"]
                    )
                    self.collections_list.set_items(current_names)

    def on_paper_select(self, paper_title: str):
        """Handle paper selection to show details."""
        if not paper_title:
            self.paper_details.text = "Select a paper to view details"
            return

        # Find paper by title (handle truncated titles)
        paper = None
        for p in self.all_papers:
            display_title = p.title[:50] + "..." if len(p.title) > 50 else p.title
            if display_title == paper_title:
                paper = p
                break

        if paper:
            details = [
                f"Title: {paper.title}",
                f"Authors: {paper.author_names}",
                f"Year: {paper.year or 'N/A'}",
                f"Venue: {paper.venue_display}",
                f"Type: {paper.paper_type or 'N/A'}",
            ]
            if paper.abstract:
                abstract = (
                    paper.abstract[:200] + "..."
                    if len(paper.abstract) > 200
                    else paper.abstract
                )
                details.append(f"Abstract: {abstract}")

            self.paper_details.text = "\n".join(details)
        else:
            self.paper_details.text = "Paper details not found"

    def add_paper_to_collection(self):
        """Add selected paper from other papers to current collection."""
        paper_title = self.other_papers_list.get_current_item()
        collection_name = self.collections_list.get_current_item()

        if (
            not paper_title
            or not collection_name
            or collection_name == "+ New Collection"
        ):
            return

        # Find the paper ID
        paper = None
        for p in self.all_papers:
            display_title = p.title[:50] + "..." if len(p.title) > 50 else p.title
            if display_title == paper_title:
                paper = p
                break

        if paper:
            # Track the change
            self.paper_moves.append((paper.id, collection_name, "add"))

            # Move paper between lists
            self.other_papers_list.remove_current_item()
            self.papers_in_collection_list.add_item(paper_title)

    def remove_paper_from_collection(self):
        """Remove selected paper from current collection."""
        paper_title = self.papers_in_collection_list.get_current_item()
        collection_name = self.collections_list.get_current_item()

        if (
            not paper_title
            or not collection_name
            or collection_name == "+ New Collection"
        ):
            return

        # Find the paper ID
        paper = None
        for p in self.all_papers:
            display_title = p.title[:50] + "..." if len(p.title) > 50 else p.title
            if display_title == paper_title:
                paper = p
                break

        if paper:
            # Track the change
            self.paper_moves.append((paper.id, collection_name, "remove"))

            # Move paper between lists
            self.papers_in_collection_list.remove_current_item()
            self.other_papers_list.add_item(paper_title)

    def save_changes(self):
        """Save changes without closing dialog."""
        try:
            saved_count = 0
            error_count = 0

            # 1. Create new collections
            for collection_name in self.new_collections:
                collection = self.collection_service.create_collection(collection_name)
                if collection:
                    self.all_collections.append(collection)
                    saved_count += 1
                else:
                    error_count += 1

            # 2. Rename collections
            for old_name, new_name in self.collection_changes.items():
                success = self.collection_service.update_collection_name(
                    old_name, new_name
                )
                if success:
                    saved_count += 1
                else:
                    error_count += 1

            # 3. Add/remove papers from collections
            for paper_id, collection_name, action in self.paper_moves:
                if action == "add":
                    success = self.collection_service.add_paper_to_collection(
                        paper_id, collection_name
                    )
                else:  # remove
                    success = self.collection_service.remove_paper_from_collection(
                        paper_id, collection_name
                    )

                if success:
                    saved_count += 1
                else:
                    error_count += 1

            # Clear the change tracking
            self.collection_changes.clear()
            self.paper_moves.clear()
            self.new_collections.clear()

            # Update status bar directly
            if self.status_bar:
                if error_count == 0:
                    if saved_count > 0:
                        self.status_bar.set_success(
                            f"Successfully saved {saved_count} changes to collections"
                        )
                    else:
                        self.status_bar.set_status("No changes to save")
                else:
                    self.status_bar.set_warning(
                        f"Saved {saved_count} changes, {error_count} errors occurred"
                    )

        except Exception as e:
            if self.status_bar:
                self.status_bar.set_error(f"Error saving changes: {str(e)}")

    def save_and_close(self):
        """Save changes and close dialog."""
        # Save changes first
        self.save_changes()

        # Return updated collections to the callback
        changes = {"collections": self.all_collections, "action": "save", "close": True}
        self.callback(changes)

    def cancel(self):
        """Cancel changes and close dialog."""
        self.callback(None)

    def __pt_container__(self):
        return self.dialog
