from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, Input, ListView, ListItem, Label, TextArea
from textual.screen import ModalScreen
from textual.reactive import reactive
from typing import Callable, Dict, Any, List, Optional
from ng.db.models import Paper, Collection


class CollectDialog(ModalScreen):
    """A modal dialog for managing collections with 3-column layout."""

    DEFAULT_CSS = """
    CollectDialog {
        align: center middle;
        layer: dialog;
    }
    CollectDialog > Container {
        width: 100;
        height: 30;
        max-width: 120;
        max-height: 35;
        border: solid $accent;
        background: $panel;
    }
    CollectDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    CollectDialog .column {
        width: 1fr;
        height: 1fr;
        border: solid grey;
        margin: 0 1;
    }
    CollectDialog .column-title {
        text-style: bold;
        text-align: center;
        height: 3;
        background: $accent-darken-1;
        color: $text;
    }
    CollectDialog .list-container {
        height: 1fr;
    }
    CollectDialog .action-buttons {
        width: 15;
        height: 1fr;
        align: center middle;
    }
    CollectDialog .action-buttons Button {
        width: 12;
        margin: 0;
        height: 3;
        content-align: center middle;
        text-align: center;
    }
    CollectDialog .column Button {
        height: 3;
        content-align: center middle;
        text-align: center;
        margin: 0 1;
    }
    CollectDialog .paper-details {
        height: 8;
        border: solid grey;
        margin: 1;
    }
    CollectDialog .paper-details-title {
        text-style: bold;
        text-align: center;
        height: 3;
        background: $accent-darken-1;
        color: $text;
    }
    CollectDialog .bottom-buttons {
        height: 5;
        align: center middle;
    }
    CollectDialog .bottom-buttons Button {
        margin: 0 1;
        min-width: 8;
        height: 3;
        content-align: center middle;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    selected_collection = reactive(None)
    selected_collection_paper = reactive(None)
    selected_all_paper = reactive(None)

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

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Manage Collections", classes="dialog-title")

            # Main 3-column layout
            with Horizontal():
                # Column 1: Collections List
                with Vertical(classes="column"):
                    yield Static("Collections", classes="column-title")
                    with VerticalScroll(classes="list-container"):
                        yield ListView(id="collections-list")
                    yield Input(
                        placeholder="New collection name", id="new-collection-input"
                    )
                    with Horizontal():
                        yield Button(
                            "Add", id="add-collection-button", variant="success"
                        )
                        yield Button(
                            "Delete", id="delete-collection-button", variant="error"
                        )

                # Column 2: Papers in Selected Collection
                with Vertical(classes="column"):
                    yield Static(
                        "Papers in Collection",
                        classes="column-title",
                        id="collection-papers-title",
                    )
                    with VerticalScroll(classes="list-container"):
                        yield ListView(id="collection-papers-list")

                # Action buttons between columns 2 and 3
                with Vertical(classes="action-buttons"):
                    yield Button("← Add", id="add-paper-button", variant="primary")
                    yield Button(
                        "Remove →", id="remove-paper-button", variant="warning"
                    )

                # Column 3: All Papers
                with Vertical(classes="column"):
                    yield Static("All Papers", classes="column-title")
                    with VerticalScroll(classes="list-container"):
                        yield ListView(id="all-papers-list")

            # Paper Details Panel
            with Vertical(classes="paper-details"):
                yield Static("Paper Details", classes="paper-details-title")
                yield TextArea(
                    text="Select a paper to view details",
                    read_only=True,
                    id="paper-details-area",
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

    def populate_collections_list(self) -> None:
        """Populate the collections list."""
        collections_list = self.query_one("#collections-list", ListView)
        collections_list.clear()

        for collection in self.collections:
            item = ListItem(Label(collection.name), id=f"collection-{collection.id}")
            collections_list.append(item)

    def populate_all_papers_list(self) -> None:
        """Populate the all papers list."""
        all_papers_list = self.query_one("#all-papers-list", ListView)
        all_papers_list.clear()

        for paper in self.papers:
            title = paper.title[:50] + "..." if len(paper.title) > 50 else paper.title
            item = ListItem(Label(title), id=f"paper-{paper.id}")
            all_papers_list.append(item)

    def populate_collection_papers_list(self, collection: Collection) -> None:
        """Populate papers in the selected collection."""
        collection_papers_list = self.query_one("#collection-papers-list", ListView)
        collection_papers_list.clear()

        # Update title
        title_widget = self.query_one("#collection-papers-title", Static)
        title_widget.update(f"Papers in '{collection.name}'")

        for idx, paper in enumerate(collection.papers):
            title = paper.title[:50] + "..." if len(paper.title) > 50 else paper.title
            item = ListItem(
                Label(title), id=f"collection-paper-{collection.id}-{paper.id}-{idx}"
            )
            collection_papers_list.append(item)

    def select_collection(self, index: int) -> None:
        """Select a collection and populate its papers."""
        if 0 <= index < len(self.collections):
            collection = self.collections[index]
            self.selected_collection = collection
            self.populate_collection_papers_list(collection)

            # Highlight the selected collection
            collections_list = self.query_one("#collections-list", ListView)
            collections_list.index = index

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list selection events."""
        if event.list_view.id == "collections-list":
            index = event.list_view.index
            if index is not None and 0 <= index < len(self.collections):
                self.select_collection(index)
        elif event.list_view.id == "collection-papers-list":
            self.selected_collection_paper = event.item
            self.update_paper_details_from_collection_paper(event.item)
        elif event.list_view.id == "all-papers-list":
            self.selected_all_paper = event.item
            self.update_paper_details_from_all_papers(event.item)

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

        # Add to UI
        collections_list = self.query_one("#collections-list", ListView)
        item = ListItem(
            Label(f"{name} (new)"), id=f"new-collection-{len(self.new_collections)-1}"
        )
        collections_list.append(item)

        # Clear input
        input_widget.value = ""

    def delete_selected_collection(self) -> None:
        """Delete the selected collection."""
        collections_list = self.query_one("#collections-list", ListView)
        index = collections_list.index

        if index is not None and 0 <= index < len(self.collections):
            collection = self.collections[index]
            self.deleted_collections.append(collection.name)

            # Remove from UI
            collections_list.remove_items([collections_list.highlighted_child])

            # Clear collection papers
            self.query_one("#collection-papers-list", ListView).clear()

    def add_paper_to_collection(self) -> None:
        """Add selected paper from all papers to the current collection."""
        if not self.selected_collection or not self.selected_all_paper:
            return

        # Extract paper ID from the item ID
        paper_id = int(self.selected_all_paper.id.replace("paper-", ""))
        paper = next((p for p in self.papers if p.id == paper_id), None)

        if paper and paper not in self.selected_collection.papers:
            # Track the change
            self.paper_moves.append((paper_id, self.selected_collection.name, "add"))

            # Add to UI
            title = paper.title[:50] + "..." if len(paper.title) > 50 else paper.title
            collection_papers_list = self.query_one("#collection-papers-list", ListView)
            idx = len(
                collection_papers_list.children
            )  # Get current count for unique index
            item = ListItem(
                Label(title),
                id=f"collection-paper-{self.selected_collection.id}-{paper.id}-{idx}",
            )
            collection_papers_list.append(item)

    def remove_paper_from_collection(self) -> None:
        """Remove selected paper from the current collection."""
        if not self.selected_collection or not self.selected_collection_paper:
            return

        # Extract paper ID from the item ID (format: collection-paper-{collection_id}-{paper_id}-{idx})
        id_parts = self.selected_collection_paper.id.split("-")
        if len(id_parts) >= 4:
            paper_id = int(id_parts[3])  # Get the paper_id part
        else:
            return  # Invalid ID format

        # Track the change
        self.paper_moves.append((paper_id, self.selected_collection.name, "remove"))

        # Remove from UI
        collection_papers_list = self.query_one("#collection-papers-list", ListView)
        collection_papers_list.remove_items([self.selected_collection_paper])

    def action_save(self) -> None:
        """Save changes and close dialog."""
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

        # Extract paper ID from the item ID (format: collection-paper-{collection_id}-{paper_id}-{idx})
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

        # Extract paper ID from the item ID (format: paper-{paper_id})
        try:
            paper_id = int(item.id.replace("paper-", ""))
            paper = next((p for p in self.papers if p.id == paper_id), None)
            if paper:
                self.show_paper_details(paper)
            else:
                self.clear_paper_details()
        except (ValueError, AttributeError):
            self.clear_paper_details()

    def show_paper_details(self, paper: Paper) -> None:
        """Display paper details in the details panel."""
        details_area = self.query_one("#paper-details-area", TextArea)

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
            details_text = f'{authors}, "{title}," {venue} ({year})'
        else:
            details_text = f'{authors}, "{title}" ({year})'

        details_area.text = details_text

    def clear_paper_details(self) -> None:
        """Clear the paper details panel."""
        details_area = self.query_one("#paper-details-area", TextArea)
        details_area.text = "Select a paper to view details"
