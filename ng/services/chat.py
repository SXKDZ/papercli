from __future__ import annotations

import os
import traceback
import webbrowser
from typing import TYPE_CHECKING, Any, Dict, List

from pluralizer import Pluralizer

from ng.services import PDFManager
from ng.services.prompts import ChatPrompts

if TYPE_CHECKING:
    from ng.db.models import Paper


class ChatService:
    """Service for chat functionality."""

    def __init__(self, app):
        self.app = app
        self.pdf_manager = PDFManager()
        self._pluralizer = Pluralizer()

    def copy_prompt_to_clipboard(self, papers: List[Paper]) -> Dict[str, Any]:
        """Generate and copy paper prompt to clipboard for external LLM use."""
        try:
            # Build paper context using the same format as chat
            context_parts = []
            for i, paper in enumerate(papers, 1):
                paper_context = f"Paper {i}: {paper.title}\n"
                paper_context += f"Authors: {paper.author_names}\n"
                paper_context += (
                    f"Venue: {paper.venue_display} ({paper.year or 'N/A'})\n"
                )
                context_parts.append(paper_context)

            # Create simple prompt for external LLM use
            full_prompt = ChatPrompts.clipboard_prompt(
                len(papers), chr(10).join(context_parts)
            )

            copied = self.app.system_service.copy_to_clipboard(full_prompt)
            if copied:
                return {
                    "success": True,
                    "message": f"Prompt for {self._pluralizer.pluralize('paper', len(papers), True)} copied to clipboard",
                    "prompt_length": len(full_prompt),
                }
            return {
                "success": False,
                "message": "Failed to copy to clipboard",
                "prompt_length": len(full_prompt),
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error copying prompt to clipboard: {str(e)}",
                "prompt_length": 0,
            }

    def open_chat_interface(self, papers: List[Paper], provider: str = "claude"):
        """Copy paper prompt to clipboard and open LLM provider in browser."""
        try:
            # First, copy the prompt to clipboard
            clipboard_result = self.copy_prompt_to_clipboard(papers)

            # Open provider-specific homepage in browser
            provider_urls = {
                "claude": "https://claude.ai",
                "chatgpt": "https://chat.openai.com",
                "gemini": "https://gemini.google.com",
            }

            url = provider_urls.get(provider, "https://claude.ai")
            webbrowser.open(url)

            # Reveal PDF files using SystemService
            opened_files = []
            failed_files = []

            for paper in papers:
                if paper.pdf_path:
                    absolute_path = self.pdf_manager.get_absolute_path(paper.pdf_path)
                    if os.path.exists(absolute_path):
                        try:
                            success, error = self.app.system_service.open_file_location(
                                absolute_path
                            )
                            if success:
                                opened_files.append(paper.title)
                            else:
                                failed_files.append(f"{paper.title}: {error}")
                        except Exception as e:
                            error_msg = f"{paper.title}: {str(e)}"
                            failed_files.append(error_msg)
                            self.app._add_log(
                                "chat_pdf_error",
                                f"Failed to open PDF for {paper.title}: {traceback.format_exc()}",
                            )

            # Prepare result message
            result_parts = []
            provider_name = provider.title()

            # Include clipboard result
            if clipboard_result["success"]:
                result_parts.append(clipboard_result["message"])
            else:
                result_parts.append(f"Warning: {clipboard_result['message']}")

            # Add browser/PDF opening results
            if opened_files:
                result_parts.append(
                    f"Opened {provider_name} and {self._pluralizer.pluralize('PDF file', len(opened_files), True)}"
                )
            else:
                result_parts.append(f"Opened {provider_name}")

            if failed_files:
                result_parts.append(
                    f"Failed to open {self._pluralizer.pluralize('file', len(failed_files), True)}"
                )
                # Return combined results
                return {
                    "success": True,
                    "message": "; ".join(result_parts),
                    "errors": failed_files,
                    "clipboard_success": clipboard_result["success"],
                }

            return {
                "success": True,
                "message": "; ".join(result_parts),
                "errors": [],
                "clipboard_success": clipboard_result["success"],
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Error opening chat interface: {str(e)}",
                "errors": [],
            }
