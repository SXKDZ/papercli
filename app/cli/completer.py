"""Smart command completer for PaperCLI."""

from typing import TYPE_CHECKING

from prompt_toolkit.completion import Completer
from prompt_toolkit.completion import Completion

if TYPE_CHECKING:
    from .main import PaperCLI


class SmartCompleter(Completer):
    """Smart command completer with subcommand and description support."""

    def __init__(self, cli: "PaperCLI" = None):
        self.cli = cli
        # Commands ordered by functional groups
        self.commands = {
            # Paper management
            "/add": {
                "description": "Open add dialog or add paper directly (e.g., /add arxiv 2307.10635)",
                "subcommands": {
                    "arxiv": "Add from an arXiv ID (e.g., 2307.10635)",
                    "dblp": "Add from a DBLP URL",
                    "openreview": "Add from an OpenReview ID (e.g., bq1JEgioLr)",
                    "doi": "Add from a DOI (e.g., 10.1000/example)",
                    "pdf": "Add from a local PDF file",
                    "bib": "Add papers from a BibTeX (.bib) file",
                    "ris": "Add papers from a RIS (.ris) file",
                    "manual": "Add a paper with manual entry",
                },
            },
            "/edit": {
                "description": "Open edit dialog or edit field directly (e.g., /edit title ...)",
                "subcommands": {
                    "extract-pdf": "Extract metadata from PDF and update paper",
                    "summarize": "Generate LLM summary and update notes field",
                    "title": "Edit the title",
                    "abstract": "Edit the abstract",
                    "notes": "Edit your personal notes",
                    "venue_full": "Edit the full venue name",
                    "venue_acronym": "Edit the venue acronym",
                    "year": "Edit the publication year",
                    "paper_type": "Edit the paper type (e.g., journal, conference)",
                    "doi": "Edit the DOI",
                    "pages": "Edit the page numbers",
                    "preprint_id": "Edit the preprint ID (e.g., arXiv 2505.15134)",
                    "url": "Edit the paper URL",
                },
            },
            "/delete": {
                "description": "Delete the selected paper(s)",
                "subcommands": {},
            },
            "/detail": {
                "description": "Show detailed metadata for the selected paper(s)",
                "subcommands": {},
            },
            "/open": {
                "description": "Open the PDF for the selected paper(s)",
                "subcommands": {},
            },
            # AI and export
            "/chat": {
                "description": "Open chat interface (local OpenAI window or copy prompt to clipboard)",
                "subcommands": {
                    "claude": "Copy prompt to clipboard and open Claude AI in browser",
                    "chatgpt": "Copy prompt to clipboard and open ChatGPT in browser",
                    "gemini": "Copy prompt to clipboard and open Google Gemini in browser",
                },
            },
            "/copy-prompt": {
                "description": "Copy paper prompt to clipboard for use with any LLM",
                "subcommands": {},
            },
            "/export": {
                "description": "Export selected paper(s) to a file or clipboard",
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
                "subcommands": {
                    "purge": "Delete all empty collections",
                },
            },
            "/add-to": {
                "description": "Add selected paper(s) to one or more collections",
                "subcommands": {},
            },
            "/remove-from": {
                "description": "Remove selected paper(s) from one or more collections",
                "subcommands": {},
            },
            # Navigation and discovery
            "/help": {"description": "Show the help panel", "subcommands": {}},
            "/all": {
                "description": "Show all papers in the database",
                "subcommands": {},
            },
            "/filter": {
                "description": "Filter papers by specific criteria or search all fields",
                "subcommands": {
                    "all": "Search across all fields (title, author, venue, abstract)",
                    "year": "Filter by publication year (e.g., 2023)",
                    "author": "Filter by author name (e.g., 'Turing')",
                    "venue": "Filter by venue name (e.g., 'NeurIPS')",
                    "type": "Filter by paper type (e.g., 'journal')",
                    "collection": "Filter by collection name (e.g., 'My Papers')",
                },
            },
            "/sort": {
                "description": "Sort the paper list by a field",
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
                    "model": "Set OpenAI model (e.g., gpt-4o, gpt-3.5-turbo)",
                    "openai_api_key": "Set OpenAI API key",
                    "remote": "Set remote sync path",
                    "auto-sync": "Enable/disable auto-sync",
                    "help": "Show configuration command help",
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
                "description": "Synchronize local data with remote storage",
                "subcommands": {},
            },
            "/log": {"description": "Show the error log panel", "subcommands": {}},
            "/doctor": {
                "description": "Diagnose and fix database/system issues",
                "subcommands": {
                    "clean": "Clean orphaned database records and PDF files",
                    "help": "Show doctor command help",
                },
            },
            "/version": {
                "description": "Show version information and check for updates",
                "subcommands": {
                    "check": "Check for available updates",
                    "update": "Update to the latest version (if possible)",
                    "info": "Show detailed version information",
                },
            },
            "/exit": {"description": "Exit the application", "subcommands": {}},
        }

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()

        # Completion for main commands
        if len(words) <= 1 and not text.endswith(" "):
            partial_cmd = words[0] if words else ""
            for cmd, data in self.commands.items():
                if cmd.startswith(partial_cmd):
                    yield Completion(
                        cmd,
                        start_position=-len(partial_cmd),
                        display_meta=data["description"],
                    )

        # Collection name completion for /add-to and /remove-from
        elif len(words) >= 1 and words[0] in ["/add-to", "/remove-from"]:
            if not self.cli:
                return

            # Get the partial collection name (the current word being typed)
            if text.endswith(" "):
                partial_name = ""
            else:
                partial_name = words[-1] if len(words) > 1 else ""

            # Get already typed collection names to exclude them from completion
            already_typed = (
                set(words[1:-1])
                if len(words) > 2 and not text.endswith(" ")
                else set(words[1:])
            )

            try:
                collections = self.cli.collection_service.get_all_collections()

                if words[0] == "/remove-from":
                    # For /remove-from, prioritize collections containing selected papers
                    selected_papers = self.cli._get_target_papers()
                    paper_ids = {p.id for p in selected_papers}

                    # Separate collections into those containing papers and those that don't
                    containing_collections = []
                    other_collections = []

                    for collection in collections:
                        collection_paper_ids = {p.id for p in collection.papers}
                        if paper_ids.intersection(collection_paper_ids):
                            containing_collections.append(collection)
                        else:
                            other_collections.append(collection)

                    # Yield containing collections first, then others
                    all_ordered_collections = containing_collections + other_collections
                else:
                    # For /add-to, use normal order
                    all_ordered_collections = collections

                for collection in all_ordered_collections:
                    # Skip collections that have already been typed
                    if collection.name in already_typed:
                        continue

                    if collection.name.lower().startswith(partial_name.lower()):
                        # Calculate the correct start position
                        start_pos = -len(partial_name)

                        yield Completion(
                            collection.name,
                            start_position=start_pos,
                            display_meta=f"Collection ({len(collection.papers)} papers)",
                        )
            except Exception:
                # Silently fail if collections can't be loaded
                pass

        # Completion for subcommands
        elif len(words) == 1 and text.endswith(" "):
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                if subcommands:
                    for subcmd, description in subcommands.items():
                        yield Completion(
                            subcmd, start_position=0, display_meta=description
                        )

        # Completion for partial subcommands
        elif len(words) == 2 and not text.endswith(" "):
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                partial_subcmd = words[1]
                for subcmd, description in subcommands.items():
                    if subcmd.startswith(partial_subcmd):
                        yield Completion(
                            subcmd,
                            start_position=-len(partial_subcmd),
                            display_meta=description,
                        )

        # Special completion for /config model <model_name>
        elif len(words) >= 2 and words[0] == "/config" and words[1] == "model":
            if len(words) == 2 and text.endswith(" "):
                # Show all model options
                model_options = self.commands["/config"].get("model_options", {})
                for model, description in model_options.items():
                    yield Completion(model, start_position=0, display_meta=description)
            elif len(words) == 3 and not text.endswith(" "):
                # Show partial model matches
                model_options = self.commands["/config"].get("model_options", {})
                partial_model = words[2]
                for model, description in model_options.items():
                    if model.startswith(partial_model):
                        yield Completion(
                            model,
                            start_position=-len(partial_model),
                            display_meta=description,
                        )
