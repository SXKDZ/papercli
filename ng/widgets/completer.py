"""Command completer for PaperCLI Textual interface."""

from typing import List, Iterable, Optional, TYPE_CHECKING
from textual.suggester import Suggester

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CommandCompleter(Suggester):
    """Command completer for PaperCLI commands."""
    
    cache = True  # Enable caching for better performance
    case_sensitive = False

    def __init__(self, app: Optional["PaperCLIApp"] = None):
        super().__init__()
        self.app = app
        # Commands ordered by functional groups  
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
            "/delete": {"description": "Delete the selected paper(s)", "subcommands": {}},
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
            "/copy-prompt": {"description": "Copy paper prompt to clipboard", "subcommands": {}},
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
            "/remove-from": {"description": "Remove papers from collections", "subcommands": {}},
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
            "/sync": {"description": "Synchronize with remote storage", "subcommands": {}},
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

    async def get_suggestion(self, value: str) -> str | None:
        """Get command suggestions."""
        if not value:
            return None
        
        # Special case: if value is just "/", suggest "add" (first common command)
        if value == "/":
            return "add"
            
        words = value.split()
        
        # Main command completion
        if len(words) == 1 and not value.endswith(" "):
            partial_cmd = words[0]
            
            # Find matching commands
            matches = [cmd for cmd in self.commands if cmd.startswith(partial_cmd)]
            if matches:
                # Sort by length to prefer shorter matches first
                matches.sort(key=len)
                for cmd in matches:
                    if cmd != partial_cmd:
                        # Return the rest of the command after the partial match
                        suggestion = cmd[len(partial_cmd):]
                        return suggestion
        
        # Subcommand completion
        elif len(words) >= 1:
            cmd = words[0]
            if cmd in self.commands:
                subcommands = self.commands[cmd].get("subcommands", {})
                if subcommands:
                    if value.endswith(" "):
                        # Suggest first subcommand alphabetically
                        subcmd_list = sorted(subcommands.keys())
                        if subcmd_list:
                            return subcmd_list[0]
                    elif len(words) == 2:
                        # Complete partial subcommand
                        partial_subcmd = words[1]
                        matches = [subcmd for subcmd in subcommands if subcmd.startswith(partial_subcmd)]
                        if matches:
                            matches.sort(key=len)
                            for subcmd in matches:
                                if subcmd != partial_subcmd:
                                    suggestion = subcmd[len(partial_subcmd):]
                                    return suggestion
        
        return None