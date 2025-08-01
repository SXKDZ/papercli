"""Export and share commands handler."""

from typing import List

from prompt_toolkit.layout.containers import Float

from .base import BaseCommandHandler
from ...dialogs import ChatDialog


class ExportCommandHandler(BaseCommandHandler):
    """Handler for export and share commands like export, chat, copy-prompt."""
    
    def handle_export_command(self, args: List[str]):
        """Handle /export command."""
        papers_to_export = self._get_target_papers()
        if not papers_to_export:
            return

        try:

            # Parse command line arguments for quick export
            if len(args) >= 1:
                # Quick export: /export bibtex [filename]
                export_format = args[0].lower()

                if export_format not in ["bibtex", "ieee", "markdown", "html", "json"]:
                    self.cli.status_bar.set_status(
                        "Usage: /export <format> [filename]. Formats: bibtex, ieee, markdown, html, json",
                        "info",
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
                self.cli.status_bar.set_status(
                    "Usage: /export <format> [filename]. Formats: bibtex, ieee, markdown, html, json",
                    "info",
                )
                return

            self.cli.status_bar.set_status("Exporting papers...", "export")

            # Export papers
            export_format = export_params["format"]
            destination = export_params["destination"]

            if export_format == "bibtex":
                content = self.cli.export_service.export_to_bibtex(papers_to_export)
            elif export_format == "ieee":
                content = self.cli.export_service.export_to_ieee(papers_to_export)
            elif export_format == "markdown":
                content = self.cli.export_service.export_to_markdown(papers_to_export)
            elif export_format == "html":
                content = self.cli.export_service.export_to_html(papers_to_export)
            elif export_format == "json":
                content = self.cli.export_service.export_to_json(papers_to_export)
            else:
                self.cli.status_bar.set_status("Unknown export format")
                return

            if destination == "file":
                filename = export_params["filename"]
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(content)
                self.cli.status_bar.set_status(
                    f"Exported {len(papers_to_export)} papers to {filename}", "success"
                )

            elif destination == "clipboard":
                if self.cli.system_service.copy_to_clipboard(content):
                    self.cli.status_bar.set_status(
                        f"Copied {len(papers_to_export)} papers to clipboard", "success"
                    )
                else:
                    self.cli.status_bar.set_status("Error copying to clipboard")

        except Exception as e:
            self.cli.status_bar.set_error(f"Error exporting papers: {e}")

    def handle_chat_command(self, provider: str = None):
        """Handle /chat command with optional provider."""
        papers_to_chat = self._get_target_papers()
        if not papers_to_chat:
            return

        try:
            if provider is None:
                # Check if chat dialog is already open
                if (
                    hasattr(self.cli, "chat_float")
                    and self.cli.chat_float in self.cli.app.layout.container.floats
                ):
                    self.cli.status_bar.set_status("Chat window is already open", "info")
                    return

                # /chat only - show chat window with OpenAI
                self.cli.status_bar.set_status(
                    "Chat window opened - Press ESC to close", "open"
                )

                # Show chat dialog with OpenAI
                chat_dialog = ChatDialog(
                    papers=papers_to_chat,
                    callback=self._on_chat_complete,
                    log_callback=self._add_log,
                    status_bar=self.cli.status_bar,
                )

                self.cli.chat_dialog = chat_dialog.show()
                self.cli.chat_float = Float(self.cli.chat_dialog)
                self.cli.app.layout.container.floats.append(self.cli.chat_float)
                self.cli.app.layout.focus(
                    chat_dialog.get_initial_focus() or self.cli.chat_dialog
                )
                self.cli.app.invalidate()
            else:
                # /chat provider - open browser interface
                valid_providers = ["claude", "chatgpt", "gemini"]
                if provider not in valid_providers:
                    self.cli.status_bar.set_error(
                        f"Invalid chat provider: {provider}. Use: {', '.join(valid_providers)}"
                    )
                    return

                self.cli.status_bar.set_status(
                    f"Copying prompt to clipboard and opening {provider.title()}...",
                    "chat",
                )

                # Open browser interface with provider-specific behavior
                result = self.cli.chat_service.open_chat_interface(papers_to_chat, provider)

                # Handle result
                if isinstance(result, dict):
                    if result["success"]:
                        self.cli.status_bar.set_success(result["message"])
                    else:
                        self.cli.status_bar.set_error(result["message"])
                        self.show_error_panel_with_message(
                            "Chat Error",
                            result["message"],
                            "Failed to open chat interface.",
                        )

        except Exception as e:
            self.cli.status_bar.set_error(f"Error opening chat: {e}")

    def handle_copy_prompt_command(self):
        """Handle /copy-prompt command - copy paper prompt to clipboard."""
        papers_to_copy = self._get_target_papers()
        if not papers_to_copy:
            return

        try:
            self.cli.status_bar.set_status("Copying prompt to clipboard...", "info")

            result = self.cli.chat_service.copy_prompt_to_clipboard(papers_to_copy)

            if result["success"]:
                self.cli.status_bar.set_success(result["message"])
            else:
                self.cli.status_bar.set_error(result["message"])
                self.show_error_panel_with_message(
                    "Copy Prompt Error",
                    result["message"],
                    "Failed to copy prompt to clipboard.",
                )
        except Exception as e:
            self.cli.status_bar.set_error(f"Error copying prompt: {e}")

    def _on_chat_complete(self, result):
        """Callback for when chat dialog is closed."""
        try:
            if (
                hasattr(self.cli, "chat_float")
                and self.cli.chat_float in self.cli.app.layout.container.floats
            ):
                self.cli.app.layout.container.floats.remove(self.cli.chat_float)
            self.cli.chat_float = None
            self.cli.chat_dialog = None
            # Restore focus to the main input buffer
            self.cli.app.layout.focus(self.cli.input_buffer)
            self.cli.status_bar.set_status("Closed chat dialog", "close")
            self.cli.app.invalidate()
        except Exception as e:
            self._add_log("chat_error", f"Error closing chat dialog: {e}")