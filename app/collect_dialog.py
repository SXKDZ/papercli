"""
Advanced collection management dialog with three-column layout.
"""

import traceback
from typing import List, Optional
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, Frame, TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.dimension import Dimension
from .models import Paper, Collection
from .services import CollectionService, PaperService


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
            show_cursor=False,
        )

        # Create the window once and reuse it.
        self.window = Window(content=self.control)

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
            self.on_select(self)

    def _get_formatted_text(self):
        if not self.items:
            return FormattedText([("class:empty", "No items")])

        result = []
        for i, item in enumerate(self.items):
            # Check if this item has pending changes (needs italic styling)
            is_pending_change = False
            if hasattr(self, "parent_dialog"):
                if self == self.parent_dialog.collections_list:
                    # Check if collection name is in pending renames
                    is_pending_change = (
                        item in self.parent_dialog.pending_collection_renames
                    )
                elif (
                    self == self.parent_dialog.papers_in_collection_list
                    or self == self.parent_dialog.other_papers_list
                ):
                    # Check if paper title is in pending moves
                    is_pending_change = item in self.parent_dialog.pending_paper_moves

            if i == self.selected_index:
                if self.editing_mode:
                    # Show edit cursor with special edit styling and cursor indicator at the correct position
                    text_before_cursor = self.edit_text[: self.cursor_position]
                    text_after_cursor = self.edit_text[self.cursor_position :]
                    display_text = f"✎ {text_before_cursor}|{text_after_cursor}"
                    # Pad the text to highlight the full row width
                    padding = " " * max(0, 40 - len(display_text))
                    result.append(("class:editing", display_text + padding))
                else:
                    # Show selection with italic if pending change
                    if is_pending_change:
                        result.append(("class:selected italic", f"> {item}"))
                    else:
                        result.append(("class:selected", f"> {item}"))
            else:
                # Show regular item with italic if pending change
                if is_pending_change:
                    result.append(("italic", f"  {item}"))
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
                # Allow escape to propagate to parent dialog
                pass

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
                self.edit_text = (
                    self.edit_text[: self.cursor_position - 1]
                    + self.edit_text[self.cursor_position :]
                )
                self.cursor_position -= 1

        @kb.add("delete")
        def handle_delete(event):
            if self.editing_mode and self.cursor_position < len(self.edit_text):
                self.edit_text = (
                    self.edit_text[: self.cursor_position]
                    + self.edit_text[self.cursor_position + 1 :]
                )

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
                    self.edit_text = (
                        self.edit_text[: self.cursor_position]
                        + char
                        + self.edit_text[self.cursor_position :]
                    )
                    self.cursor_position += 1

        return kb

    def __pt_container__(self):
        return self.window


