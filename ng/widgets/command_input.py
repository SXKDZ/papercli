from textual.app import ComposeResult
from textual.widgets import Input
from textual import events
from textual.message import Message
from textual.containers import Container
from typing import Optional, TYPE_CHECKING, List

from textual_autocomplete import AutoComplete, DropdownItem
from ng.services import CollectionService

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CommandInput(Container):
    """A custom input widget with autocomplete dropdown for handling commands."""

    class CommandEntered(Message):
        """Posted when a command is entered."""

        def __init__(self, command: str) -> None:
            self.command = command
            super().__init__()

    def __init__(
        self,
        app: Optional["PaperCLIApp"] = None,
        placeholder: str = "",
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._app = app
        self.placeholder = placeholder
        self._input_widget: Optional[Input] = None

        # Commands for autocomplete
        self.commands = {
            # Paper management
            "/add": {
                "description": "Open add dialog or add paper directly",
                "subcommands": {
                    "arxiv": "Add from an arXiv ID",
                    "dblp": "Add from a DBLP URL",
                    "openreview": "Add from an OpenReview ID",
                    "doi": "Add from a DOI",
                    "pdf": "Add from a local PDF file",
                    "bib": "Add papers from a BibTeX file",
                    "ris": "Add papers from a RIS file",
                    "manual": "Add a paper with manual entry",
                },
            },
            "/edit": {
                "description": "Open edit dialog or edit field directly",
                "subcommands": {
                    "extract-pdf": "Extract metadata from PDF",
                    "summarize": "Generate LLM summary",
                    "title": "Edit the title",
                    "abstract": "Edit the abstract",
                    "notes": "Edit your personal notes",
                    "venue_full": "Edit the full venue name",
                    "venue_acronym": "Edit the venue acronym",
                    "year": "Edit the publication year",
                    "paper_type": "Edit the paper type",
                    "doi": "Edit the DOI",
                    "pages": "Edit the page numbers",
                    "preprint_id": "Edit the preprint ID",
                    "url": "Edit the paper URL",
                },
            },
            "/delete": {
                "description": "Delete the selected paper(s)",
                "subcommands": {},
            },
            "/detail": {"description": "Show detailed metadata", "subcommands": {}},
            "/open": {"description": "Open the PDF file", "subcommands": {}},
            # AI and export
            "/chat": {
                "description": "Chat interface with AI",
                "subcommands": {
                    "claude": "Open Claude AI in browser",
                    "chatgpt": "Open ChatGPT in browser",
                    "gemini": "Open Google Gemini in browser",
                },
            },
            "/copy-prompt": {
                "description": "Copy paper prompt to clipboard",
                "subcommands": {},
            },
            "/export": {
                "description": "Export selected papers",
                "subcommands": {
                    "bibtex": "Export to BibTeX format",
                    "ieee": "Export to IEEE reference format",
                    "markdown": "Export to Markdown format",
                    "html": "Export to HTML format",
                    "json": "Export to JSON format",
                },
            },
            # Collections
            "/collect": {
                "description": "Manage collections",
                "subcommands": {"purge": "Delete all empty collections"},
            },
            "/add-to": {"description": "Add papers to collections", "subcommands": {}},
            "/remove-from": {
                "description": "Remove papers from collections",
                "subcommands": {},
            },
            # Navigation and discovery
            "/help": {"description": "Show the help panel", "subcommands": {}},
            "/all": {"description": "Show all papers", "subcommands": {}},
            "/filter": {
                "description": "Filter papers by criteria",
                "subcommands": {
                    "all": "Search across all fields",
                    "year": "Filter by publication year",
                    "author": "Filter by author name",
                    "venue": "Filter by venue name",
                    "type": "Filter by paper type",
                    "collection": "Filter by collection name",
                },
            },
            "/sort": {
                "description": "Sort the paper list",
                "subcommands": {
                    "title": "Sort by title",
                    "authors": "Sort by author names",
                    "venue": "Sort by venue",
                    "year": "Sort by publication year",
                },
            },
            "/select": {"description": "Enter multi-selection mode", "subcommands": {}},
            "/clear": {"description": "Clear all selected papers", "subcommands": {}},
            # System and configuration
            "/config": {
                "description": "Manage configuration settings",
                "subcommands": {
                    "show": "Show all current configuration",
                    "model": "Set OpenAI model",
                    "openai_api_key": "Set OpenAI API key",
                    "remote": "Set remote sync path",
                    "auto-sync": "Enable/disable auto-sync",
                    "help": "Show configuration help",
                },
            },
            "/sync": {
                "description": "Synchronize with remote storage",
                "subcommands": {},
            },
            "/log": {"description": "Show the log panel", "subcommands": {}},
            "/doctor": {
                "description": "Diagnose and fix issues",
                "subcommands": {
                    "clean": "Clean orphaned records",
                    "help": "Show doctor help",
                },
            },
            "/version": {
                "description": "Show version information",
                "subcommands": {
                    "check": "Check for updates",
                    "update": "Update to latest version",
                    "info": "Show detailed version info",
                },
            },
            "/exit": {"description": "Exit the application", "subcommands": {}},
        }

    def compose(self) -> ComposeResult:
        # Use modern autocomplete dropdown
        self._input_widget = Input(placeholder=self.placeholder, id="input")
        yield self._input_widget
        # Use custom autocomplete with DropdownItems
        yield AutoComplete(self._input_widget, candidates=self._build_candidates())

    def _build_candidates(self) -> List[DropdownItem]:
        """Build DropdownItem candidates with commands and help text properly separated."""
        items: List[DropdownItem] = []

        # Get collection names for dynamic autocomplete
        collection_names = []
        try:
            collection_service = CollectionService()
            collections = collection_service.get_all_collections()
            collection_names = [c.name for c in collections]
        except Exception:
            # Fallback if database isn't available
            collection_names = []

        for cmd, info in self.commands.items():
            # DropdownItem takes main text as first parameter
            items.append(DropdownItem(cmd))

            # Handle dynamic collection subcommands
            if cmd in ["/add-to", "/remove-from"] and collection_names:
                for collection_name in collection_names:
                    full_cmd = f"{cmd} {collection_name}"
                    items.append(DropdownItem(full_cmd))
            else:
                # Regular subcommands
                for subcmd, sdesc in info.get("subcommands", {}).items():
                    full_cmd = f"{cmd} {subcmd}"
                    items.append(DropdownItem(full_cmd))
        return items

    def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission."""
        self.post_message(self.CommandEntered(message.value))
        if self._input_widget:
            self._input_widget.value = ""  # Clear the input after submission

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Before focus moves to the input on mouse click, preserve cursor row highlight and log state."""
        try:
            paper_list = self.screen.query_one("#paper-list-view")
            # Store cursor position before focus changes
            current_cursor_row = paper_list.cursor_row
            
            # Re-apply cursor row to keep highlight even when focus changes
            if 0 <= paper_list.cursor_row < len(paper_list.papers):
                paper_list.move_cursor(row=paper_list.cursor_row)
            
            # Store the cursor position in a custom attribute for later restoration
            paper_list._stored_cursor_row = current_cursor_row
            
            # Ensure selection styling is maintained when focus moves to input
            if paper_list.selected_paper_ids and paper_list.in_select_mode:
                paper_list.add_class("retain-selection")
            if hasattr(self.app, "_add_log"):
                self.app._add_log(
                    "command_input_mouse_down",
                    f"preserve cursor_row={current_cursor_row}, stored_cursor={current_cursor_row}, "
                    f"selected_ids={list(paper_list.selected_paper_ids)}, "
                    f"in_select_mode={paper_list.in_select_mode}, "
                    f"classes_before={paper_list.classes}"
                )
        except Exception:
            pass

    @property
    def value(self) -> str:
        """Get the current input value."""
        return self._input_widget.value if self._input_widget else ""

    @value.setter
    def value(self, new_value: str) -> None:
        """Set the input value."""
        if self._input_widget:
            self._input_widget.value = new_value

    @property
    def app(self) -> Optional["PaperCLIApp"]:
        """Get the app reference."""
        return self._app

    @app.setter
    def app(self, value: Optional["PaperCLIApp"]) -> None:
        """Set the app reference."""
        self._app = value
