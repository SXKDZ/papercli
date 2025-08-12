from typing import TYPE_CHECKING, List, Optional

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.geometry import Offset, Region, Spacing
from textual.message import Message
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem, TargetState

from ng.services import CollectionService

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CommandInput(Container):
    """A custom input widget with autocomplete dropdown for handling commands."""

    BINDINGS = [
        Binding("ctrl+c", "clear_input", "Clear input", show=False),
    ]

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
                "model_options": {
                    "gpt-4o": "Latest GPT-4 Omni model (recommended)",
                    "gpt-4o-mini": "Faster, smaller GPT-4 Omni model",
                    "gpt-4-turbo": "GPT-4 Turbo model",
                    "gpt-4": "Standard GPT-4 model",
                    "gpt-3.5-turbo": "GPT-3.5 Turbo model (faster, cheaper)",
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
        # Use custom autocomplete with dynamic candidate building
        yield CommandAutoComplete(
            self._input_widget,
            candidates=self._get_dynamic_candidates,
            app=self._app,
            classes="autocomplete-dropdown",
        )

    def _get_dynamic_candidates(self, state: TargetState) -> List[DropdownItem]:
        """Dynamically build candidates based on current input context."""
        if not self._input_widget:
            return []

        text = state.text
        words = text.split()
        items: List[DropdownItem] = []

        # Show more items in dropdown (up to 10)
        max_items = 10
        count = 0

        # Main command completion
        if len(words) <= 1 and not text.endswith(" "):
            partial_cmd = words[0] if words else ""

            for cmd, info in self.commands.items():
                if cmd.startswith(partial_cmd) and count < max_items:
                    # Don't show completion if command is already complete (without trailing space)
                    # This allows "/edit" to execute directly, but "/edit " will show subcommands
                    if partial_cmd == cmd:
                        continue  # Skip showing completion for complete commands
                    items.append(DropdownItem(cmd))
                    count += 1

        # Collection name completion for /add-to and /remove-from (only after command is typed)
        elif len(words) >= 1 and words[0] in ["/add-to", "/remove-from"]:
            try:
                collection_service = CollectionService()
                collections = collection_service.get_all_collections()

                # Get the partial collection name
                if text.endswith(" "):
                    partial_name = ""
                else:
                    partial_name = words[-1] if len(words) > 1 else ""

                # Get already typed collection names to exclude them
                already_typed = (
                    set(words[1:-1])
                    if len(words) > 2 and not text.endswith(" ")
                    else set(words[1:])
                )

                # Simplified logic: just show all matching collections for now
                for collection in collections:
                    if (
                        collection.name not in already_typed
                        and collection.name.lower().startswith(partial_name.lower())
                        and count < max_items
                    ):
                        items.append(DropdownItem(collection.name))
                        count += 1

            except Exception:
                # Add test items if service fails to verify completion works
                for i in range(min(5, max_items - count)):
                    items.append(DropdownItem(main=f"test-collection-{i+1}"))
                    count += 1

        # Subcommand completion (only after main command and space, but not for collection commands)
        elif (
            (len(words) >= 1 and text.endswith(" "))
            or (len(words) == 2 and not text.endswith(" "))
        ) and words[0] not in ["/add-to", "/remove-from"]:
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                if subcommands:
                    partial_subcmd = "" if text.endswith(" ") else words[1]
                    for subcmd, description in subcommands.items():
                        if subcmd.startswith(partial_subcmd) and count < max_items:
                            items.append(DropdownItem(subcmd))
                            count += 1

        # Special completion for /config model <model_name>
        elif len(words) >= 2 and words[0] == "/config" and words[1] == "model":
            model_options = self.commands["/config"].get("model_options", {})
            if model_options:
                partial_model = (
                    "" if text.endswith(" ") else (words[2] if len(words) > 2 else "")
                )
                for model, description in model_options.items():
                    if model.startswith(partial_model) and count < max_items:
                        items.append(DropdownItem(model))
                        count += 1

        return items

    def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission."""
        self.post_message(self.CommandEntered(message.value))
        if self._input_widget:
            self._input_widget.value = ""  # Clear the input after submission

    def on_key(self, event: events.Key) -> None:
        """Handle key events for Ctrl-C."""
        if (
            event.key == "ctrl+c"
            and self._input_widget
            and self._input_widget.has_focus
        ):
            self._input_widget.value = ""
            event.prevent_default()

    def action_clear_input(self) -> None:
        """Clear the input when Ctrl+C is pressed."""
        if self._input_widget:
            self._input_widget.value = ""

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
                    f"classes_before={paper_list.classes}",
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


class CommandAutoComplete(AutoComplete):
    """Autocomplete tuned for command-style inputs.

    - Matches only the relevant segment (last token or sub-token) instead of the whole input.
    - Applies the completion by replacing just the active token, preserving the rest of the command.
    - Positions dropdown above the input field with more height for better visibility.
    """

    def __init__(self, target_input, candidates, app=None, classes=None, **kwargs):
        """Initialize with app reference for logging."""
        super().__init__(target_input, candidates=candidates, classes=classes, **kwargs)
        self._app = app

    def _align_to_target(self) -> None:
        """Override to position the dropdown above the input field."""
        if not self.target:
            return

        # Get target cursor position (original approach)
        x, y = self.target.cursor_screen_offset
        dropdown = self.option_list
        width, height = dropdown.outer_size

        # Make dropdown much narrower - use about 20% of target width, max 18 chars
        target_width = self.target.size.width if hasattr(self.target, "size") else width
        dropdown_width = min(
            max(int(target_width * 0.2), 12), 18
        )  # 12-18 characters wide

        # Use consistent height regardless of item count for stable appearance
        consistent_height = 8  # Always show 8 rows for consistency

        # Try to position above the target input field, moved 2 lines lower
        desired_y = y - consistent_height  # Position above without gap (2 lines lower)

        # Ensure dropdown doesn't go off-screen at the top
        if desired_y < 0:
            # Fall back to original positioning (below cursor)
            desired_y = y + 1

        # Constrain the dropdown within the screen bounds
        x, y, _width, _height = Region(
            x - 1, desired_y, dropdown_width, consistent_height
        ).constrain(
            "inside",
            "none",
            Spacing.all(0),
            self.screen.scrollable_content_region,
        )

        # Apply the position
        self.absolute_offset = Offset(x, y)

        # Try to set the dropdown size to ensure proper dimensions
        try:
            dropdown.styles.height = _height
            dropdown.styles.width = _width
            dropdown.styles.max_height = _height
            # Ensure the internal list can scroll properly
            dropdown.styles.overflow_y = "auto"
        except Exception:
            pass  # Fallback to CSS-controlled sizing

        self.refresh(layout=True)

    def get_search_string(self, target_state: TargetState) -> str:
        text = target_state.text
        cursor = target_state.cursor_position
        head = text[:cursor]
        parts = head.split()

        if not parts:
            return ""

        first = parts[0]

        # Main command: match the whole first token (e.g. "/ad")
        if len(parts) == 1 and not head.endswith(" "):
            return parts[0]

        # Collection commands: match the last (partial) collection name
        if first in ("/add-to", "/remove-from"):
            if head.endswith(" "):
                return ""
            return parts[-1]

        # Subcommands: match the second token
        if len(parts) >= 2 and first in (
            "/add",
            "/edit",
            "/export",
            "/filter",
            "/sort",
            "/chat",
            "/config",
        ):
            if head.endswith(" "):
                return ""
            # Return the current partial subcommand (2nd token)
            return parts[1]

        # Fallback: match last token
        return parts[-1]

    def apply_completion(self, value: str, state: TargetState) -> None:
        """Replace only the active token with the chosen value.

        Ensures command prefixes and previously entered arguments remain intact.
        """
        text = state.text
        cursor = state.cursor_position
        head = text[:cursor]
        tail = text[cursor:]

        parts = head.split()
        if not parts:
            new_text = value
        else:
            first = parts[0]

            # Main command replacement
            if len(parts) == 1 and not head.endswith(" "):
                new_head = value
                # Add space after completing a command to encourage next completions
                if not tail.startswith(" "):
                    tail = " " + tail
                new_text = new_head + tail

            # Collection commands: replace the last (partial) collection name
            elif first in ("/add-to", "/remove-from"):
                if head.endswith(" "):
                    # Append a new collection name
                    new_head = head + value
                else:
                    # Replace the current partial collection token
                    new_head = " ".join(parts[:-1] + [value])
                # Always add a trailing space to allow chaining multiple names
                if not tail.startswith(" "):
                    tail = " " + tail
                new_text = new_head + tail

            # Subcommands: replace the second token
            elif len(parts) >= 2 and first in (
                "/add",
                "/edit",
                "/export",
                "/filter",
                "/sort",
                "/chat",
                "/config",
            ):
                if head.endswith(" "):
                    new_head = head + value
                else:
                    new_head = " ".join([parts[0], value])
                if not tail.startswith(" "):
                    tail = " " + tail
                new_text = new_head + tail

            else:
                # Generic: replace last token
                if head.endswith(" "):
                    new_head = head + value
                else:
                    new_head = " ".join(parts[:-1] + [value])
                new_text = new_head + tail

        target = self.target
        with self.prevent(Input.Changed):
            target.value = new_text
            # Move cursor to end of the inserted value
            target.cursor_position = len(new_text)
        self.post_completion()

    def should_show_dropdown(self, search_string: str) -> bool:
        """Show dropdown when there are options, even if search is empty for certain commands.

        - Default behavior: show when search string non-empty and there are options.
        - Extended: show when cursor is after a space in commands that expect another token
          (e.g., collections list after `/add-to ` or subcommands after `/add `).
        """
        option_list = self.option_list
        option_count = option_list.option_count
        if option_count == 0:
            return False
        if len(search_string) > 0:
            return True
        # When search string is empty, show in specific contexts
        state = self._get_target_state()
        text = state.text
        words = text.split()
        if not words:
            return False
        first = words[0]
        if first in ("/add-to", "/remove-from"):
            return True
        if text.endswith(" ") and first in (
            "/add",
            "/edit",
            "/export",
            "/filter",
            "/sort",
            "/chat",
            "/config",
        ):
            return True
        return False