class CollectDialog:
    """A comprehensive collection management dialog with three columns."""

    def __init__(
        self,
        collections: List[Collection],
        papers: List[Paper],
        callback,
        collection_service: CollectionService,
        paper_service: PaperService,
        status_bar=None,
        log_callback=None,
        error_display_callback=None,
    ):
        self.callback = callback
        self.status_bar = status_bar
        self.all_collections = collections
        self.all_papers = papers
        self.current_collection = None
        self.collection_service = collection_service
        self.paper_service = paper_service
        self.log_callback = log_callback
        self.error_display_callback = error_display_callback

        # Track changes for saving
        self.collection_changes = {}  # {old_name: new_name}
        self.paper_moves = (
            []
        )  # [(paper_id, collection_name, action)] where action is 'add' or 'remove'
        self.new_collections = []  # [collection_name]

        # Track pending changes for styling
        self.pending_collection_renames = (
            set()
        )  # Collection names that have been renamed
        self.pending_paper_moves = set()  # Paper titles that have been moved

        # Initialize focus tracking early
        self.current_focus_index = 0

        # Initialize buttons
        self.save_button = Button(text="Save", handler=self.save_and_close)
        self.purge_button = Button(text="Purge", handler=self.purge_empty_collections)
        self.close_button = Button(text="Cancel", handler=self.cancel)

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

        # Select the first collection by default to populate paper lists
        if self.collections_list.items:
            self.collections_list.selected_index = 0
            self.on_collection_select(self.collections_list)

        # Action buttons between lists
        self.add_button = Button(
            text="← Add", handler=self.add_paper_to_collection, width=9
        )
        self.remove_button = Button(
            text="Del →", handler=self.remove_paper_from_collection, width=9
        )

        button_container = HSplit(
            [
                Window(height=2),  # More spacer
                self.add_button,
                Window(height=2),  # More spacer
                self.remove_button,
                Window(height=2),  # More spacer
            ],
            width=Dimension(min=12, preferred=14, max=14),
        )

        # Column 1: Collections
        self.collections_frame = Frame(
            title="Collections",
            body=self.collections_list,
            width=Dimension(min=30, preferred=35),
        )
        # Column 2: Papers in selected collection
        self.papers_in_collection_frame = Frame(
            title="Papers in Collection",
            body=self.papers_in_collection_list,
            width=Dimension(min=35, preferred=45),
        )
        # Column 3: All other papers
        self.other_papers_frame = Frame(
            title="All Papers",
            body=self.other_papers_list,
            width=Dimension(min=35, preferred=45),
        )

        # Main layout with three columns
        main_body = VSplit(
            [
                self.collections_frame,
                self.papers_in_collection_frame,
                button_container,
                self.other_papers_frame,
            ]
        )

        # Help text
        help_text = Window(
            content=FormattedTextControl(
                text="Collections: Enter=Edit  Ctrl+S=Save  Esc=Cancel  Ctrl+A=Add  Ctrl+D=Delete | Navigation: Tab=Next Column  Shift+Tab=Previous"
            ),
            height=1,
        )

        # Complete dialog layout
        self.dialog_body = HSplit(
            [
                help_text,
                Window(height=1),  # Add spacing line after help text
                main_body,
                # Paper details at bottom
                Frame(title="Paper Details", body=self.paper_details),
            ]
        )

        button_row = VSplit(
            [
                self.purge_button,
                Window(width=3),
                self.save_button,
                Window(width=3),
                self.close_button,
            ]
        )

        # Create dialog with key bindings
        self.dialog = Dialog(
            title="Collection Management",
            body=self.dialog_body,
            buttons=[button_row],
            width=Dimension(min=140, preferred=160),
            with_background=False,
            modal=True,
        )

        # Apply key bindings directly to dialog container - simple approach
        self.dialog.container.key_bindings = self._create_dialog_key_bindings()

        # Store references to focusable components and their frames for TAB navigation
        self.focusable_components = [
            self.collections_list,
            self.papers_in_collection_list,
            self.add_button,
            self.remove_button,
            self.other_papers_list,
            self.purge_button,
            self.save_button,
            self.close_button,
        ]
        self.component_frames = {
            self.collections_list: self.collections_frame,
            self.papers_in_collection_list: self.papers_in_collection_frame,
            self.other_papers_list: self.other_papers_frame,
        }

        # Set initial focus style and update detail page
        self._set_focus_style()
        self._update_detail_page_on_focus_change()

    def get_initial_focus(self):
        """Return the initial component to be focused."""
        return self.collections_list.__pt_container__()

    def _set_focus_style(self):
        """Update the border style and titles of frames based on current focus."""
        from prompt_toolkit.application import get_app

        # Define base titles and focus symbols
        base_titles = {
            self.collections_list: "Collections",
            self.papers_in_collection_list: "Papers in Collection",
            self.other_papers_list: "All Papers",
        }
        focus_symbol = "▶"

        # Get currently focused component
        focused_component = self.focusable_components[self.current_focus_index] if self.current_focus_index < len(self.focusable_components) else None
        
        for component, frame in self.component_frames.items():
            base_title = base_titles[component]

            if component == focused_component:
                # Focused: add symbol, make bold, set focused style
                frame.title = f"{focus_symbol} {base_title}"
                frame.style = "class:frame.focused bold"
            else:
                # Not focused: plain title, no bold, set unfocused style
                frame.title = base_title
                frame.style = "class:frame.unfocused"

        # Invalidate the app to redraw the UI with new styles
        app = get_app()
        if app:
            app.invalidate()

    def _update_detail_page_on_focus_change(self):
        """Update the detail page based on the currently focused column."""
        if self.current_focus_index == 0:
            # Collections column is focused - clear detail page
            self.paper_details.text = "Select a paper to view details"
        elif self.current_focus_index == 1:
            # Papers in collection column is focused
            if self.papers_in_collection_list.get_current_item():
                self.on_paper_select(self.papers_in_collection_list)
            else:
                self.paper_details.text = "No papers in this collection"
        elif self.current_focus_index == 4:
            # Other papers column is focused
            if self.other_papers_list.get_current_item():
                self.on_paper_select(self.other_papers_list)
            else:
                self.paper_details.text = "No papers available"
        else:
            # Buttons are focused - keep current detail page
            pass

    def _create_dialog_key_bindings(self):
        """Create key bindings for dialog navigation."""
        kb = KeyBindings()

        @kb.add("tab", eager=True)
        def focus_next(event):
            self.current_focus_index = (self.current_focus_index + 1) % len(
                self.focusable_components
            )
            editable_list = self.focusable_components[self.current_focus_index]
            focused_window = editable_list.__pt_container__()
            event.app.layout.focus(focused_window)
            self._set_focus_style()
            self._update_detail_page_on_focus_change()

        @kb.add("s-tab", eager=True)  # Shift+Tab
        def focus_previous(event):
            self.current_focus_index = (self.current_focus_index - 1) % len(
                self.focusable_components
            )

            editable_list = self.focusable_components[self.current_focus_index]
            focused_window = editable_list.__pt_container__()
            event.app.layout.focus(focused_window)
            self._set_focus_style()
            self._update_detail_page_on_focus_change()

        @kb.add("escape", eager=True)
        def quit_dialog(event):
            # Close the dialog when escape is pressed
            self.cancel()

        @kb.add("c-a", eager=True)  # Ctrl+A
        def add_paper_key(event):
            self.add_paper_to_collection()

        @kb.add("c-d", eager=True)  # Ctrl+D  
        def remove_paper_key(event):
            self.remove_paper_from_collection()

        @kb.add("c-s", eager=True)  # Ctrl+S to save and close
        def save_key(event):
            self.save_and_close()

        return kb

    def on_collection_select(self, editable_list_instance):
        """Handle collection selection."""
        collection_name = editable_list_instance.get_current_item()
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
            # Clear detail page when no collection is selected
            self.paper_details.text = "Select a paper to view details"
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

        # Update detail page based on currently focused column
        if (
            self.current_focus_index == 1
            and self.papers_in_collection_list.get_current_item()
        ):
            # Papers in collection column is focused
            self.on_paper_select(self.papers_in_collection_list)
        elif (
            self.current_focus_index == 4 and self.other_papers_list.get_current_item()
        ):
            # Other papers column is focused
            self.on_paper_select(self.other_papers_list)
        else:
            # Collection column is focused, clear detail page
            self.paper_details.text = "Select a paper to view details"

    def on_collection_edit(self, old_name: str, new_name: str):
        """Handle collection name editing."""
        if not new_name.strip():
            return

        new_name = new_name.strip()

        if old_name == "+ New Collection":
            # Create new collection
            if (
                new_name != "+ New Collection"  # Reject placeholder name
                and new_name not in [c.name for c in self.all_collections]
                and new_name not in self.new_collections
            ):
                self.new_collections.append(new_name)
                # Add to pending changes for styling
                self.pending_collection_renames.add(new_name)
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
                    # Add to pending changes for styling
                    self.pending_collection_renames.add(new_name)
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

    def on_paper_select(self, editable_list_instance):
        """Handle paper selection to show details."""
        paper_title = editable_list_instance.get_current_item()
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

        # Find the paper object from all_papers
        paper_to_add = None
        for p in self.all_papers:
            display_title = p.title[:50] + "..." if len(p.title) > 50 else p.title
            if display_title == paper_title:
                paper_to_add = p
                break

        if not paper_to_add:
            self.status_bar.set_warning(f"Paper '{paper_title}' not found.")
            return

        # Find the collection object from all_collections
        target_collection = None
        for c in self.all_collections:
            if c.name == collection_name:
                target_collection = c
                break

        if not target_collection:
            self.status_bar.set_warning(f"Collection '{collection_name}' not found.")
            return

        # Check if paper is already in the collection (compare by ID, not object reference)
        paper_ids_in_collection = {p.id for p in target_collection.papers}
        if paper_to_add.id in paper_ids_in_collection:
            self.status_bar.set_status(
                f"Paper '{paper_title}' is already in '{collection_name}'."
            )
            return

        # Track the change
        self.paper_moves.append((paper_to_add.id, collection_name, "add"))

        # Add to pending changes for styling
        self.pending_paper_moves.add(paper_title)

        # Update in-memory collection for immediate UI feedback
        target_collection.papers.append(paper_to_add)

        # Move paper between lists in UI
        self.other_papers_list.remove_current_item()
        self.papers_in_collection_list.add_item(paper_title)
        self.status_bar.set_status(
            f"Added '{paper_title}' to '{collection_name}'. Press Save to confirm."
        )

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

        # Find the paper object from all_papers
        paper_to_remove = None
        for p in self.all_papers:
            display_title = p.title[:50] + "..." if len(p.title) > 50 else p.title
            if display_title == paper_title:
                paper_to_remove = p
                break

        if not paper_to_remove:
            self.status_bar.set_warning(f"Paper '{paper_title}' not found.")
            return

        # Find the collection object from all_collections
        target_collection = None
        for c in self.all_collections:
            if c.name == collection_name:
                target_collection = c
                break

        if not target_collection:
            self.status_bar.set_warning(f"Collection '{collection_name}' not found.")
            return

        # Check if paper is actually in the collection (compare by ID, not object reference)
        paper_ids_in_collection = {p.id for p in target_collection.papers}
        if paper_to_remove.id not in paper_ids_in_collection:
            self.status_bar.set_status(
                f"Paper '{paper_title}' is not in '{collection_name}'."
            )
            return

        # Track the change
        self.paper_moves.append((paper_to_remove.id, collection_name, "remove"))

        # Add to pending changes for styling
        self.pending_paper_moves.add(paper_title)

        # Update in-memory collection for immediate UI feedback (find by ID, not object reference)
        paper_to_remove_from_collection = next(
            (p for p in target_collection.papers if p.id == paper_to_remove.id), None
        )
        if paper_to_remove_from_collection:
            target_collection.papers.remove(paper_to_remove_from_collection)

        # Move paper between lists in UI
        self.papers_in_collection_list.remove_current_item()
        self.other_papers_list.add_item(paper_title)
        self.status_bar.set_status(
            f"Removed '{paper_title}' from '{collection_name}'. Press Save to confirm."
        )

    def save_changes(self):
        """Save changes without closing dialog."""
        try:
            saved_count = 0

            # 1. Create new collections
            for collection_name in self.new_collections:
                try:
                    collection = self.collection_service.create_collection(
                        collection_name
                    )
                    if collection:
                        self.all_collections.append(collection)
                        saved_count += 1
                        # Log the creation
                        if self.log_callback:
                            self.log_callback(
                                "collection",
                                f"Created new collection '{collection_name}'",
                            )
                    else:
                        self.error_display_callback(
                            "Collection Creation Error",
                            f"Failed to create collection '{collection_name}'.",
                            "Name might already exist.",
                        )
                except Exception as e:
                    self.error_display_callback(
                        "Collection Creation Error",
                        f"Failed to create collection '{collection_name}'",
                        traceback.format_exc(),
                    )

            # 2. Rename collections
            for old_name, new_name in self.collection_changes.items():
                try:
                    success = self.collection_service.update_collection_name(
                        old_name, new_name
                    )
                    if success:
                        saved_count += 1
                        # Log the rename
                        if self.log_callback:
                            self.log_callback(
                                "collection",
                                f"Renamed collection from '{old_name}' to '{new_name}'",
                            )
                    else:
                        self.error_display_callback(
                            "Collection Rename Error",
                            f"Failed to rename collection from '{old_name}' to '{new_name}'.",
                            f"New name '{new_name}' might already exist or old collection '{old_name}' not found.",
                        )
                except Exception as e:
                    self.error_display_callback(
                        "Collection Rename Error",
                        f"Failed to rename collection from '{old_name}' to '{new_name}'",
                        traceback.format_exc(),
                    )

            # 3. Add/remove papers from collections
            for paper_id, collection_name, action in self.paper_moves:
                try:
                    # Find paper title for logging
                    paper_title = "Unknown"
                    paper = next((p for p in self.all_papers if p.id == paper_id), None)
                    if paper:
                        paper_title = paper.title

                    if action == "add":
                        success = self.collection_service.add_paper_to_collection(
                            paper_id, collection_name
                        )
                        if success:
                            saved_count += 1
                            # Log the addition
                            if self.log_callback:
                                self.log_callback(
                                    "collection",
                                    f"Added paper '{paper_title}' to collection '{collection_name}'",
                                )
                        else:
                            self.error_display_callback(
                                "Add Paper to Collection Error",
                                f"Failed to add paper (ID: {paper_id}) to collection '{collection_name}'.",
                                f"Paper '{paper_title}' might already be in collection or collection '{collection_name}' not found.",
                            )
                    else:  # remove
                        success = self.collection_service.remove_paper_from_collection(
                            paper_id, collection_name
                        )
                        if success:
                            saved_count += 1
                            # Log the removal
                            if self.log_callback:
                                self.log_callback(
                                    "collection",
                                    f"Removed paper '{paper_title}' from collection '{collection_name}'",
                                )
                        else:
                            self.error_display_callback(
                                "Remove Paper from Collection Error",
                                f"Failed to remove paper (ID: {paper_id}) from collection '{collection_name}'.",
                                f"Paper '{paper_title}' might not be in collection or collection '{collection_name}' not found.",
                            )
                except Exception as e:
                    self.error_display_callback(
                        "Collection Paper Processing Error",
                        f"Failed to process paper (ID: {paper_id}) for collection '{collection_name}' ({action})",
                        traceback.format_exc(),
                    )

            # Clear the change tracking
            self.collection_changes.clear()
            self.paper_moves.clear()
            self.new_collections.clear()

            # Clear pending changes for styling
            self.pending_collection_renames.clear()
            self.pending_paper_moves.clear()

            # Reload all collections and papers to reflect changes
            self.all_collections = self.collection_service.get_all_collections()
            self.all_papers = self.paper_service.get_all_papers()

            # Update the collections list UI with the new collections
            current_names = [c.name for c in self.all_collections] + [
                "+ New Collection"
            ]
            self.collections_list.set_items(current_names)

            # Re-select the current collection to refresh the paper lists
            if self.current_collection:
                # Find the reloaded version of the current collection
                reloaded_current_collection = next(
                    (
                        c
                        for c in self.all_collections
                        if c.name == self.current_collection.name
                    ),
                    None,
                )
                if reloaded_current_collection:
                    self.current_collection = reloaded_current_collection
                    # Find the index of the current collection in the updated list
                    collection_index = next(
                        (
                            i
                            for i, name in enumerate(current_names)
                            if name == self.current_collection.name
                        ),
                        0,
                    )
                    self.collections_list.selected_index = collection_index
                    self.on_collection_select(
                        self.collections_list
                    )  # Re-trigger UI update
            else:
                # If no current collection, refresh the "other papers" list
                all_paper_titles = [
                    p.title[:50] + "..." if len(p.title) > 50 else p.title
                    for p in self.all_papers
                ]
                self.other_papers_list.set_items(all_paper_titles)

            # Update status bar directly
            if self.status_bar:
                if saved_count > 0:
                    self.status_bar.set_success(
                        f"Successfully saved {saved_count} changes to collections"
                    )
                else:
                    self.status_bar.set_status("No changes to save")

        except Exception as e:
            if self.status_bar:
                self.status_bar.set_error(
                    f"An unexpected error occurred during save: {str(e)}"
                )
            if self.error_display_callback:
                self.error_display_callback(
                    "Collection Save Error",
                    "Failed to save collection changes",
                    traceback.format_exc(),
                )

    def save_and_close(self):
        """Save changes and close dialog."""
        # Save changes first
        self.save_changes()

        # Return updated collections to the callback
        changes = {"collections": self.all_collections, "action": "save", "close": True}
        self.callback(changes)

        # Refresh the UI after saving and closing
        self.on_collection_select(self.collections_list)

    def cancel(self):
        """Cancel changes and close dialog."""
        self.callback(None)

    def purge_empty_collections(self):
        """Purge all empty collections."""
        from .services import CollectionService
        
        try:
            collection_service = CollectionService()
            deleted_count = collection_service.purge_empty_collections()
            
            if deleted_count == 0:
                # Set status message - no collections to purge
                if self.status_bar:
                    self.status_bar.set_status("No empty collections found to purge.")
            else:
                # Collections were purged, refresh the dialog
                if self.status_bar:
                    self.status_bar.set_success(f"Purged {deleted_count} empty collection{'s' if deleted_count != 1 else ''}.")
                
                # Refresh collections list
                collection_service = CollectionService()
                self.all_collections = collection_service.get_all_collections()
                current_names = (
                    [c.name for c in self.all_collections]
                    + self.new_collections
                    + ["+ New Collection"]
                )
                self.collections_list.set_items(current_names)
                # Reset selection to first item
                self.collections_list.current_index = 0
                self.on_collection_select(self.collections_list)
                
        except Exception as e:
            import traceback
            if self.error_display_callback:
                self.error_display_callback(
                    "Collection Purge Error",
                    f"Failed to purge empty collections: {e}",
                    traceback.format_exc()
                )

    def __pt_container__(self):
        return self.dialog
