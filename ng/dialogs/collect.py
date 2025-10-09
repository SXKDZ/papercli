import time
from typing import Any, Callable, Dict, List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Click, MouseDown, MouseUp
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, Rule

from ng.db.models import Collection, Paper
from ng.services import dialog_utils
from ng.services.formatting import format_title_by_words


class CollectDialog(ModalScreen):
    """A modal dialog for managing collections with 3-column layout."""

    DEFAULT_CSS = """
    CollectDialog {
        align: center middle;
        layer: dialog;
    }
    CollectDialog > Container {
        width: 112;
        height: 40;
        max-width: 112;
        max-height: 50;
        border: solid $accent;
        background: $panel;
    }
    /* Title styles */
    CollectDialog .dialog-title,
    CollectDialog .column-title,
    CollectDialog .paper-details-title {
        text-style: bold;
        text-align: center;
        height: 1;
        color: $text;
    }
    CollectDialog .dialog-title {
        background: $accent;
        width: 100%;
    }
    CollectDialog .column-title,
    CollectDialog .paper-details-title {
        background: $accent-darken-1;
    }
    /* Layout containers */
    CollectDialog .top-panel {
        width: 100%;
        height: 1fr;
        margin: 1;
    }
    CollectDialog .column-30 {
        width: 31;
        height: 1fr;
        border: solid $border;
        margin: 0 1 0 0;
        align: center top;
    }
    CollectDialog .column-10 {
        width: 12;
        height: 1fr;
        margin: 1 1;
        align: center middle;
    }
    CollectDialog VerticalScroll {
        height: 1fr;
        scrollbar-size: 1 1;
        overflow-y: auto;
    }
    CollectDialog .paper-details-scroll {
        height: 1fr;
        scrollbar-size: 1 1;
        overflow-y: auto;
    }
    /* Button styles */
    CollectDialog Button {
        height: 3;
        content-align: center middle;
    }
    CollectDialog .action-buttons Button {
        width: 1fr;
        margin: 1 0;
        min-width: 8;
    }
    CollectDialog .bottom-buttons {
        height: 5;
        align: center middle;
    }
    CollectDialog .bottom-buttons Button {
        margin: 0 5;
        min-width: 12;
    }
    /* Collection button row */
    CollectDialog .collection-buttons-row {
        height: 1;
        width: 100%;
        align: center middle;
    }
    CollectDialog .compact-collection-button {
        height: 1;
        width: 5;
        max-width: 5;
        margin: 0 5 0 0;
        padding: 0;
        border: none !important;
        text-align: center;
        background: $surface;
        color: $text;
    }
    CollectDialog .compact-collection-button:last-child {
        margin: 0;
    }
    /* Input styles */
    CollectDialog .new-collection-input {
        height: 3;
        border: solid $border;
    }
    CollectDialog .paper-search-input {
        height: 1;
        border: none;
        background: $surface;
        color: $text;
    }
    CollectDialog .paper-search-input:focus {
        border: none;
        background: $surface-darken-1;
    }
    CollectDialog .edit-collection-input {
        background: $warning;
        color: $text;
        width: 1fr;
        border: none;
        height: 1;
    }
    CollectDialog .edit-collection-input:focus {
        background: $warning-darken-1;
        border: none;
        padding: 0;
        height: 1;
    }
    /* Edit mode */
    CollectDialog .edit-symbol {
        width: 2;
        height: 1;
        background: $warning;
        color: $text;
        content-align: center middle;
        border: none;
        padding: 0;
        margin: 0;
    }
    CollectDialog .editing-container {
        height: 1;
    }
    CollectDialog .changed-collection,
    CollectDialog .changed-paper {
        text-style: italic;
    }
    CollectDialog .paper-details {
        height: 6;
        border: solid $border;
        margin: 1;
    }
    /* Separator between search box and list (thin rule) */
    CollectDialog .list-separator {
        height: 1;
        min-height: 1;
        max-height: 1;
        margin: 0 !important;
        padding: 0 !important;
        border: none;
        color: $border;
        background: transparent;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
        ("f2", "edit_collection", "Edit Collection"),
        ("enter", "edit_collection", "Edit Collection"),
    ]

    # Double-click threshold in seconds
    DOUBLE_CLICK_THRESHOLD_S = 0.5

    selected_collection = reactive(None)
    selected_collection_paper = reactive(None)
    selected_all_paper = reactive(None)
    editing_collection_index = reactive(None)

    def __init__(
        self,
        collections: List[Collection],
        papers: List[Paper],
        callback: Callable[[Dict[str, Any] | None], None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.collections = collections or []
        self.papers = papers or []
        self.callback = callback

        # Track changes
        self.collection_changes = {}  # {old_name: new_name}
        self.paper_moves = []  # [(paper_id, collection_name, action)]
        self.new_collections = []  # [collection_name]
        self.deleted_collections = []  # [collection_name]

        # Track last click times per item for double-click detection
        self._last_click_time: Dict[str, float] = {}
        
        # Track filter text for paper lists
        self.collection_papers_filter = ""
        self.all_papers_filter = ""

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Manage Collections", classes="dialog-title")

            # Main 4-section layout: 30%, 30%, 10%, 30%
            with Vertical(classes="top-panel"):
                with Horizontal():
                    # Column 1: Collections List (30%)
                    with Vertical(classes="column-30"):
                        yield Static("Collections", classes="column-title")
                        with VerticalScroll(
                            classes="list-container", id="collections-scroll"
                        ):
                            yield ListView(id="collections-list")
                        yield Input(
                            placeholder="New collection name",
                            id="new-collection-input",
                            classes="new-collection-input",
                        )
                        with Horizontal(classes="collection-buttons-row"):
                            yield Button(
                                "+",
                                id="add-collection-button",
                                variant="success",
                                classes="compact-collection-button",
                            )
                            yield Button(
                                "-",
                                id="delete-collection-button",
                                variant="error",
                                classes="compact-collection-button",
                            )

                    # Column 2: Papers in Selected Collection (30%)
                    with Vertical(classes="column-30"):
                        yield Static(
                            "Papers in Collection",
                            classes="column-title",
                            id="collection-papers-title",
                        )
                        yield Input(
                            placeholder="Search papers...",
                            id="collection-papers-search",
                            classes="paper-search-input",
                        )
                        yield Rule(classes="list-separator")
                        with VerticalScroll(
                            classes="list-container", id="collection-papers-scroll"
                        ):
                            yield ListView(id="collection-papers-list")

                    # Action buttons (10%)
                    with Vertical(classes="column-10 action-buttons"):
                        yield Button("← Add", id="add-paper-button", variant="primary")
                        yield Button(
                            "Remove →", id="remove-paper-button", variant="warning"
                        )

                    # Column 3: All Remaining Papers (30%)
                    with Vertical(classes="column-30"):
                        yield Static("All Papers", classes="column-title")
                        yield Input(
                            placeholder="Search papers...",
                            id="all-papers-search",
                            classes="paper-search-input",
                        )
                        yield Rule(classes="list-separator")
                        with VerticalScroll(
                            classes="list-container", id="all-papers-scroll"
                        ):
                            yield ListView(id="all-papers-list")

            # Paper Details Panel
            with Vertical(classes="paper-details"):
                yield Static("Paper Details", classes="paper-details-title")
                with VerticalScroll(classes="paper-details-scroll"):
                    yield Static(
                        "Select a paper to view details",
                        id="paper-details-text",
                    )

            # Bottom buttons
            with Horizontal(classes="bottom-buttons"):
                yield Button("Save", id="save-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        self.populate_collections_list()
        self.populate_all_papers_list()
        if self.collections:
            self.select_collection(0)

    def _is_collection_changed(self, collection_name: str) -> bool:
        """Check if a collection has been changed (renamed or is new)."""
        return (
            collection_name in self.collection_changes.values()
            or collection_name in self.new_collections
        )

    def _is_paper_changed(self, paper_id: int) -> bool:
        """Check if a paper has been moved to/from collections."""
        return any(move[0] == paper_id for move in self.paper_moves)
    
    def _is_paper_changed_in_collection(self, paper_id: int, collection_name: str) -> bool:
        """Check if a paper was added to a specific collection in this session."""
        return any(
            move[0] == paper_id and move[1] == collection_name and move[2] == "add"
            for move in self.paper_moves
        )
    
    def _is_paper_changed_in_all_papers(self, paper_id: int, collection_name: str = None) -> bool:
        """Check if a paper was removed from the currently selected collection."""
        if not collection_name:
            return False
        return any(
            move[0] == paper_id and move[1] == collection_name and move[2] == "remove"
            for move in self.paper_moves
        )

    def populate_collections_list(self) -> None:
        """Populate the collections list."""
        collections_list = self.query_one("#collections-list", ListView)
        collections_list.clear()

        timestamp = int(time.time() * 1000)  # Unique timestamp for IDs

        for idx, collection in enumerate(self.collections):
            if self.editing_collection_index == idx:
                # Create editing UI with symbol + input field
                class EditingContainer(Horizontal):
                    def __init__(self, collection_name, edit_idx, edit_timestamp):
                        super().__init__(classes="editing-container")
                        self.collection_name = collection_name
                        self.edit_idx = edit_idx
                        self.edit_timestamp = edit_timestamp

                    def compose(self):
                        yield Static("✏️", classes="edit-symbol")

                        class EditInput(Input):
                            def on_mouse_down(self, event: MouseDown) -> None:
                                # Keep the event local so ListView doesn't steal focus, but allow default selection behavior
                                event.stop()
                                self.focus()

                            def on_mouse_up(self, event: MouseUp) -> None:
                                # Keep the event local; don't cancel default so selection works
                                event.stop()

                            def on_click(self, event: Click) -> None:
                                # Stop propagation so ListItem/ListView doesn't handle it; allow default click behavior
                                event.stop()
                                self.focus()

                        yield EditInput(
                            value=self.collection_name,
                            id=f"edit-collection-{self.edit_idx}-{self.edit_timestamp}",
                            classes="edit-collection-input",
                            disabled=False,
                            placeholder="Enter collection name",
                        )

                edit_container = EditingContainer(collection.name, idx, timestamp)
                item = ListItem(
                    edit_container, id=f"collection-{collection.id}-editing-{timestamp}"
                )
            else:
                # Show label (double-clickable to edit)
                is_changed = self._is_collection_changed(collection.name)
                label_classes = "changed-collection" if is_changed else ""
                label = Label(collection.name, classes=label_classes)
                item = ListItem(label, id=f"collection-{collection.id}-{timestamp}")
            collections_list.append(item)

        # Add new collections that haven't been saved yet
        for new_idx, new_collection_name in enumerate(self.new_collections):
            if new_collection_name not in [c.name for c in self.collections]:
                label = Label(new_collection_name, classes="changed-collection")
                item = ListItem(
                    label, id=f"new-collection-{new_collection_name}-{timestamp}"
                )
                collections_list.append(item)

    def populate_all_papers_list(self) -> None:
        """Populate the all papers list with papers not in the current collection."""
        all_papers_list = self.query_one("#all-papers-list", ListView)
        all_papers_list.clear()

        timestamp = int(time.time() * 1000)  # Millisecond timestamp for uniqueness

        # Get papers that are not in the currently selected collection
        if self.selected_collection:
            collection_paper_ids = {p.id for p in self.selected_collection.papers}
            available_papers = []

            for paper in self.papers:
                if paper.id not in collection_paper_ids:
                    available_papers.append(paper)
        else:
            available_papers = self.papers

        # Apply search filter (case-insensitive partial match on title)
        filter_text = (self.all_papers_filter or "").strip().lower()
        if filter_text:
            def matches(p):
                title = (p.title or "").lower()
                return filter_text in title
            available_papers = [p for p in available_papers if matches(p)]

        # Sort available papers by modified date (newest first)
        sorted_available_papers = sorted(
            available_papers,
            key=lambda p: p.modified_date or p.added_date,
            reverse=True,
        )

        for idx, paper in enumerate(sorted_available_papers):
            title = format_title_by_words(paper.title or "")
            # Only show italic if removed from current collection
            collection_name = self.selected_collection.name if self.selected_collection else None
            is_changed = self._is_paper_changed_in_all_papers(paper.id, collection_name)
            label_classes = "changed-paper" if is_changed else ""
            label = Label(title, classes=label_classes)
            item = ListItem(label, id=f"all-paper-{paper.id}-{idx}-{timestamp}")
            all_papers_list.append(item)

    def populate_collection_papers_list(self, collection: Collection) -> None:
        """Populate papers in the selected collection."""
        collection_papers_list = self.query_one("#collection-papers-list", ListView)
        collection_papers_list.clear()

        # Update title
        title_widget = self.query_one("#collection-papers-title", Static)
        title_widget.update(f"Papers in '{collection.name}'")

        timestamp = int(time.time() * 1000)  # Millisecond timestamp for uniqueness

        # Sort papers by: 1) newly added in this session (top), 2) modified date (newest first)
        def sort_key(paper):
            # Check if this paper was added in the current session
            is_newly_added = self._is_paper_changed_in_collection(paper.id, collection.name)
            if is_newly_added:
                return (0, 0)  # Highest priority - newly added papers go to top
            else:
                # Sort by modified_date or added_date in descending order
                date_value = paper.modified_date or paper.added_date
                return (1, -date_value.timestamp() if date_value else 0)

        # Apply search filter (case-insensitive partial match on title)
        papers_source = collection.papers
        filter_text = (self.collection_papers_filter or "").strip().lower()
        if filter_text:
            def matches(p):
                title = (p.title or "").lower()
                return filter_text in title
            papers_source = [p for p in papers_source if matches(p)]

        sorted_papers = sorted(papers_source, key=sort_key)

        for idx, paper in enumerate(sorted_papers):
            title = format_title_by_words(paper.title or "")
            is_changed = self._is_paper_changed_in_collection(paper.id, collection.name)
            label_classes = "changed-paper" if is_changed else ""
            label = Label(title, classes=label_classes)
            item = ListItem(
                label,
                id=f"collection-paper-{collection.id}-{paper.id}-{idx}-{timestamp}",
            )
            collection_papers_list.append(item)

    def select_collection(self, index: int) -> None:
        """Select a collection and populate its papers."""
        total_collections = len(self.collections) + len(self.new_collections)

        if 0 <= index < total_collections:
            if index < len(self.collections):
                # Selecting an existing collection
                collection = self.collections[index]
                self.selected_collection = collection
                self.populate_collection_papers_list(collection)
            else:
                # Selecting a new collection (it has no papers yet)
                new_collection_index = index - len(self.collections)
                if 0 <= new_collection_index < len(self.new_collections):
                    # Create a temporary collection object for new collections
                    class TempCollection:
                        def __init__(self, name):
                            self.name = name
                            self.papers = []
                            self.id = None

                    collection = TempCollection(
                        self.new_collections[new_collection_index]
                    )
                    self.selected_collection = collection
                    self.populate_collection_papers_list(collection)

            self.populate_all_papers_list()  # Refresh to exclude papers from selected collection

            # Highlight the selected collection
            collections_list = self.query_one("#collections-list", ListView)
            collections_list.index = index

            # Re-apply any active filters after selection change
            # to ensure both lists reflect current filter text
            if self.collection_papers_filter:
                try:
                    self.populate_collection_papers_list(self.selected_collection)
                except Exception:
                    pass
            if self.all_papers_filter:
                try:
                    self.populate_all_papers_list()
                except Exception:
                    pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list selection events."""
        # Ignore list selection changes while editing a collection name
        if self.editing_collection_index is not None:
            try:
                event.prevent_default()
                event.stop()
            except Exception:
                pass
            return
        if event.list_view.id == "collections-list":
            index = event.list_view.index
            total_collections = len(self.collections) + len(self.new_collections)
            if index is not None and 0 <= index < total_collections:
                self.select_collection(index)
        elif event.list_view.id == "collection-papers-list":
            self.selected_collection_paper = event.item
            self.update_paper_details_from_collection_paper(event.item)
        elif event.list_view.id == "all-papers-list":
            self.selected_all_paper = event.item
            self.update_paper_details_from_all_papers(event.item)

    def on_click(self, event: Click) -> None:
        """Handle clicks to detect double-clicks on collection labels."""
        # Skip click processing if we're already in editing mode
        if self.editing_collection_index is not None:
            return

        # Get the clicked widget
        clicked_widget = event.control

        # Check if it's a Label widget inside a ListItem
        if isinstance(clicked_widget, Label):
            list_item = clicked_widget.parent
            if isinstance(list_item, ListItem) and list_item.id:
                if list_item.id.startswith("collection-") and not list_item.id.endswith(
                    "-editing"
                ):
                    if dialog_utils.is_double_click(
                        list_item.id,
                        self._last_click_time,
                        self.DOUBLE_CLICK_THRESHOLD_S,
                    ):

                        # This is a double-click - start editing
                        collections_list = self.query_one("#collections-list", ListView)
                        for idx, item in enumerate(collections_list.children):
                            if item == list_item and idx < len(self.collections):
                                self.editing_collection_index = idx
                                self.populate_collections_list()
                                # Focus the input field after a short delay
                                self.call_after_refresh(self._focus_edit_input, idx)
                                break

    def _focus_edit_input(self, idx: int) -> None:
        """Helper method to focus the edit input field."""
        try:
            # Find the input field with the edit-collection prefix
            for widget in self.query(Input):
                if widget.id and widget.id.startswith(f"edit-collection-{idx}-"):
                    widget.focus()
                    # Select all text for easy editing
                    widget.action_select_all()
                    break
        except Exception:
            pass

    def _is_focus_within_same_editing_row(self, input_widget: Input) -> bool:
        """Return True if current focus is the same edit input or within the same editing row.

        This guards against transient blur when clicking the edit input itself.
        """
        try:
            focused = self.app.focused
            if focused is None:
                return False

            # If focus returned to the same input, definitely ignore blur
            if focused is input_widget:
                return True

            # If focus is another Input with the same edit index, also treat as same row
            if isinstance(focused, Input) and focused.id and input_widget.id:
                try:
                    # IDs are in format: edit-collection-{idx}-{timestamp}
                    focused_parts = focused.id.split("-")
                    input_parts = input_widget.id.split("-")
                    if (
                        len(focused_parts) >= 3
                        and len(input_parts) >= 3
                        and focused_parts[0] == "edit"
                        and input_parts[0] == "edit"
                        and focused_parts[1] == "collection"
                        and input_parts[1] == "collection"
                        and focused_parts[2] == input_parts[2]
                    ):
                        return True
                except Exception:
                    pass

            # Walk parents of focused widget to see if it's inside the same EditingContainer
            try:
                container = input_widget.parent
                node = focused
                while node is not None:
                    if node is container:
                        return True
                    node = node.parent
            except Exception:
                pass

            return False
        except Exception:
            return False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission for collection name editing."""
        if event.input.id and event.input.id.startswith("edit-collection-"):
            self._save_collection_edit(event.input)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter lists live as the user types in search boxes."""
        try:
            if event.input.id == "collection-papers-search":
                self.collection_papers_filter = event.value or ""
                if self.selected_collection:
                    self.populate_collection_papers_list(self.selected_collection)
            elif event.input.id == "all-papers-search":
                self.all_papers_filter = event.value or ""
                self.populate_all_papers_list()
        except Exception:
            # Avoid breaking the dialog if filtering fails for any reason
            pass

    def on_input_blurred(self, event: Input.Blurred) -> None:
        """Handle input losing focus - auto-exit editing mode."""
        if event.input.id and event.input.id.startswith("edit-collection-"):
            input_widget = event.input

            # Delay handling to allow focus to settle (e.g., when clicking inside the input)
            def delayed_handle(*_args):
                try:
                    is_same_row = self._is_focus_within_same_editing_row(input_widget)

                    if is_same_row:
                        # Focus stayed within the same editing row; ignore this blur
                        # Optionally re-focus the input to keep caret visible
                        try:
                            input_widget.focus()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
                # Focus moved outside; proceed to save and exit edit mode
                self._save_collection_edit(input_widget)

            try:
                self.app.call_later(delayed_handle, 0.05)
            except Exception:
                # Fallback: if scheduling fails, handle immediately
                delayed_handle()

    def _save_collection_edit(self, input_widget: Input) -> None:
        """Helper method to save collection name edit and exit editing mode."""
        if not input_widget.id or not input_widget.id.startswith("edit-collection-"):
            return

        # Extract index from ID format: edit-collection-{idx}-{timestamp}
        id_parts = input_widget.id.split("-")

        if len(id_parts) >= 3:
            try:
                idx = int(id_parts[2])  # Get the index part
                new_name = input_widget.value.strip()

                if new_name and idx < len(self.collections):
                    old_name = self.collections[idx].name

                    if new_name != old_name:
                        # Track the change
                        self.collection_changes[old_name] = new_name
                        # Update the collection name locally for display
                        self.collections[idx].name = new_name

                # Exit editing mode
                self.editing_collection_index = None
                self.populate_collections_list()
            except (ValueError, IndexError):
                # Exit editing mode on error
                self.editing_collection_index = None
                self.populate_collections_list()

    def action_edit_collection(self) -> None:
        """Edit the currently selected collection name."""
        collections_list = self.query_one("#collections-list", ListView)
        index = collections_list.index

        if index is not None and 0 <= index < len(self.collections):
            self.editing_collection_index = index
            self.populate_collections_list()
            # Focus the input field after refresh
            self.call_after_refresh(self._focus_edit_input, index)

    def on_key(self, event) -> None:
        """Handle escape key to cancel editing."""
        if event.key == "escape" and self.editing_collection_index is not None:
            self.editing_collection_index = None
            self.populate_collections_list()
            event.prevent_default()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-collection-button":
            self.add_collection()
        elif event.button.id == "delete-collection-button":
            self.delete_selected_collection()
        elif event.button.id == "add-paper-button":
            self.add_paper_to_collection()
        elif event.button.id == "remove-paper-button":
            self.remove_paper_from_collection()
        elif event.button.id == "save-button":
            self.action_save()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def add_collection(self) -> None:
        """Add a new collection."""
        input_widget = self.query_one("#new-collection-input", Input)
        name = input_widget.value.strip()

        if not name:
            return

        if name in [c.name for c in self.collections] + self.new_collections:
            return  # Collection already exists

        self.new_collections.append(name)

        # Refresh the collections list to show the new collection
        self.populate_collections_list()

        # Clear input
        input_widget.value = ""

    def delete_selected_collection(self) -> None:
        """Delete the selected collection."""
        collections_list = self.query_one("#collections-list", ListView)
        # Ensure the selection tracks the current cursor position before deleting
        try:
            collections_list.action_select_cursor()
        except Exception:
            pass
        index = collections_list.index

        if index is not None:
            if index < len(self.collections):
                # Deleting an existing collection
                collection = self.collections.pop(index)

                # Track all papers being removed from this collection
                for paper in list(collection.papers):
                    self.paper_moves.append((paper.id, collection.name, "remove"))

                # Track the collection deletion
                self.deleted_collections.append(collection.name)
            else:
                # Deleting a new collection that hasn't been saved yet
                new_collection_index = index - len(self.collections)
                if 0 <= new_collection_index < len(self.new_collections):
                    # Just remove it from new_collections list
                    del self.new_collections[new_collection_index]

            # Refresh the collections list
            self.populate_collections_list()

            # After deletion, select the next sensible collection if any remain
            total_remaining = len(self.collections) + len(self.new_collections)
            if total_remaining > 0:
                new_index = min(index, total_remaining - 1)
                self.select_collection(new_index)
            else:
                # No collections left; clear panels
                self.selected_collection = None
                self.query_one("#collection-papers-list", ListView).clear()
                title_widget = self.query_one("#collection-papers-title", Static)
                title_widget.update("Papers in Collection")
                self.populate_all_papers_list()

    def add_paper_to_collection(self) -> None:
        """Add selected paper from all papers to the current collection."""
        if not self.selected_collection or not self.selected_all_paper:
            return

        # Extract paper ID from the item ID (format: all-paper-{paper_id}-{idx}-{timestamp})
        id_parts = self.selected_all_paper.id.split("-")
        if len(id_parts) >= 3:
            paper_id = int(id_parts[2])  # Get the paper_id part
        else:
            return  # Invalid ID format
        paper = next((p for p in self.papers if p.id == paper_id), None)

        if paper:
            # Remove paper from collection if it's already there (to avoid duplicates)
            if paper in self.selected_collection.papers:
                self.selected_collection.papers.remove(paper)

            # Track the change
            self.paper_moves.append((paper_id, self.selected_collection.name, "add"))

            # Add paper to the top of the collection for UI display
            self.selected_collection.papers.insert(0, paper)

            # Refresh UI to show the change and italic styling
            self.populate_collection_papers_list(self.selected_collection)
            self.populate_all_papers_list()  # Refresh to show italic styling

    def remove_paper_from_collection(self) -> None:
        """Remove selected paper from the current collection."""
        if not self.selected_collection or not self.selected_collection_paper:
            return

        # Extract paper ID from the item ID (format: collection-paper-{collection_id}-{paper_id}-{idx}-{timestamp})
        id_parts = self.selected_collection_paper.id.split("-")
        if len(id_parts) >= 4:
            paper_id = int(id_parts[3])  # Get the paper_id part
        else:
            return  # Invalid ID format

        # Track the change
        self.paper_moves.append((paper_id, self.selected_collection.name, "remove"))

        # Remove paper from the collection temporarily for UI display
        paper_to_remove = next(
            (p for p in self.selected_collection.papers if p.id == paper_id), None
        )
        if paper_to_remove:
            self.selected_collection.papers.remove(paper_to_remove)

        # Refresh UI to show the change and italic styling
        self.populate_collection_papers_list(self.selected_collection)
        self.populate_all_papers_list()  # Refresh to show italic styling

    def action_save(self) -> None:
        """Save changes and close dialog."""
        # Exit editing mode before saving to ensure changes are captured
        if self.editing_collection_index is not None:
            # Find the current editing input and save its changes
            for widget in self.query(Input):
                if widget.id and widget.id.startswith("edit-collection-"):
                    self._save_collection_edit(widget)
                    break

        result = {
            "collection_changes": self.collection_changes,
            "paper_moves": self.paper_moves,
            "new_collections": self.new_collections,
            "deleted_collections": self.deleted_collections,
        }

        if self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Cancel and close dialog."""
        if self.callback:
            self.callback(None)
        self.dismiss(None)

    def update_paper_details_from_collection_paper(self, item: ListItem) -> None:
        """Update paper details when a paper from collection is selected."""
        if not item:
            self.clear_paper_details()
            return

        # Extract paper ID from the item ID (format: collection-paper-{collection_id}-{paper_id}-{idx}-{timestamp})
        id_parts = item.id.split("-")
        if len(id_parts) >= 4:
            try:
                paper_id = int(id_parts[3])
                paper = next((p for p in self.papers if p.id == paper_id), None)
                if paper:
                    self.show_paper_details(paper)
                else:
                    self.clear_paper_details()
            except (ValueError, IndexError):
                self.clear_paper_details()
        else:
            self.clear_paper_details()

    def update_paper_details_from_all_papers(self, item: ListItem) -> None:
        """Update paper details when a paper from all papers is selected."""
        if not item:
            self.clear_paper_details()
            return

        # Extract paper ID from the item ID (format: all-paper-{paper_id}-{idx}-{timestamp})
        try:
            id_parts = item.id.split("-")
            if len(id_parts) >= 3 and id_parts[0] == "all":
                paper_id = int(id_parts[2])  # Get the paper_id part
                paper = next((p for p in self.papers if p.id == paper_id), None)
                if paper:
                    self.show_paper_details(paper)
                else:
                    self.clear_paper_details()
            else:
                self.clear_paper_details()
        except (ValueError, AttributeError, IndexError):
            self.clear_paper_details()

    def show_paper_details(self, paper: Paper) -> None:
        """Display paper details in the details panel."""
        details_text = self.query_one("#paper-details-text", Static)

        # Format paper details as one-liner like the original app
        authors = paper.author_names or "Unknown Authors"
        title = paper.title or "Unknown Title"
        venue = ""
        if hasattr(paper, "venue_display"):
            venue = paper.venue_display or ""
        elif paper.venue_full:
            venue = paper.venue_full
        elif paper.venue_acronym:
            venue = paper.venue_acronym

        year = paper.year or "Unknown Year"

        # Format as citation: authors, "title," venue (year)
        if venue:
            details_display = f'{authors}, "{title}," {venue} ({year})'
        else:
            details_display = f'{authors}, "{title}" ({year})'

        details_text.update(details_display)

    def clear_paper_details(self) -> None:
        """Clear the paper details panel."""
        details_text = self.query_one("#paper-details-text", Static)
        details_text.update("Select a paper to view details")
