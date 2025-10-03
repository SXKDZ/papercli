from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from pluralizer import Pluralizer

from ng.commands import CommandHandler
from ng.dialogs import ChatDialog
from ng.services import ChatService, export, LLMSummaryService

if TYPE_CHECKING:
    from ng.db.models import Paper
    from ng.papercli import PaperCLIApp


class ExportCommandHandler(CommandHandler):
    """Handler for export and share commands like export, chat, copy-prompt."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.pluralizer = Pluralizer()
        self.chat_service = ChatService(app=self.app)
        self.llm_summary_service = LLMSummaryService(
            paper_service=self.app.paper_service,
            background_service=self.app.background_service,
            app=self.app,
        )

    async def handle_export_command(self, args: List[str]):
        """Handle /export command."""
        papers_to_export = self._get_target_papers()
        if not papers_to_export:
            self.app.notify("No papers selected or under cursor", severity="warning")
            return

        try:
            # Parse command line arguments for quick export
            if len(args) >= 1:
                # Quick export: /export bibtex [filename]
                export_format = args[0].lower()

                if export_format not in ["bibtex", "ieee", "markdown", "html", "json"]:
                    self.app.notify(
                        "Usage: /export <format> [filename]. Formats: bibtex, ieee, markdown, html, json",
                        severity="information",
                    )
                    return

                # Determine destination and filename
                if len(args) >= 2:
                    destination = "file"
                    filename = " ".join(args[1:])
                else:
                    destination = "clipboard"
                    filename = None

                export_params = {
                    "format": export_format,
                    "destination": destination,
                    "filename": filename,
                }
            else:
                # Show usage instead of interactive dialog
                self.app.notify(
                    "Usage: /export <format> [filename]. Formats: bibtex, ieee, markdown, html, json",
                    severity="information",
                )
                return

            self.app.notify("Exporting papers...", severity="information")

            # Export papers
            export_format = export_params["format"]
            destination = export_params["destination"]

            if export_format == "bibtex":
                content = export.export_to_bibtex(papers_to_export)
            elif export_format == "ieee":
                content = export.export_to_ieee(papers_to_export)
            elif export_format == "markdown":
                content = export.export_to_markdown(papers_to_export)
            elif export_format == "html":
                content = export.export_to_html(papers_to_export)
            elif export_format == "json":
                content = export.export_to_json(papers_to_export)
            else:
                self.app.notify("Unknown export format", severity="error")
                return

            if destination == "file":
                if filename:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.app.notify(
                        f"Exported {self.pluralizer.pluralize('paper', len(papers_to_export), True)} to {filename}",
                        severity="information",
                    )
                else:
                    self.app.notify(
                        "Filename not provided for file export", severity="error"
                    )

            elif destination == "clipboard":
                copied = self.app.system_service.copy_to_clipboard(content)
                if copied:
                    self.app.notify(
                        f"Copied {self.pluralizer.pluralize('paper', len(papers_to_export), True)} to clipboard",
                        severity="information",
                    )
                else:
                    self.app.notify(
                        "Failed to copy to clipboard",
                        severity="error",
                    )

        except Exception as e:
            self.app.notify(
                f"Error exporting {self.pluralizer.pluralize('paper', len(papers_to_export), True)}: {e}",
                severity="error",
            )

    async def handle_chat_command(self, provider: str = None):
        """Handle /chat command with optional provider."""
        papers_to_chat = self._get_target_papers()
        if not papers_to_chat:
            self.app.notify("No papers selected or under cursor", severity="warning")
            return

        if provider is None:
            # Show chat dialog with OpenAI
            def chat_dialog_callback(result: Dict[str, Any] | None):
                if result:
                    self.app.notify("Chat dialog closed", severity="information")

            await self.app.push_screen(
                ChatDialog(
                    papers=papers_to_chat,
                    callback=chat_dialog_callback,
                )
            )
        else:
            # /chat provider - open browser interface
            valid_providers = ["claude", "chatgpt", "gemini"]
            if provider not in valid_providers:
                self.app.notify(
                    f"Invalid chat provider: {provider}. Use: {', '.join(valid_providers)}",
                    severity="error",
                )
                return

            self.app.notify(
                f"Copying prompt to clipboard and opening {provider.title()}...",
                severity="information",
            )

            result = self.chat_service.open_chat_interface(papers_to_chat, provider)

            if result["success"]:
                self.app.notify(result["message"], severity="information")
            else:
                self.app.notify(result["message"], severity="error")

    async def handle_copy_prompt_command(self):
        """Handle /copy-prompt command - copy paper prompt to clipboard."""
        papers_to_copy = self._get_target_papers()
        if not papers_to_copy:
            self.app.notify("No papers selected or under cursor", severity="warning")
            return

        self.app.notify("Copying prompt to clipboard...", severity="information")

        result = self.chat_service.copy_prompt_to_clipboard(papers_to_copy)

        if result["success"]:
            self.app.notify(result["message"], severity="information")
        else:
            self.app.notify(result["message"], severity="error")
