from __future__ import annotations

import os
import threading
import time
import traceback
import webbrowser
from typing import TYPE_CHECKING, Any, Callable, Dict, List

import PyPDF2
import tiktoken
from openai import OpenAI
from pluralizer import Pluralizer

from ng.services import PDFManager, dialog_utils, llm_utils, prompts

if TYPE_CHECKING:
    from ng.db.models import Paper


class ChatService:
    """Service for chat functionality."""

    def __init__(self, app):
        self.app = app
        self.pdf_manager = PDFManager(app=self.app)
        self._pluralizer = Pluralizer()
        self.openai_client = None

        # Initialize OpenAI client if API key available
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
            except Exception:
                pass

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
            full_prompt = prompts.chat_clipboard_prompt(
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

    def estimate_tokens(self, text: str, model_name: str) -> int:
        """Estimate tokens using OpenAI's tiktoken library."""
        try:
            encoding = tiktoken.encoding_for_model(model_name.lower())
            return len(encoding.encode(text))
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))

    def clean_pdf_text(self, text: str) -> str:
        """Clean PDF text to remove surrogates and other problematic characters."""
        try:
            cleaned = text.encode("utf-8", errors="ignore").decode("utf-8")
            cleaned = "".join(
                char for char in cleaned if ord(char) >= 32 or char in "\n\t"
            )
            return cleaned
        except Exception:
            return ""

    def extract_page_range(
        self, pdf_path: str, start_page: int = 1, end_page: int = 10
    ) -> str:
        """Extract text from a specific page range of a PDF."""
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text_parts = []
                total_pages = len(pdf_reader.pages)

                if end_page > total_pages or start_page > total_pages:
                    start_idx = 0
                    end_idx = total_pages
                else:
                    start_idx = max(0, start_page - 1)
                    end_idx = min(total_pages, end_page)

                for page_num in range(start_idx, end_idx):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text.strip():
                        cleaned_text = self.clean_pdf_text(page_text.strip())
                        if cleaned_text:
                            text_parts.append(f"Page {page_num + 1}:\n{cleaned_text}")

                return "\n\n".join(text_parts)
        except Exception as e:
            if self.app:
                self.app._add_log(
                    "pdf_extract_error", f"Failed to extract PDF text: {e}"
                )
            return ""

    def build_paper_context(
        self, papers: List[Paper], pdf_start_page: int = 1, pdf_end_page: int = 10
    ) -> str:
        """Build paper context for LLM."""
        if not papers:
            return "No papers are currently selected for discussion."

        context_parts = []
        for i, paper in enumerate(papers, 1):
            fields = dialog_utils.get_paper_fields(paper)

            paper_context = f"Paper {i}: {fields['title']}\n"
            paper_context += f"Authors: {fields['authors']}\n"
            paper_context += f"Venue: {fields['venue']} ({fields['year']})\n"

            if fields["abstract"]:
                paper_context += f"Abstract: {fields['abstract']}\n"

            pdf_content_added = False
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    try:
                        start_page = max(1, pdf_start_page)
                        end_page = max(start_page, pdf_end_page)
                        pdf_text = self.extract_page_range(
                            absolute_path, start_page=start_page, end_page=end_page
                        )
                        if pdf_text:
                            if start_page == end_page:
                                paper_context += f"Page {start_page} attached to this chat:\n{pdf_text}\n"
                            else:
                                paper_context += f"Pages {start_page}-{end_page} attached to this chat:\n{pdf_text}\n"
                            pdf_content_added = True
                    except Exception as e:
                        if self.app:
                            self.app._add_log(
                                "pdf_extract_error",
                                f"Failed to extract PDF pages for '{fields['title']}': {e}",
                            )

            if not pdf_content_added and fields["notes"]:
                paper_context += f"Notes: {fields['notes']}\n"

            context_parts.append(paper_context)

        return prompts.chat_paper_context_header() + "\n".join(context_parts)

    def build_conversation_messages(
        self,
        user_message: str,
        chat_history: List[Dict],
        papers: List[Paper],
        pdf_start_page: int = 1,
        pdf_end_page: int = 10,
    ) -> list:
        """Build messages for OpenAI API."""
        paper_context = self.build_paper_context(papers, pdf_start_page, pdf_end_page)
        system_message = prompts.chat_system_message(paper_context)

        messages = [{"role": "system", "content": system_message}]

        # Include recent history in order. Do not drop the last item,
        # since the current user message is passed separately.
        recent_history = chat_history[-8:] if len(chat_history) > 8 else chat_history
        for entry in recent_history:
            if (
                entry["role"] in ["user", "assistant"]
                and entry["content"].strip()
                and not entry.get("ui_only", False)
            ):
                messages.append({"role": entry["role"], "content": entry["content"]})

        # Append the current user message to be answered
        if user_message and user_message.strip():
            messages.append({"role": "user", "content": user_message})

        return messages

    def stream_chat_response(
        self,
        model_name: str,
        messages: list,
        show_thinking: bool,
        on_content_update: Callable[[str, str], None],
        on_complete: Callable[[str, str], None],
        on_error: Callable[[str], None],
    ):
        """
        Stream chat response from OpenAI API.

        Args:
            model_name: Model to use
            messages: Conversation messages
            show_thinking: Whether to show thinking for reasoning models
            on_content_update: Callback(content, thinking) for streaming updates
            on_complete: Callback(final_content, final_thinking) when done
            on_error: Callback(error_msg) on error
        """

        def send_request():
            try:
                self.app._add_log("chat_api_call", f"Sending to OpenAI {model_name}")

                use_responses_api = (
                    llm_utils.is_reasoning_model(model_name) and show_thinking
                )

                if use_responses_api:
                    effort = os.getenv("OPENAI_REASONING_EFFORT", "medium")
                    params = {
                        "model": model_name,
                        "input": messages,
                        "reasoning": {
                            "effort": effort,
                            "summary": "auto",
                        },
                        "stream": True,
                    }
                    max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
                    if max_tokens:
                        params["max_output_tokens"] = max_tokens

                    stream = self.openai_client.responses.create(**params)
                else:
                    params = llm_utils.get_model_parameters(model_name)
                    params["messages"] = messages
                    params["stream"] = True
                    stream = self.openai_client.chat.completions.create(**params)

                full_response = ""
                full_thinking = ""
                last_update_time = 0
                update_interval = 0.3
                chunk_count = 0

                if use_responses_api:
                    last_thinking_update_time = 0
                    for event in stream:
                        if hasattr(event, "type"):
                            if event.type == "response.reasoning_summary_text.delta":
                                full_thinking += event.delta

                                current_time = time.time()
                                if (
                                    current_time - last_thinking_update_time
                                    >= update_interval
                                ):
                                    self.app.call_from_thread(
                                        on_content_update,
                                        full_response,
                                        full_thinking,
                                    )
                                    last_thinking_update_time = current_time

                            elif event.type == "response.output_text.delta":
                                full_response += event.delta
                                chunk_count += 1

                                current_time = time.time()
                                if (
                                    current_time - last_update_time >= update_interval
                                ) or (chunk_count % 10 == 0):
                                    self.app.call_from_thread(
                                        on_content_update,
                                        full_response,
                                        full_thinking,
                                    )
                                    last_update_time = current_time
                else:
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content is not None:
                            full_response += chunk.choices[0].delta.content
                            chunk_count += 1

                            current_time = time.time()
                            if (current_time - last_update_time >= update_interval) or (
                                chunk_count % 10 == 0
                            ):
                                self.app.call_from_thread(
                                    on_content_update,
                                    full_response,
                                    "",
                                )
                                last_update_time = current_time

                self.app.call_from_thread(
                    on_complete,
                    full_response,
                    full_thinking,
                )

            except Exception as e:
                error_msg = f"Chat Error: {str(e)}"
                if self.app:
                    self.app._add_log("chat_error", f"OpenAI error: {str(e)}")
                    self.app.call_from_thread(
                        on_error,
                        error_msg,
                    )

        threading.Thread(target=send_request, daemon=True).start()
