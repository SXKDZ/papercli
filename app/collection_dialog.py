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
        self.cursor_position = 0  # Track cursor position within edit_text

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
                    # Show edit cursor with special edit styling and cursor indicator at the correct position
                    text_before_cursor = self.edit_text[:self.cursor_position]
                    text_after_cursor = self.edit_text[self.cursor_position:]
                    display_text = f"✎ {text_before_cursor}|{text_after_cursor}"
                    # Pad the text to highlight the full row width
                    padding = " " * max(0, 40 - len(display_text))
                    result.append(("class:editing", display_text + padding))
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
        def handle_enter(event):
            if self.editing_mode:
                # Save edit when in editing mode
                if self.edit_text.strip():
                    if 0 <= self.selected_index < len(self.items):
                        old_item = self.items[self.selected_index]
                        self.items[self.selected_index] = self.edit_text.strip()
                        if self.on_edit:
                            self.on_edit(old_item, self.edit_text.strip())
                    self.editing_mode = False
                    self.edit_text = ""
                    self.cursor_position = 0
                    self._trigger_select()
            elif self.editable:
                # Enter edit mode when not editing
                current = self.get_current_item()
                if current:
                    self.editing_mode = True
                    self.edit_text = current
                    self.cursor_position = len(current)  # Start cursor at end

        @kb.add("escape")
        def escape_edit(event):
            if self.editing_mode:
                self.editing_mode = False
                self.edit_text = ""
                self.cursor_position = 0
            else:
                # Pass escape to parent
                event.app.layout.focus_previous()

        @kb.add("c-s")  # Ctrl+S to save edit (kept for compatibility)
        def save_edit(event):
            if self.editing_mode and self.edit_text.strip():
                if 0 <= self.selected_index < len(self.items):
                    old_item = self.items[self.selected_index]
                    self.items[self.selected_index] = self.edit_text.strip()
                    if self.on_edit:
                        self.on_edit(old_item, self.edit_text.strip())
                self.editing_mode = False
                self.edit_text = ""
                self.cursor_position = 0
                self._trigger_select()

        @kb.add("left")
        def move_cursor_left(event):
            if self.editing_mode and self.cursor_position > 0:
                self.cursor_position -= 1

        @kb.add("right")
        def move_cursor_right(event):
            if self.editing_mode and self.cursor_position < len(self.edit_text):
                self.cursor_position += 1

        @kb.add("home")
        def move_cursor_home(event):
            if self.editing_mode:
                self.cursor_position = 0

        @kb.add("end")
        def move_cursor_end(event):
            if self.editing_mode:
                self.cursor_position = len(self.edit_text)

        @kb.add("backspace")
        def handle_backspace(event):
            if self.editing_mode and self.cursor_position > 0:
                self.edit_text = self.edit_text[:self.cursor_position-1] + self.edit_text[self.cursor_position:]
                self.cursor_position -= 1

        @kb.add("delete")
        def handle_delete(event):
            if self.editing_mode and self.cursor_position < len(self.edit_text):
                self.edit_text = self.edit_text[:self.cursor_position] + self.edit_text[self.cursor_position+1:]

        @kb.add("c-c")  # Ctrl+C to cancel edit
        def cancel_edit(event):
            if self.editing_mode:
                self.editing_mode = False
                self.edit_text = ""
                self.cursor_position = 0

        # Handle text input during editing
        @kb.add("<any>")
        def handle_character(event):
            if self.editing_mode and event.data and len(event.data) == 1:
                char = event.data
                if char.isprintable():
                    # Insert character at cursor position
                    self.edit_text = self.edit_text[:self.cursor_position] + char + self.edit_text[self.cursor_position:]
                    self.cursor_position += 1

        # Add tab navigation for the dialog (only when not editing)
        @kb.add("tab")
        def handle_tab_navigation(event):
            if not self.editing_mode and hasattr(self, 'parent_dialog'):
                try:
                    dialog = self.parent_dialog
                    dialog.current_focus_index = (dialog.current_focus_index + 1) % len(dialog.focusable_components)
                    event.app.layout.focus(dialog.focusable_components[dialog.current_focus_index])
                except Exception:
                    # Fallback to normal tab behavior
                    pass

        @kb.add("s-tab")  # Shift+Tab
        def handle_shift_tab_navigation(event):
            if not self.editing_mode and hasattr(self, 'parent_dialog'):
                try:
                    dialog = self.parent_dialog
                    dialog.current_focus_index = (dialog.current_focus_index - 1) % len(dialog.focusable_components)
                    event.app.layout.focus(dialog.focusable_components[dialog.current_focus_index])
                except Exception:
                    # Fallback to normal shift+tab behavior
                    pass

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
        self.collections_list.parent_dialog = self  # Add reference to parent

        self.papers_in_collection_list = EditableList(
            [], on_select=self.on_paper_select, editable=False
        )
        self.papers_in_collection_list.parent_dialog = self  # Add reference to parent

        all_paper_titles = [
            p.title[:50] + "..." if len(p.title) > 50 else p.title for p in papers
        ]
        self.other_papers_list = EditableList(
            all_paper_titles, on_select=self.on_paper_select, editable=False
        )
        self.other_papers_list.parent_dialog = self  # Add reference to parent

        # Paper details display
        self.paper_details = TextArea(
            text="Select a paper to view details",
            read_only=True,
            height=Dimension(min=3, max=3),
            wrap_lines=True,
        )

        # Action buttons between lists
        add_button = Button(text="←", handler=self.add_paper_to_collection)
        remove_button = Button(text="→", handler=self.remove_paper_from_collection)

        button_container = HSplit(
            [
                Window(height=2),  # More spacer
                add_button,
                Window(height=2),  # More spacer
                remove_button,
                Window(height=2),  # More spacer
            ],
            width=Dimension(min=3, preferred=3, max=3),
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
                Button(text="Discard", handler=self.discard_changes),
                Button(text="Close", handler=self.cancel),
            ],
            width=Dimension(min=140, preferred=160),
            with_background=False,
        )
        
        # Add dialog key bindings directly to the dialog
        self.dialog.container.key_bindings = self._create_dialog_key_bindings()

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

        @kb.add("escape")
        def quit_dialog(event):
            # Close the dialog when escape is pressed
            self.cancel()

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
            # Create a compact one-liner citation format
            authors = paper.author_names or "Unknown Authors"
            title = paper.title
            venue = paper.venue_display or "Unknown Venue"
            year = paper.year or "N/A"
            paper_type = paper.paper_type or "Unknown"
            
            # Format as: Authors, "Title," Venue, Type. Date.
            # Truncate long fields to fit in one line
            if len(authors) > 60:
                authors = authors[:57] + "..."
            if len(title) > 80:
                title = title[:77] + "..."
            if len(venue) > 40:
                venue = venue[:37] + "..."
            
            # Create citation-style format
            citation = f'{authors}, "{title}," {venue}'
            
            # Add type and date if available
            if paper_type != "Unknown":
                citation += f", vol. {paper_type}"
            if year != "N/A":
                citation += f". {year}"
            citation += "."
            
            self.paper_details.text = citation
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

    def discard_changes(self):
        """Discard all changes without saving."""
        # Clear all pending changes
        self.collection_changes.clear()
        self.paper_moves.clear()
        self.new_collections.clear()
        
        if self.status_bar:
            self.status_bar.set_status("Changes discarded")

    def cancel(self):
        """Cancel changes and close dialog."""
        self.callback(None)

    def __pt_container__(self):
        return self.dialog
