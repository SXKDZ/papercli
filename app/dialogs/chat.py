"""
Chat dialog for interacting with LLMs about selected papers.
"""

import os
import platform
import subprocess
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import PyPDF2
from openai import OpenAI
from prompt_toolkit.application import get_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import UIContent
from prompt_toolkit.layout.containers import HSplit, ScrollOffsets, VSplit, Window
from prompt_toolkit.layout.controls import UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import Margin, ScrollbarMargin
from prompt_toolkit.widgets import Button, Dialog, TextArea
from rich.console import Console
from rich.markdown import Markdown

from ..prompts import ChatPrompts
from ..services import BackgroundOperationService, LLMSummaryService, PaperService
from ..services.pdf import PDFManager


class SpacingMargin(Margin):
    """A simple margin that creates spacing with the specified number of spaces."""

    def __init__(self, width: int = 1):
        self.width = width

    def get_width(self, ui_content):
        return self.width

    def create_margin(self, window_render_info, width, height):
        return [" " * width for _ in range(height)]


class ChatDisplayControl(UIControl):
    def __init__(
        self,
        chat_history: List[Dict[str, Any]],
        chat_width: int,
        model_name: str = "gpt-4o",
        log_callback: Callable = None,
    ):
        self.chat_history = chat_history
        self.chat_width = chat_width
        self.model_name = model_name
        self.log_callback = log_callback
        self._cursor_line = 0  # Current cursor position in content
        self._content_height = 0  # To be calculated after rendering

    def create_content(self, width: int, height: int) -> UIContent:
        output = StringIO()
        console = Console(
            file=output,
            force_terminal=True,  # Enable ANSI output
            width=self.chat_width
            - 5,  # Reduce by 5 to account for SpacingMargin(2) + ScrollbarMargin(3)
            legacy_windows=False,
            _environ={},  # Ensure clean environment for consistent output
        )

        for entry in self.chat_history:
            role = entry["role"]
            content = entry["content"]

            if role == "user":
                console.print(f"⏵ User", style="bold green")
                console.print(content)
            elif role == "assistant":
                model_name = self.model_name
                console.print(f"⏵ Model ({model_name})", style="bold blue")
                # Render markdown with Rich using better code differentiation
                md = Markdown(
                    content,
                    code_theme="friendly",
                    inline_code_lexer="text",
                    inline_code_theme="friendly",
                )
                console.print(md)
            elif role == "system":
                console.print(f"⏵ System", style="bold magenta")
                console.print(f"{content}", style="italic")
            console.print()  # Add blank line

        # Get ANSI formatted output and return all lines (let Window handle scrolling)
        ansi_output = output.getvalue()
        all_lines = ansi_output.splitlines()
        self._content_height = len(all_lines)

        def get_line_tokens(i: int) -> List[Tuple[str, str]]:
            if i < len(all_lines):
                line_text = all_lines[i]
                try:
                    # Use ANSI to convert to prompt-toolkit formatted text
                    ansi_formatted = ANSI(line_text)
                    # Convert to list of tuples format expected by prompt-toolkit
                    if hasattr(ansi_formatted, "__iter__"):
                        try:
                            return list(ansi_formatted)
                        except:
                            pass

                    # More sophisticated ANSI parsing to handle mixed formatting
                    import re

                    segments = []
                    current_pos = 0
                    current_style = ""

                    # Find all ANSI codes and their positions
                    ansi_pattern = r"\x1b\[([0-9;]*)m"
                    matches = list(re.finditer(ansi_pattern, line_text))

                    for match in matches:
                        # Add text before this ANSI code
                        if match.start() > current_pos:
                            text_segment = line_text[current_pos : match.start()]
                            if text_segment:
                                segments.append((current_style, text_segment))

                        # Update style based on ANSI code
                        code = match.group(1)
                        if code == "1":  # Bold
                            if "fg:" in current_style:
                                current_style = "bold " + current_style
                            else:
                                current_style = "bold"
                        elif code == "3":  # Italic
                            current_style = "italic"
                        elif code == "32":  # Green
                            if "bold" in current_style:
                                current_style = "bold fg:green"
                            else:
                                current_style = "fg:green"
                        elif code == "34":  # Blue
                            if "bold" in current_style:
                                current_style = "bold fg:blue"
                            else:
                                current_style = "fg:blue"
                        elif code == "33":  # Yellow -> Gray
                            if "bold" in current_style:
                                current_style = "bold fg:#606060"
                            else:
                                current_style = "fg:#606060"
                        elif code == "35":  # Magenta
                            if "bold" in current_style:
                                current_style = "bold fg:magenta"
                            else:
                                current_style = "fg:magenta"
                        elif code == "1;32":  # Bold Green -> Muted Green
                            current_style = "bold fg:#228B22"
                        elif code == "1;34":  # Bold Blue -> Muted Blue
                            current_style = "bold fg:#4682B4"
                        elif code == "1;33":  # Bold Yellow -> Bold Gray
                            current_style = "bold fg:#606060"
                        elif code == "1;35":  # Bold Magenta -> Muted Magenta
                            current_style = "bold fg:#9932CC"
                        elif code == "0" or code == "":  # Reset
                            current_style = ""

                        current_pos = match.end()

                    # Add remaining text
                    if current_pos < len(line_text):
                        remaining_text = line_text[current_pos:]
                        if remaining_text:
                            segments.append((current_style, remaining_text))

                    # If no segments were created, just return cleaned text
                    if not segments:
                        clean_text = re.sub(r"\x1b\[[0-9;]*m", "", line_text)
                        return [("", clean_text)]

                    return segments

                except Exception as e:
                    # Final fallback: plain text
                    import re

                    clean_text = re.sub(r"\x1b\[[0-9;]*m", "", line_text)
                    return [("", clean_text)]
            else:
                return [("", "")]

        # Ensure cursor is within bounds
        if self._content_height > 0:
            self._cursor_line = max(0, min(self._cursor_line, self._content_height - 1))
        else:
            self._cursor_line = 0

        return UIContent(
            get_line=get_line_tokens,
            line_count=len(
                all_lines
            ),  # Return total line count so Window can handle scrolling
            show_cursor=True,  # Show cursor for navigation
            cursor_position=Point(0, self._cursor_line),  # Use tracked cursor position
        )

    def get_invalidate_events(self):
        # Return empty list to avoid compatibility issues
        return []

    def is_focusable(self):
        return True

    def move_cursor_up(self):
        """Move cursor up by one line."""
        if self._cursor_line > 0:
            self._cursor_line -= 1
            get_app().invalidate()

    def move_cursor_down(self):
        """Move cursor down by one line."""
        if self._cursor_line < self._content_height - 1:
            self._cursor_line += 1
            get_app().invalidate()

    def _refresh_content_height(self):
        """Refresh content height by re-rendering the content."""
        try:
            # Re-render content to get accurate height
            output = StringIO()
            console = Console(
                file=output,
                force_terminal=True,
                width=self.chat_width - 5,
                legacy_windows=False,
                _environ={},
            )

            for entry in self.chat_history:
                role = entry["role"]
                content = entry["content"]

                if role == "user":
                    console.print(f"⏵ User", style="bold green")
                    console.print(content)
                elif role == "assistant":
                    model_name = self.model_name
                    console.print(f"⏵ Model ({model_name})", style="bold blue")
                    md = Markdown(
                        content,
                        code_theme="friendly",
                        inline_code_lexer="text",
                        inline_code_theme="friendly",
                    )
                    console.print(md)
                elif role == "system":
                    console.print(f"⏵ System", style="bold magenta")
                    console.print(f"{content}", style="italic")
                console.print()  # Add blank line

            ansi_output = output.getvalue()
            all_lines = ansi_output.splitlines()
            self._content_height = len(all_lines)

        except Exception as e:
            if self.log_callback:
                self.log_callback(
                    "content_refresh_error", f"Error refreshing content height: {e}"
                )

    def move_cursor_to_bottom(self):
        """Move cursor to the bottom of content."""
        if self._content_height > 0:
            self._cursor_line = self._content_height - 1
            get_app().invalidate()


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
        self.chat_width = 180  # Define chat width
        self.paper_service = PaperService()
        self.background_service = BackgroundOperationService(
            status_bar=self.status_bar, log_callback=self.log_callback
        )
        self.pdf_manager = PDFManager()

        # Initialize OpenAI client
        self.openai_client = OpenAI()
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

        # Chat history
        self.chat_history = []

        # Create UI components
        self._create_ui_components()
        self._setup_key_bindings()

        # Initialize the chat with paper details
        self._initialize_chat()

    def _initialize_chat(self):
        """Initialize the chat with paper details."""
        if not self.papers:
            self.chat_history.append(
                {"role": "system", "content": "No papers selected for chat."}
            )
            return

        # Get paper details and potentially generate summaries
        paper_details = []
        papers_needing_summaries = []
        for paper in self.papers:
            fields = self._get_paper_fields(paper)
            if not fields["notes"] and fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    papers_needing_summaries.append(paper)

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
                pdf_accessible = False
                if fields["pdf_path"]:
                    absolute_path = self.pdf_manager.get_absolute_path(
                        fields["pdf_path"]
                    )
                    pdf_accessible = os.path.exists(absolute_path)

                if pdf_accessible:

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
            return f"**Paper {index}: {fields['title']}**\n\n{fields['notes']}"
        else:
            # No notes available, show basic paper info
            paper_info = f"**Paper {index}: {fields['title']}**\n\nAuthors: {fields['authors']}\nVenue: {fields['venue']} ({fields['year']})"
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

        # Invalidate the app to trigger a redraw
        get_app().invalidate()

    def _create_ui_components(self):
        """Create the UI components for the chat dialog."""
        # Chat display area using ChatDisplayControl for rich text and custom scrolling
        self.chat_display_control = ChatDisplayControl(
            chat_history=self.chat_history,
            chat_width=self.chat_width,
            model_name=self.model_name,
            log_callback=self.log_callback,
        )

        # Chat window with scrollbar and spacing - use Window's built-in scrolling
        self.chat_window = Window(
            content=self.chat_display_control,
            wrap_lines=False,
            height=Dimension(min=30, preferred=35, max=40),
            scroll_offsets=ScrollOffsets(top=1, bottom=1),  # Enable built-in scrolling
            right_margins=[
                SpacingMargin(width=2),  # Add 2 spaces before scrollbar
                ScrollbarMargin(display_arrows=True),
            ],
        )

        # User input area
        self.user_input = TextArea(
            text="",
            multiline=True,
            wrap_lines=True,
            scrollbar=True,
            height=Dimension(min=5, max=5),
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

        self.close_button = Button(
            text="Close",
            handler=self._handle_close,
        )

        # Button layout (vertical)
        button_container = HSplit(
            [
                self.send_button,
                Window(height=Dimension.exact(1)),  # Spacer
                self.save_button,
                Window(height=Dimension.exact(1)),  # Spacer
                self.close_button,
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
                self.chat_window,
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
            width=Dimension(min=160, preferred=self.chat_width),
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

        @kb.add("<any>")
        def _(event):
            # Handle all character input to prevent it from reaching main app
            if event.data and len(event.data) == 1:
                if event.data.isprintable():
                    current_control = event.app.layout.current_control
                    if hasattr(current_control, "buffer"):
                        current_control.buffer.insert_text(event.data)
                # For non-printable characters (like escape sequence remnants), just ignore them

        # Create condition to check if we should handle scrolling keys
        @Condition
        def should_handle_scroll_keys():
            current_window = get_app().layout.current_window
            # Only handle scroll keys when chat window has focus, not input box
            return current_window == self.chat_window

        @kb.add("up", filter=should_handle_scroll_keys)
        def _(event):
            # Scroll up in the chat window
            self.chat_display_control.move_cursor_up()

        @kb.add("down", filter=should_handle_scroll_keys)
        def _(event):
            # Scroll down in the chat window
            self.chat_display_control.move_cursor_down()

        # Create condition for input box focus
        @Condition
        def input_box_has_focus():
            return get_app().layout.current_window == self.user_input.window

        @kb.add("up", filter=input_box_has_focus)
        def _(event):
            # Let TextArea handle up key natively - don't bubble to main app
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.cursor_up()

        @kb.add("down", filter=input_box_has_focus)
        def _(event):
            # Let TextArea handle down key natively - don't bubble to main app
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.cursor_down()

        @kb.add("home")
        def _(event):
            # Handle Home key - move cursor to beginning of line
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.cursor_position = (
                    current_control.buffer.document.get_start_of_line_position()
                )

        @kb.add("end")
        def _(event):
            # Handle End key - move cursor to end of line
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.cursor_position = (
                    current_control.buffer.document.get_end_of_line_position()
                )

        @kb.add("escape")
        def _(event):
            # Close dialog on escape key
            self._handle_close()

        @kb.add("c-k")
        def _(event):
            # Cut text from cursor to end of line, or delete empty line
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                buffer = current_control.buffer
                current_line = buffer.document.current_line

                # If the line is empty, delete the entire line
                if not current_line.strip():
                    buffer.delete_line()
                else:
                    # Otherwise, delete from cursor to end of line
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

        @kb.add("space")
        def _(event):
            # Handle space key specifically
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                current_control.buffer.insert_text(" ")

        # Apply key bindings to the container
        self.container.key_bindings = merge_key_bindings(
            [
                self.container.key_bindings or KeyBindings(),
                kb,
            ]
        )

    def _get_provider_display_name(self) -> str:
        """Get the display name for ChatGPT with model info."""
        return f"ChatGPT ({self.model_name})"

    def _handle_send(self):
        """Handle sending a message."""
        user_message = self.user_input.text.strip()
        if not user_message:
            return

        # Add user message to history
        self.chat_history.append({"role": "user", "content": user_message})

        # Log the user message
        if self.log_callback:
            self.log_callback("chat_user", f"User: {user_message}")

        # Clear input
        self.user_input.text = ""

        # Invalidate to update display first, then scroll to bottom
        get_app().invalidate()

        # Use call_soon to ensure content is rendered before scrolling
        get_app().loop.call_soon(lambda: self._scroll_to_bottom())

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
        get_app().invalidate()

        # Delay scroll to ensure content is rendered
        get_app().loop.call_soon(lambda: self._scroll_to_bottom())

        # Run LLM response generation in background thread with streaming
        def get_response_background():
            try:
                # Use streaming to get response
                def on_chunk(chunk_text):
                    # Update the assistant response in place
                    streaming_placeholder["content"] += chunk_text

                    # Schedule UI update in main thread
                    get_app().loop.call_soon_threadsafe(
                        lambda: (get_app().invalidate(), self._scroll_to_bottom())
                    )

                # Get streaming response
                final_response = self._get_llm_response_streaming(
                    user_message, on_chunk
                )

                # Schedule final UI update
                def schedule_final_update():
                    streaming_placeholder["content"] = final_response
                    if self.log_callback:
                        self.log_callback(
                            "chat_assistant",
                            f"{self._get_provider_display_name()}: {final_response}",
                        )
                    if self.status_bar:
                        self.status_bar.set_success(
                            f"Response received from {self._get_provider_display_name()}"
                        )
                    get_app().invalidate()
                    self._scroll_to_bottom()

                get_app().loop.call_soon_threadsafe(schedule_final_update)

            except Exception as e:
                get_app().loop.call_soon_threadsafe(
                    lambda: (
                        self.status_bar
                        and self.status_bar.set_error(
                            f"Failed to get response: {str(e)}"
                        ),
                        streaming_placeholder.update(
                            {"content": f"Sorry, I encountered an error: {str(e)}"}
                        ),
                        get_app().invalidate(),
                    )
                )

        # Start background thread
        thread = threading.Thread(target=get_response_background, daemon=True)
        thread.start()

    def _scroll_to_bottom(self):
        """Scroll the chat window to the bottom."""
        # Move cursor to bottom so Window scrolls to show it
        if hasattr(self, "chat_display_control"):
            # Force content refresh first to get accurate content height
            self.chat_display_control._refresh_content_height()
            self.chat_display_control.move_cursor_to_bottom()

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

            # Extract first N pages from PDF if available (configurable)
            pdf_content_added = False
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    try:
                        max_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
                        pdf_text = self._extract_first_pages(
                            absolute_path, max_pages=max_pages
                        )
                        if pdf_text:
                            paper_context += f"First {max_pages} pages attached to this chat:\n{pdf_text}\n"
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
        return self.user_input  # Focus input box so users can start typing immediately
