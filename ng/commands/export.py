from __future__ import annotations
import os
from typing import List, TYPE_CHECKING, Any, Dict

import pyperclip

from ng.commands import CommandHandler
from ng.services import ExportService, ChatService, LLMSummaryService
from ng.dialogs import ChatDialog

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp
    from ng.db.models import Paper


class ExportCommandHandler(CommandHandler):
    """Handler for export and share commands like export, chat, copy-prompt."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.export_service = ExportService()
        pdf_dir = os.path.join(os.path.dirname(self.app.db_path), "pdfs")
        self.chat_service = ChatService(app=self.app, pdf_dir=pdf_dir)
        self.llm_summary_service = LLMSummaryService(
            paper_service=self.app.paper_service,
            background_service=self.app.background_service,
            app=self.app,
            pdf_dir=pdf_dir,
        )

    def _get_target_papers(self) -> List[Paper]:
        """Helper to get selected papers from the main app's paper list."""
        try:
            paper_list = self.app.screen.query_one("#paper-list-view")
            return paper_list.get_selected_papers()
        except:
            # Fallback: return empty list if no papers available
            return []

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
                content = self.export_service.export_to_bibtex(papers_to_export)
            elif export_format == "ieee":
                content = self.export_service.export_to_ieee(papers_to_export)
            elif export_format == "markdown":
                content = self.export_service.export_to_markdown(papers_to_export)
            elif export_format == "html":
                content = self.export_service.export_to_html(papers_to_export)
            elif export_format == "json":
                content = self.export_service.export_to_json(papers_to_export)
            else:
                self.app.notify("Unknown export format", severity="error")
                return

            if destination == "file":
                if filename:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(content)
                    self.app.notify(
                        f"Exported {len(papers_to_export)} papers to {filename}",
                        severity="information",
                    )
                else:
                    self.app.notify(
                        "Filename not provided for file export", severity="error"
                    )

            elif destination == "clipboard":
                try:
                    pyperclip.copy(content)
                    self.app.notify(
                        f"Copied {len(papers_to_export)} papers to clipboard",
                        severity="information",
                    )
                except pyperclip.PyperclipException:
                    self.app.notify(
                        "Failed to copy to clipboard. pyperclip might not be installed or configured correctly",
                        severity="error",
                    )

        except Exception as e:
            self.app.notify(f"Error exporting papers: {e}", severity="error")

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

        try:
            self.app.notify("Copying prompt to clipboard...", severity="information")

            result = self.chat_service.copy_prompt_to_clipboard(papers_to_copy)

            if result["success"]:
                self.app.notify(result["message"], severity="information")
            else:
                self.app.notify(result["message"], severity="error")
        except Exception as e:
            self.app.notify(f"Error copying prompt: {e}", severity="error")
