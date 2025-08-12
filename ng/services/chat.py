from __future__ import annotations
import os
import platform
import subprocess
import traceback
import webbrowser
from typing import Any, Dict, List, TYPE_CHECKING

import pyperclip

from ng.prompts import ChatPrompts
from ng.services import PDFManager

if TYPE_CHECKING:
    from ng.db.models import Paper


class ChatService:
    """Service for chat functionality."""

    def __init__(self, app=None, pdf_dir=None):
        self.app = app
        self.pdf_manager = PDFManager()

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

            # Copy to clipboard
            pyperclip.copy(full_prompt)

            return {
                "success": True,
                "message": f"Prompt for {len(papers)} paper{'s' if len(papers) != 1 else ''} copied to clipboard",
                "prompt_length": len(full_prompt),
            }

        except ImportError:
            return {
                "success": False,
                "message": "Clipboard functionality unavailable (pyperclip not installed)",
                "prompt_length": 0,
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

            # Open PDF files in Finder/File Explorer
            system = platform.system()
            opened_files = []
            failed_files = []

            for paper in papers:
                if paper.pdf_path:
                    absolute_path = self.pdf_manager.get_absolute_path(paper.pdf_path)
                    if os.path.exists(absolute_path):
                        try:
                            if system == "Darwin":  # macOS
                                subprocess.run(
                                    ["open", "-R", absolute_path], check=True
                                )
                            elif system == "Windows":
                                subprocess.run(
                                    ["explorer", "/select,,", absolute_path], check=True
                                )
                            elif system == "Linux":
                                # For Linux, open the directory containing the file
                                pdf_dir = os.path.dirname(absolute_path)
                                subprocess.run(["xdg-open", pdf_dir], check=True)

                            opened_files.append(paper.title)
                        except Exception as e:
                            error_msg = f"{paper.title}: {str(e)}"
                            failed_files.append(error_msg)
                            if self.app:
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
                    f"Opened {provider_name} and {len(opened_files)} PDF file(s)"
                )
            else:
                result_parts.append(f"Opened {provider_name}")

            if failed_files:
                result_parts.append(f"Failed to open {len(failed_files)} file(s)")
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
