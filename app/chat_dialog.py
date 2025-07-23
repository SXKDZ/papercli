"""
Chat dialog for interacting with LLMs about selected papers.
"""

import os
import platform
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import PyPDF2
from openai import OpenAI
from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button, Dialog, TextArea

from .prompts import ChatPrompts
from .services import BackgroundOperationService, LLMSummaryService, PaperService


class ChatDialog:
    """A dialog for chatting with LLMs about papers."""

    def __init__(
        self,
        papers: List[Dict[str, Any]],
        callback: Callable,
        log_callback: Callable,
        status_bar=None,
    ):
        self.papers = papers
        self.callback = callback
        self.log_callback = log_callback
        self.status_bar = status_bar
        self.result = None
        self.paper_service = PaperService()
        self.background_service = BackgroundOperationService(
            status_bar=self.status_bar, log_callback=self.log_callback
        )

        # Initialize OpenAI client
        self.openai_client = OpenAI()
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

        # Chat history
        self.chat_history = []

        # Input history for Up/Down navigation
        self.input_history = []
        self.history_index = -1

        # Initialize the chat with paper details
        self._initialize_chat()

        # Create UI components
        self._create_ui_components()
        self._setup_key_bindings()

    def _initialize_chat(self):
        """Initialize the chat with paper details."""
        if not self.papers:
            self.chat_history.append(
                {"role": "system", "content": "No papers selected for chat."}
            )
            return

        # Get paper details and potentially generate summaries
        paper_details = []
        papers_needing_summaries = [
            paper
            for paper in self.papers
            if not self._get_paper_fields(paper)["notes"]
            and self._get_paper_fields(paper)["pdf_path"]
            and os.path.exists(self._get_paper_fields(paper)["pdf_path"])
        ]

        # Generate summaries using the shared service
        if papers_needing_summaries:
            summary_service = LLMSummaryService(
                paper_service=self.paper_service,
                background_service=self.background_service,
                log_callback=self.log_callback,
            )

            def on_summaries_complete(tracking):
                # Update in-memory paper objects with summaries
                for paper_id, summary, paper_title in tracking["queue"]:
                    for paper in self.papers:
                        if paper.id == paper_id:
                            paper.notes = summary
                            if self.log_callback:
                                self.log_callback(
                                    f"chat_summary_memory_updated_{paper_id}",
                                    f"Updated in-memory paper: {paper.title[:50]}...",
                                )
                            break
                self._refresh_chat_display()

            summary_service.generate_summaries(
                papers=papers_needing_summaries,
                on_all_complete=on_summaries_complete,
                operation_prefix="chat_summary",
            )

        # Second pass: build paper details for display
        for i, paper in enumerate(self.papers, 1):
            # Check if we need to generate a summary
            fields = self._get_paper_fields(paper)

            if not fields["notes"]:
                # Try to generate summary from PDF
                if fields["pdf_path"] and os.path.exists(fields["pdf_path"]):

                    # Add placeholder message for background generation
                    paper_info = (
                        self._format_paper_info(paper, i)
                        + "\n\n(Summary being generated in background...)"
                    )
                else:
                    # No PDF available, use standard formatting
                    paper_info = self._format_paper_info(paper, i)
            else:
                # Notes available, use standard formatting
                paper_info = self._format_paper_info(paper, i)

            paper_details.append(paper_info)

        # Add initial system message with paper details (UI only, not sent to LLM)
        initial_content = self._build_initial_content(paper_details)
        self.chat_history.append(
            {"role": "assistant", "content": initial_content, "ui_only": True}
        )

    def _get_paper_fields(self, paper):
        """Extract common paper fields."""
        return {
            "title": getattr(paper, "title", "Unknown Title"),
            "authors": getattr(paper, "author_names", "Unknown Authors"),
            "venue": getattr(paper, "venue_full", "Unknown Venue"),
            "year": getattr(paper, "year", "Unknown Year"),
            "abstract": getattr(paper, "abstract", "") or "",
            "notes": (getattr(paper, "notes", "") or "").strip(),
            "pdf_path": getattr(paper, "pdf_path", ""),
        }

    def _format_paper_info(self, paper, index):
        """Format paper information for display."""
        fields = self._get_paper_fields(paper)

        if fields["notes"]:
            return f"**Paper {index}: {fields['title']}**\n{fields['notes']}"
        else:
            # No notes available, show basic paper info
            paper_info = f"**Paper {index}: {fields['title']}**\nAuthors: {fields['authors']}\nVenue: {fields['venue']} ({fields['year']})"
            if fields["abstract"]:
                paper_info += f"\n\nAbstract: {fields['abstract']}"
            return paper_info

    def _build_initial_content(self, paper_details):
        """Build the initial content message for the chat."""
        if len(self.papers) == 1:
            return ChatPrompts.initial_single_paper(paper_details[0])
        else:
            paper_content = "\n\n---\n\n".join(paper_details)
            return ChatPrompts.initial_multiple_papers(len(self.papers), paper_content)

    def _refresh_chat_display(self):
        """Refresh the chat display by rebuilding the initial content with updated paper info."""
        # Rebuild paper details using unified formatting
        paper_details = [
            self._format_paper_info(paper, i) for i, paper in enumerate(self.papers, 1)
        ]

        # Build the updated content
        updated_content = self._build_initial_content(paper_details)

        # Update the initial assistant message in chat history
        if (
            len(self.chat_history) > 0
            and self.chat_history[0]["role"] == "assistant"
            and self.chat_history[0].get("ui_only", False)
        ):
            self.chat_history[0]["content"] = updated_content

        # Refresh the display
        self.chat_display.text = self._format_chat_history()

    def _create_ui_components(self):
        """Create the UI components for the chat dialog."""
        # Chat display area (scrollable) with fixed height
        self.chat_display = TextArea(
            text=self._format_chat_history(),
            read_only=True,
            wrap_lines=True,
            scrollbar=True,
            height=Dimension(
                min=25, preferred=35, max=40
            ),  # Longer height for better viewing
        )

        # User input area
        self.user_input = TextArea(
            text="",
            multiline=True,
            wrap_lines=True,
        )

        # Buttons
        self.send_button = Button(
            text="Send",
            handler=self._handle_send,
        )

        self.save_button = Button(
            text="Save",
            handler=self._handle_save,
        )

        # Button layout (vertical)
        button_container = HSplit(
            [
                self.send_button,
                Window(height=Dimension.exact(1)),  # Spacer
                self.save_button,
            ]
        )

        # Input area layout
        input_container = VSplit(
            [
                self.user_input,
                Window(width=Dimension.exact(2)),  # Spacer
                button_container,
            ]
        )

        # Main layout with fixed dimensions
        self.container = HSplit(
            [
                # Chat display
                self.chat_display,
                Window(height=Dimension.exact(1)),  # Spacer
                # Input area
                input_container,
            ]
        )

        # Create dialog with wider dimensions
        self.dialog = Dialog(
            title=f"Chat with ChatGPT ({self.model_name})",
            body=self.container,
            with_background=False,
            modal=True,
            width=Dimension(min=160, preferred=180),
        )

    def _setup_key_bindings(self):
        """Setup key bindings for the dialog."""
        kb = KeyBindings()

        @kb.add("c-s")
        def _(event):
            self._handle_save()

        @kb.add("enter")
        def _(event):
            # Only send if in the input field, otherwise default behavior
            if event.app.layout.current_window == self.user_input.window:
                self._handle_send()

        @kb.add("c-j")
        def _(event):
            # Add newline in input field
            if event.app.layout.current_window == self.user_input.window:
                current_control = event.app.layout.current_control
                if hasattr(current_control, "buffer"):
                    current_control.buffer.insert_text("\n")

        @kb.add("escape")
        def _(event):
            self._handle_close()

        @kb.add("c-k")
        def _(event):
            # Cut text from cursor to end of line
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                buffer = current_control.buffer
                buffer.delete(count=len(buffer.document.current_line_after_cursor))

        # Add backspace and delete handling for text input
        @kb.add("backspace")
        def _(event):
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.delete_before_cursor()

        @kb.add("delete")
        def _(event):
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.delete()

        @kb.add("up")
        def _(event):
            # Navigate input history backward when in input field, otherwise scroll chat
            if event.app.layout.current_window == self.user_input.window:
                if (
                    self.input_history
                    and self.history_index < len(self.input_history) - 1
                ):
                    self.history_index += 1
                    self.user_input.text = self.input_history[-(self.history_index + 1)]
                    self.user_input.buffer.cursor_position = len(self.user_input.text)
            else:
                # Scroll chat display up
                self.chat_display.buffer.cursor_up(count=1)

        @kb.add("down")
        def _(event):
            # Navigate input history forward when in input field, otherwise scroll chat
            if event.app.layout.current_window == self.user_input.window:
                if self.history_index > 0:
                    self.history_index -= 1
                    self.user_input.text = self.input_history[-(self.history_index + 1)]
                    self.user_input.buffer.cursor_position = len(self.user_input.text)
                elif self.history_index == 0:
                    self.history_index = -1
                    self.user_input.text = ""
            else:
                # Scroll chat display down
                self.chat_display.buffer.cursor_down(count=1)

        @kb.add("pageup")
        def _(event):
            # Scroll chat display up
            if event.app.layout.current_window == self.chat_display.window:
                self.chat_display.buffer.cursor_up(count=10)

        @kb.add("pagedown")
        def _(event):
            # Scroll chat display down
            if event.app.layout.current_window == self.chat_display.window:
                self.chat_display.buffer.cursor_down(count=10)

        @kb.add("space")
        def _(event):
            # Handle space key specifically
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.insert_text(" ")

        @kb.add("<any>")
        def _(event):
            # Handle all character input to prevent it from reaching main app
            if event.data and len(event.data) == 1 and event.data.isprintable():
                current_control = event.app.layout.current_control
                if hasattr(current_control, "buffer"):
                    current_control.buffer.insert_text(event.data)

        # Apply key bindings to the container
        self.container.key_bindings = merge_key_bindings(
            [
                self.container.key_bindings or KeyBindings(),
                kb,
            ]
        )

    def _format_chat_history(self) -> str:
        """Format the chat history for display."""
        formatted = []
        for entry in self.chat_history:
            role = entry["role"]
            content = entry["content"]

            if role == "user":
                formatted.append(f"You: {content}")
            elif role == "assistant":
                # Use visual formatting for ChatGPT responses
                provider_name = self._get_provider_display_name()
                # Add indentation and different styling for ChatGPT responses
                lines = content.split("\n")
                formatted.append(f"{provider_name}:")
                for line in lines:
                    formatted.append(f"  {line}")  # Indent ChatGPT responses
            elif role == "system":
                formatted.append(f"System: {content}")

            formatted.append("")  # Add empty line between messages

        return "\n".join(formatted)

    def _get_provider_display_name(self) -> str:
        """Get the display name for ChatGPT with model info."""
        return f"ChatGPT ({self.model_name})"

    def _handle_send(self):
        """Handle sending a message."""
        user_message = self.user_input.text.strip()
        if not user_message:
            return

        # Add to input history for Up/Down navigation
        if user_message not in self.input_history:
            self.input_history.append(user_message)
        self.history_index = -1

        # Add user message to history
        self.chat_history.append({"role": "user", "content": user_message})

        # Log the user message
        if self.log_callback:
            self.log_callback("chat_user", f"User: {user_message}")

        # Clear input
        self.user_input.text = ""

        # Update display
        self.chat_display.text = self._format_chat_history()

        # Show status that we're working on the response
        if self.status_bar:
            self.status_bar.set_status(
                f"Streaming response from {self._get_provider_display_name()}...",
                "llm",
            )
            get_app().invalidate()

        # Add a placeholder for the streaming response
        streaming_placeholder = {"role": "assistant", "content": ""}
        self.chat_history.append(streaming_placeholder)
        self.chat_display.text = self._format_chat_history()
        get_app().invalidate()

        # Run LLM response generation in background thread with streaming
        def get_response_background():
            try:
                # Use streaming to get response
                def on_chunk(chunk_text):
                    # Update the assistant response in place
                    streaming_placeholder["content"] += chunk_text

                    # Schedule UI update in main thread
                    def schedule_stream_update():
                        self.chat_display.text = self._format_chat_history()
                        # Auto-scroll to bottom to follow the streaming text
                        self.chat_display.buffer.cursor_position = len(
                            self.chat_display.text
                        )
                        get_app().invalidate()

                    get_app().loop.call_soon_threadsafe(schedule_stream_update)

                # Get streaming response
                final_response = self._get_llm_response_streaming(
                    user_message, on_chunk
                )

                # Schedule final UI update
                def schedule_final_update():
                    # Ensure the final content is set correctly
                    streaming_placeholder["content"] = final_response

                    # Log the final assistant response
                    if self.log_callback:
                        self.log_callback(
                            "chat_assistant",
                            f"{self._get_provider_display_name()}: {final_response}",
                        )

                    self.chat_display.text = self._format_chat_history()

                    if self.status_bar:
                        self.status_bar.set_success(
                            f"Response received from {self._get_provider_display_name()}"
                        )

                    # Scroll to bottom
                    self.chat_display.buffer.cursor_position = len(
                        self.chat_display.text
                    )
                    get_app().invalidate()

                get_app().loop.call_soon_threadsafe(schedule_final_update)

            except Exception as e:

                def schedule_ui_error():
                    if self.status_bar:
                        self.status_bar.set_error(f"Failed to get response: {str(e)}")
                    streaming_placeholder["content"] = (
                        f"Sorry, I encountered an error: {str(e)}"
                    )
                    self.chat_display.text = self._format_chat_history()
                    get_app().invalidate()

                get_app().loop.call_soon_threadsafe(schedule_ui_error)

        # Start background thread
        thread = threading.Thread(target=get_response_background, daemon=True)
        thread.start()

        # Scroll to bottom
        self.chat_display.buffer.cursor_position = len(self.chat_display.text)

    def _get_llm_response_streaming(self, user_message: str, on_chunk_callback) -> str:
        """Get streaming response from ChatGPT."""
        try:
            # Prepare messages for API call
            messages = []

            # Add system message with paper context
            paper_context = self._build_paper_context()
            messages.append(
                {
                    "role": "system",
                    "content": ChatPrompts.system_message(paper_context),
                }
            )

            # Add conversation history (last 6 messages to stay within token limits)
            # Skip the last TWO entries since the last is our streaming placeholder and second-to-last is the current user message we'll add separately
            recent_history = (
                self.chat_history[-8:-2]
                if len(self.chat_history) > 8
                else self.chat_history[:-2]
            )
            for entry in recent_history:
                if (
                    entry["role"] in ["user", "assistant"]
                    and entry["content"].strip()
                    and not entry.get("ui_only", False)
                ):
                    messages.append(
                        {"role": entry["role"], "content": entry["content"]}
                    )

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Log the complete LLM request
            if self.log_callback:
                self.log_callback(
                    "chat_llm_request",
                    f"Sending request to {self.model_name} with {len(messages)} messages",
                )
                # Log all messages in the conversation
                for i, msg in enumerate(messages):
                    self.log_callback(
                        "chat_llm_messages",
                        f"Message {i+1} ({msg['role']}): {msg['content']}",
                    )

            # Call OpenAI API with streaming
            stream = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=4000,
                temperature=0.7,
                stream=True,
            )

            # Collect the full response while streaming
            full_response = ""
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    chunk_text = chunk.choices[0].delta.content
                    full_response += chunk_text
                    # Call the callback for each chunk
                    on_chunk_callback(chunk_text)

            return full_response.strip()

        except Exception as e:
            if self.log_callback:
                self.log_callback(
                    "openai_error", f"Error getting ChatGPT streaming response: {e}"
                )
            error_msg = f"Error: Failed to get response from ChatGPT. {str(e)}"
            on_chunk_callback(error_msg)
            return error_msg

    def _build_paper_context(self) -> str:
        """Build context string about the papers for the LLM."""
        if not self.papers:
            return "No papers are currently selected for discussion."

        context_parts = []
        for i, paper in enumerate(self.papers, 1):
            fields = self._get_paper_fields(paper)

            paper_context = f"Paper {i}: {fields['title']}\n"
            paper_context += f"Authors: {fields['authors']}\n"
            paper_context += f"Venue: {fields['venue']} ({fields['year']})\n"

            if fields["abstract"]:
                paper_context += f"Abstract: {fields['abstract']}\n"

            # Extract first 10 pages from PDF if available
            pdf_content_added = False
            if fields["pdf_path"] and os.path.exists(fields["pdf_path"]):
                try:
                    pdf_text = self._extract_first_pages(
                        fields["pdf_path"], max_pages=10
                    )
                    if pdf_text:
                        paper_context += (
                            f"First 10 pages attached to this chat:\n{pdf_text}\n"
                        )
                        pdf_content_added = True
                except Exception as e:
                    if self.log_callback:
                        self.log_callback(
                            "pdf_extract_error",
                            f"Failed to extract PDF pages for '{fields['title']}': {e}",
                        )

            # Only include notes/summary if we don't have PDF content (to avoid redundancy)
            if not pdf_content_added and fields["notes"]:
                paper_context += f"Notes: {fields['notes']}\n"

            context_parts.append(paper_context)

        return ChatPrompts.paper_context_header() + "\n".join(context_parts)

    def _extract_first_pages(self, pdf_path: str, max_pages: int = 10) -> str:
        """Extract text from the first N pages of a PDF."""
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                text_parts = []
                pages_to_extract = min(len(pdf_reader.pages), max_pages)

                for page_num in range(pages_to_extract):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_parts.append(f"Page {page_num + 1}:\n{page_text.strip()}")

                return "\n\n".join(text_parts)
        except Exception as e:
            if self.log_callback:
                self.log_callback(
                    "pdf_extract_error", f"Failed to extract PDF text: {e}"
                )
            return ""

    def _handle_save(self):
        """Handle saving the chat to a file."""
        try:
            # Get data directory
            data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
            if data_dir_env:
                data_dir = Path(data_dir_env).expanduser().resolve()
            else:
                data_dir = Path.home() / ".papercli"

            # Create chats directory if it doesn't exist
            chats_dir = data_dir / "chats"
            chats_dir.mkdir(exist_ok=True, parents=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            paper_titles = []
            for paper in self.papers:
                title = getattr(paper, "title", "Unknown")
                # Clean title for filename
                clean_title = "".join(
                    c for c in title if c.isalnum() or c in (" ", "-", "_")
                ).rstrip()
                paper_titles.append(clean_title[:30])  # Limit length

            if paper_titles:
                filename = f"chat_{timestamp}_{'-'.join(paper_titles[:2])}.md"
            else:
                filename = f"chat_{timestamp}.md"

            filepath = chats_dir / filename

            # Format chat content for file
            content = self._format_chat_for_file()

            # Write to file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # Open file in system explorer/finder
            self._open_file_in_explorer(filepath)

            # Log success
            if self.log_callback:
                self.log_callback("chat_save", f"Chat saved to: {filepath}")

            # Update status
            if self.status_bar:
                self.status_bar.set_success(f"Chat saved to {filepath.name}")

        except Exception as e:
            # Log error
            if self.log_callback:
                self.log_callback("chat_save_error", f"Failed to save chat: {str(e)}")

            # Update status
            if self.status_bar:
                self.status_bar.set_error(f"Failed to save chat: {str(e)}")

    def _format_chat_for_file(self) -> str:
        """Format the chat history for saving to a file."""
        lines = []

        # Add header
        lines.append("# Chat Session")
        lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Model**: {self.model_name}")
        lines.append("")

        # Add paper information
        if self.papers:
            lines.append("## Papers Discussed")
            for i, paper in enumerate(self.papers, 1):
                fields = self._get_paper_fields(paper)
                lines.append(f"**Paper {i}**: {fields['title']}")
                lines.append(f"- Authors: {fields['authors']}")
                lines.append(f"- Venue: {fields['venue']} ({fields['year']})")
                if fields["abstract"]:
                    lines.append(f"- Abstract: {fields['abstract']}")
                lines.append("")

        # Add chat history
        lines.append("## Chat History")
        lines.append("")

        for entry in self.chat_history:
            role = entry["role"]
            content = entry["content"]

            if role == "user":
                lines.append(f"**You**: {content}")
            elif role == "assistant":
                provider_name = self._get_provider_display_name()
                lines.append(f"**{provider_name}**: {content}")
            elif role == "system":
                lines.append(f"**System**: {content}")

            lines.append("")

        return "\n".join(lines)

    def _open_file_in_explorer(self, filepath: Path):
        """Open the file in the system's default file explorer."""
        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                # Use 'open' command to reveal file in Finder
                subprocess.run(["open", "-R", str(filepath)], check=False)
            elif system == "Windows":  # Windows
                # Use 'explorer' command to select file in Explorer
                subprocess.run(["explorer", "/select,", str(filepath)], check=False)
            else:  # Linux and other Unix-like systems
                # Try to open the directory containing the file
                subprocess.run(["xdg-open", str(filepath.parent)], check=False)
        except Exception as e:
            # Log error but don't fail the save operation
            if self.log_callback:
                self.log_callback(
                    "explorer_open_error", f"Failed to open file in explorer: {str(e)}"
                )

    def _handle_close(self):
        """Handle closing the dialog."""
        self.result = None
        if self.callback:
            self.callback(self.result)

    def show(self):
        """Show the chat dialog."""
        return self.dialog

    def get_initial_focus(self):
        """Return the control that should receive initial focus."""
        return self.user_input
