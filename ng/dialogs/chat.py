import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import PyPDF2
from openai import OpenAI
try:
    import tiktoken
except ImportError:
    tiktoken = None
from pluralizer import Pluralizer
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static

from ng.services import (
    BackgroundOperationService,
    LLMSummaryService,
    PaperService,
    PDFManager,
    SystemService,
    ThemeService,
)
from ng.services.llm_utils import get_model_parameters
from ng.services.prompts import ChatPrompts

_pluralizer = Pluralizer()


class ChatDialog(ModalScreen):
    """A modal dialog for chat interactions with OpenAI."""

    class StreamingUpdate(Message):
        """Message sent when streaming content is updated."""
        def __init__(self, content: str) -> None:
            self.content = content
            super().__init__()

    class StreamingComplete(Message):
        """Message sent when streaming is complete."""
        def __init__(self, final_content: str) -> None:
            self.final_content = final_content
            super().__init__()

    class StreamingError(Message):
        """Message sent when streaming encounters an error."""
        def __init__(self, error_message: str) -> None:
            self.error_message = error_message
            super().__init__()

    DEFAULT_CSS = """
    ChatDialog {
        align: center middle;
    }
    
    #chat-container {
        width: 95%;
        height: 85%;
        border: solid $warning;
        background: $panel;
    }
    
    #chat-title {
        text-align: center;
        text-style: bold;
        background: $warning;
        color: $text;
        height: 1;
        width: 100%;
    }
    
    #chat-history {
        height: 1fr;
        border: solid $warning;
        margin: 1;
        scrollbar-size-vertical: 2;
        scrollbar-size-horizontal: 0;
    }
    
    #chat-history:focus {
        border: solid $primary;
    }
    
    #input-area {
        height: auto;
        margin: 0 1 0 1;
        padding: 0;
    }
    
    .chat-input {
        height: 3;
        border: solid $warning;
        background: $surface;
        color: $text;
    }
    
    .chat-input:focus {
        border: solid $primary;
    }
    
    /* Chat message containers */
    .chat-message {
        margin: 1 0;
        padding: 1;
        background: transparent;
    }
    
    .chat-message:hover {
        background: $boost;
    }
    
    .chat-role-header {
        text-style: bold;
        margin: 0 0 1 0;
    }
    
    #controls-bar {
        height: auto;
        padding: 1;
        margin: 0 1 0 1;
        width: 100%;
    }
    
    #controls-left {
        height: auto;
        width: 50%;
        align: left middle;
    }
    
    #controls-right {
        height: auto;
        width: 50%;
        align: right middle;
    }
    
    .control-row {
        height: auto;
        margin: 0 0 1 0;
        align: left middle;
    }
    
    .control-label {
        width: auto;
        margin: 0 1 0 0;
        text-align: right;
        height: 1;
        content-align: center middle;
    }
    
    .compact-model-input {
        height: 1;
        width: 25;
        border: none;
        padding: 0;
        margin: 0 2 0 0;
    }
    
    .compact-input {
        height: 1;
        width: 4;
        border: none;
        padding: 0;
        margin: 0 1 0 0;
    }
    
    .compact-input:disabled {
        opacity: 0.5;
    }
    
    .compact-model-input:focus {
        border: none;
    }
    
    .compact-input:focus {
        border: none;
    }
    
    #button-bar {
        height: auto;
        align: right middle;
    }
    
    #button-bar Button {
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "send_message", "Send Message"),
        ("ctrl+s", "save_chat", "Save Chat"),
    ]

    def __init__(
        self,
        papers: List[Any],
        callback: Callable[[Dict[str, Any] | None], None],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.papers = papers or []
        self.callback = callback
        self.chat_history = []
        self.chat_display_content = ""
        self.openai_client = None
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.pdf_manager = PDFManager()
        self.summary_in_progress = False
        self.default_pdf_pages_limit = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
        self.pdf_start_page = 1
        self.pdf_end_page = self.default_pdf_pages_limit
        self.total_pdf_pages = 0

        self.paper_service = PaperService(app=self.app)
        self.background_service = BackgroundOperationService(app=None)
        self.llm_service = LLMSummaryService(
            paper_service=self.paper_service,
            background_service=self.background_service,
            app=None,
        )
        self.system_service = SystemService(self.pdf_manager)

        # Initialize OpenAI client
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
            except Exception:
                pass

        # Thread-safe state
        self._streaming_content = ""
        self._streaming_widget = None
        self._input_tokens = 0
        self._output_tokens = 0

    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens using OpenAI's tiktoken library."""
        if tiktoken is None:
            # Fallback to rough estimation if tiktoken not available
            return len(text) // 4
            
        try:
            # Use appropriate encoding for the model
            if "gpt-4" in self.model_name.lower():
                encoding = tiktoken.encoding_for_model("gpt-4")
            elif "gpt-3.5" in self.model_name.lower():
                encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            else:
                # Default to cl100k_base for most modern models
                encoding = tiktoken.get_encoding("cl100k_base")
                
            return len(encoding.encode(text))
        except Exception:
            # Fallback to rough estimation if tiktoken fails
            return len(text) // 4

    def _clean_pdf_text(self, text: str) -> str:
        """Clean PDF text to remove surrogates and other problematic characters."""
        try:
            # Remove surrogates and other problematic unicode characters
            cleaned = text.encode('utf-8', errors='ignore').decode('utf-8')
            # Remove null bytes and other control characters except newlines and tabs
            cleaned = ''.join(char for char in cleaned if ord(char) >= 32 or char in '\n\t')
            return cleaned
        except Exception:
            # If all else fails, return empty string
            return ""

    def compose(self) -> ComposeResult:
        with Container(id="chat-container"):
            selection_text = _pluralizer.pluralize("paper", len(self.papers), True)
            yield Static(f"Chat with {selection_text} selected", id="chat-title")
            with VerticalScroll(id="chat-history"):
                pass  # Content will be dynamically added
            with Container(id="input-area"):
                yield Input(
                    value="",
                    id="user-input",
                    classes="chat-input",
                    placeholder="❯ Type your message and press Enter to send...",
                )
            with Horizontal(id="controls-bar"):
                with Container(id="controls-left"):
                    with Horizontal(classes="control-row"):
                        yield Static("Model:", classes="control-label")
                        yield Input(
                            value=self.model_name,
                            id="model-input",
                            classes="compact-model-input",
                            placeholder="gpt-4o",
                        )
                    with Horizontal(classes="control-row"):
                        yield Static("Send PDF from", classes="control-label")
                        yield Input(
                            value=str(self.pdf_start_page),
                            id="pdf-start-input",
                            classes="compact-input",
                            placeholder="1",
                        )
                        yield Static("to", classes="control-label")
                        yield Input(
                            value=str(self.pdf_end_page),
                            id="pdf-end-input",
                            classes="compact-input",
                            placeholder=str(self.default_pdf_pages_limit),
                        )
                        yield Static("pages", classes="control-label")
                with Container(id="controls-right"):
                    with Horizontal(id="button-bar"):
                        yield Button("Send", id="send-button", variant="primary")
                        yield Button("Save", id="save-button", variant="default")
                        yield Button("Close", id="close-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the chat following app version logic."""
        # Set app references for services
        self.background_service.app = self.app
        self.llm_service.app = self.app

        user_input = self.query_one("#user-input", Input)
        # Ensure Input is properly configured for input
        user_input.can_focus = True
        user_input.focus()

        # Calculate total PDF pages and update input states
        self._update_pdf_controls_state()

        if not self.papers:
            self._add_system_message("No papers selected for chat.")
            return

        if not self.openai_client:
            self._add_system_message(
                "OpenAI API key not configured. Set OPENAI_API_KEY environment variable."
            )
            return

        # Initialize chat with papers following app version logic
        self._initialize_chat_with_papers()

    def _initialize_chat_with_papers(self):
        """Initialize chat with paper details, generating summaries if needed (app version logic)."""
        # Get papers that need summaries
        papers_needing_summaries = []
        for paper in self.papers:
            fields = self._get_paper_fields(paper)
            if not fields["notes"] and fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    papers_needing_summaries.append(paper)

        # Generate summaries if needed (following app version)
        if papers_needing_summaries:
            self.summary_in_progress = True
            self._disable_buttons()

            def on_summaries_complete(tracking):
                """Update in-memory paper objects with summaries (app version logic)."""
                for paper_id, summary, paper_title in tracking["queue"]:
                    for paper in self.papers:
                        if paper.id == paper_id:
                            paper.notes = summary
                            if self.app:
                                self.app._add_log(
                                    f"chat_summary_memory_updated_{paper_id}",
                                    f"Updated in-memory paper: {paper.title[:50]}...",
                                )
                            break
                self.summary_in_progress = False
                self._enable_buttons()
                self._refresh_chat_display()

            self.llm_service.generate_summaries(
                papers=papers_needing_summaries,
                on_all_complete=on_summaries_complete,
                operation_prefix="chat_summary",
            )

        # Build initial chat content
        self._build_initial_chat_content()

    def _get_paper_fields(self, paper):
        """Extract common paper fields (app version logic)."""
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
        """Format paper information for display (app version logic)."""
        fields = self._get_paper_fields(paper)

        # Always include basic paper metadata
        paper_info = (
            f"**Paper {index}: {fields['title']}**\n\n"
            f"Authors: {fields['authors']}\n"
            f"Venue: {fields['venue']} ({fields['year']})"
        )
        
        if fields["notes"]:
            paper_info += f"\n\nNotes: {fields['notes']}"
        elif fields["abstract"]:
            paper_info += f"\n\nAbstract: {fields['abstract']}"
            
        return paper_info

    def _build_initial_chat_content(self):
        """Build initial chat content (app version logic)."""
        paper_details = []
        for i, paper in enumerate(self.papers, 1):
            paper_details.append(self._format_paper_info(paper, i))

        if len(self.papers) == 1:
            initial_content = ChatPrompts.initial_single_paper(paper_details[0])
        else:
            initial_content = ChatPrompts.initial_multiple_papers(
                len(self.papers), "\n\n---\n\n".join(paper_details)
            )

        self._add_system_message(initial_content)

    def _add_system_message(self, content: str):
        """Add a system message to chat history."""
        self.chat_history.append({"role": "system", "content": content})
        self._update_display()

    def _update_display(self):
        """Update the chat display with themed colors, markdown support, and selectable content."""
        chat_container = self.query_one("#chat-history", VerticalScroll)

        # Clear existing content
        chat_container.remove_children()

        if not self.chat_history:
            welcome_text = (
                "# Chat Session\n\n"
                "*No messages yet. Type your message below and press "
                "**Enter** to send (or click Send button).*"
            )
            welcome_widget = Markdown(welcome_text)
            welcome_widget.can_focus = True
            chat_container.mount(welcome_widget)
        else:
            # No title needed - start directly with messages
            pass

            for i, entry in enumerate(self.chat_history):
                if i > 0:
                    # Add separator
                    separator = Markdown("---")
                    chat_container.mount(separator)

                role = entry["role"]
                content = entry["content"]

                # Get theme-appropriate colors using ThemeService
                if role == "user":
                    role_color = ThemeService.get_markup_color("accent", app=self.app)
                    role_text = "⏵ User"
                elif role == "assistant":
                    role_color = ThemeService.get_markup_color("success", app=self.app)
                    role_text = f"⏵ Model ({self.model_name})"
                elif role == "system":
                    role_color = ThemeService.get_markup_color("warning", app=self.app)
                    role_text = f"⏵ System ({self.model_name})"
                elif role == "loading":
                    role_color = ThemeService.get_markup_color("info", app=self.app)
                    role_text = content
                    # For loading messages, just show the text
                    loading_widget = Static(role_text, classes="chat-role-header")
                    loading_widget.styles.color = role_color
                    loading_widget.can_focus = True
                    chat_container.mount(loading_widget)
                    continue
                elif role == "error":
                    role_color = ThemeService.get_markup_color("error", app=self.app)
                    role_text = f"Error: {content}"
                    # For error messages, just show the text
                    error_widget = Static(role_text, classes="chat-role-header")
                    error_widget.styles.color = role_color
                    error_widget.can_focus = True
                    chat_container.mount(error_widget)
                    continue

                # Create role header with themed color
                role_header = Static(role_text, classes="chat-role-header")
                role_header.styles.color = role_color
                role_header.can_focus = True
                chat_container.mount(role_header)

                # Create content widget with markdown support
                # Don't modify system content - let it render as-is
                content_markdown = content

                content_widget = Markdown(content_markdown)
                content_widget.can_focus = True
                chat_container.mount(content_widget)

        # Auto-scroll to the bottom
        chat_container.scroll_end(animate=False)

    def _refresh_chat_display(self):
        """Refresh chat display (used after summary generation)."""
        # Rebuild initial content with updated summaries
        self.chat_history = []  # Clear existing history
        self._build_initial_chat_content()

    def _disable_buttons(self):
        """Disable Send and Save buttons during summary generation."""
        try:
            send_button = self.query_one("#send-button", Button)
            save_button = self.query_one("#save-button", Button)
            user_input = self.query_one("#user-input", Input)
            send_button.disabled = True
            save_button.disabled = True
            user_input.disabled = True
        except Exception:
            pass

    def _enable_buttons(self):
        """Enable Send and Save buttons after summary generation."""
        try:
            send_button = self.query_one("#send-button", Button)
            save_button = self.query_one("#save-button", Button)
            user_input = self.query_one("#user-input", Input)
            send_button.disabled = False
            save_button.disabled = False
            user_input.disabled = False
        except Exception:
            pass

    def action_save_chat(self) -> None:
        """Save the chat history (Ctrl+S)."""
        if self.summary_in_progress:
            return
        self._handle_save()

    def action_cancel(self) -> None:
        """Close dialog (Escape)."""
        self.dismiss(None)

    def action_send_message(self) -> None:
        """Send the user message (Enter)."""
        if self.summary_in_progress:
            return
        self._handle_send()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle when user presses Enter in the input field."""
        if not self.summary_in_progress:
            self._handle_send()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle model and page range input changes with validation."""
        if event.input.id == "model-input":
            self.model_name = event.value.strip() or "gpt-4o"
            if self.app:
                self.app._add_log(
                    "chat_model_change", f"Model changed to: {self.model_name}"
                )
        elif event.input.id == "pdf-start-input":
            try:
                if not event.value or not event.value.strip():
                    self.pdf_start_page = 1
                    event.input.value = "1"
                    return

                value = int(event.value)
                if value < 1:
                    value = 1
                    event.input.value = "1"
                elif self.total_pdf_pages > 0 and value > self.total_pdf_pages:
                    value = self.total_pdf_pages
                    event.input.value = str(self.total_pdf_pages)

                self.pdf_start_page = value

                # Ensure end page is not less than start page
                end_input = self.query_one("#pdf-end-input", Input)
                if self.pdf_end_page < self.pdf_start_page:
                    self.pdf_end_page = self.pdf_start_page
                    end_input.value = str(self.pdf_start_page)

            except ValueError:
                self.pdf_start_page = 1
                event.input.value = "1"

        elif event.input.id == "pdf-end-input":
            try:
                if not event.value or not event.value.strip():
                    self.pdf_end_page = max(
                        self.pdf_start_page, self.default_pdf_pages_limit
                    )
                    event.input.value = str(self.pdf_end_page)
                    return

                value = int(event.value)
                if value < self.pdf_start_page:
                    value = self.pdf_start_page
                    event.input.value = str(self.pdf_start_page)
                elif self.total_pdf_pages > 0 and value > self.total_pdf_pages:
                    value = self.total_pdf_pages
                    event.input.value = str(self.total_pdf_pages)

                self.pdf_end_page = value

            except ValueError:
                self.pdf_end_page = max(
                    self.pdf_start_page, self.default_pdf_pages_limit
                )
                event.input.value = str(self.pdf_end_page)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-button":
            if not self.summary_in_progress:
                self._handle_send()
        elif event.button.id == "save-button":
            if not self.summary_in_progress:
                self._handle_save()
        elif event.button.id == "close-button":
            self.dismiss(None)

    def on_streaming_update(self, message: StreamingUpdate) -> None:
        """Handle streaming content updates."""
        self._streaming_content = message.content
        if self._streaming_widget:
            self._streaming_widget.update(self._streaming_content)
            # Scroll to end
            chat_container = self.query_one("#chat-history", VerticalScroll)
            chat_container.scroll_end(animate=False)
        else:
            if self.app:
                self.app._add_log("chat_stream_error", "No streaming widget found for content update")

    def on_streaming_complete(self, message: StreamingComplete) -> None:
        """Handle streaming completion."""
        # Estimate output tokens
        self._output_tokens = self._estimate_tokens(message.final_content)
        
        # Add token info to response
        final_content_with_tokens = f"{message.final_content}\n\n*(~{self._input_tokens} input tokens, ~{self._output_tokens} output tokens)*"
        
        # Update chat history with final content
        if self.chat_history and self.chat_history[-1]["role"] == "assistant":
            self.chat_history[-1]["content"] = final_content_with_tokens
        
        # Final widget update
        if self._streaming_widget:
            self._streaming_widget.update(final_content_with_tokens)
            chat_container = self.query_one("#chat-history", VerticalScroll)
            chat_container.scroll_end(animate=False)
        
        # Re-enable buttons
        self._enable_buttons()
        
        # Ensure we have some response
        if not message.final_content.strip():
            if self.chat_history and self.chat_history[-1]["role"] == "assistant":
                self.chat_history[-1]["content"] = "No response received from the AI model."
                if self.app:
                    self.app._add_log("chat_stream_warning", "Received empty response from LLM")
            self._update_display()

    def on_streaming_error(self, message: StreamingError) -> None:
        """Handle streaming errors."""
        if self.app:
            self.app._add_log("chat_stream_error", f"LLM streaming failed: {message.error_message}")
        
        # Replace the last message with error and re-enable input
        if self.chat_history:
            self.chat_history[-1] = {"role": "error", "content": message.error_message}
        self._update_display()
        self._enable_buttons()

    def _handle_send(self):
        """Handle sending a message (app version logic)."""
        user_input = self.query_one("#user-input", Input)
        user_message = user_input.value.strip()

        if not user_message:
            return

        # Add user message to history with PDF page range info if applicable
        user_content = user_message
        pdf_info_added = False

        # Check if any papers have PDF content that will be sent
        for paper in self.papers:
            fields = self._get_paper_fields(paper)
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    if not pdf_info_added:
                        start_page = max(1, self.pdf_start_page)
                        end_page = max(start_page, self.pdf_end_page)
                        if start_page == end_page:
                            user_content += f"\n\n*(PDF page {start_page} attached)*"
                        else:
                            user_content += (
                                f"\n\n*(PDF pages {start_page}-{end_page} attached)*"
                            )
                        pdf_info_added = True
                        break

        # Estimate input tokens for the full conversation context
        messages = self._build_conversation_messages(user_message)
        total_input_text = " ".join([msg["content"] for msg in messages])
        self._input_tokens = self._estimate_tokens(total_input_text)
        
        # Add token info to user content for display
        user_content_with_tokens = f"{user_content}\n\n*(~{self._input_tokens} input tokens)*"
        
        self.chat_history.append({"role": "user", "content": user_content_with_tokens})

        # Log the user message
        if self.app:
            user_preview = user_message[:100] + "..." if len(user_message) > 100 else user_message
            self.app._add_log("chat_user", f"User: {user_preview} ({len(user_message)} characters total)")

        # Clear input and disable UI during response
        user_input.value = ""
        self._disable_buttons()
        self._update_display()

        # Add empty assistant message that will be updated with streaming content
        self.chat_history.append({"role": "assistant", "content": ""})
        self._update_display()

        # Get reference to the last content widget for direct updates
        chat_container = self.query_one("#chat-history", VerticalScroll)
        self._streaming_widget = None
        # Find the last Markdown widget (the content of the assistant message we just added)
        for child in reversed(list(chat_container.children)):
            if isinstance(child, Markdown):
                self._streaming_widget = child
                break

        # Send request in background with streaming using message system
        dialog_ref = self  # Capture reference for thread
        
        def send_request():
            try:
                # Build messages
                messages = self._build_conversation_messages(user_message)

                if self.app:
                    self.app._add_log(
                        "chat_api_call", f"Sending to OpenAI {self.model_name}"
                    )

                # Get response with model-specific parameters using centralized utility
                params = get_model_parameters(self.model_name)
                params["messages"] = messages
                params["stream"] = True

                stream = self.openai_client.chat.completions.create(**params)

                # Stream response using message system for thread safety
                full_response = ""
                last_update_time = 0
                update_interval = 0.3  # Update every 300ms to reduce UI overhead
                chunk_count = 0

                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        full_response += chunk.choices[0].delta.content
                        chunk_count += 1

                        # Send streaming update message with reduced frequency
                        current_time = time.time()
                        if (current_time - last_update_time >= update_interval) or (chunk_count % 10 == 0):
                            self.app.call_from_thread(dialog_ref.on_streaming_update, dialog_ref.StreamingUpdate(full_response))
                            last_update_time = current_time

                # Send completion message
                self.app.call_from_thread(dialog_ref.on_streaming_complete, dialog_ref.StreamingComplete(full_response))

            except Exception as e:
                error_msg = f"Chat Error: {str(e)}"
                if self.app:
                    self.app._add_log("chat_error", f"OpenAI error: {str(e)}")
                    # Send error message
                    self.app.call_from_thread(dialog_ref.on_streaming_error, dialog_ref.StreamingError(error_msg))

        threading.Thread(target=send_request, daemon=True).start()

    def _build_conversation_messages(self, user_message: str) -> list:
        """Build messages for OpenAI API (app version logic)."""
        # Build paper context
        paper_context = self._build_paper_context()
        system_message = ChatPrompts.system_message(paper_context)

        messages = [{"role": "system", "content": system_message}]

        # Add conversation history (last 6 messages to stay within token limits)
        # Skip only the last entry (empty assistant placeholder for streaming)
        # Include up to the last 7 entries (6 previous + current user message)
        recent_history = (
            self.chat_history[-7:-1]
            if len(self.chat_history) > 7
            else self.chat_history[:-1]
        )
        for entry in recent_history:
            if (
                entry["role"] in ["user", "assistant"]
                and entry["content"].strip()
                and not entry.get("ui_only", False)
            ):
                messages.append({"role": entry["role"], "content": entry["content"]})

        return messages

    def _build_paper_context(self) -> str:
        """Build paper context for LLM (app version logic)."""
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

            # Extract specified page range from PDF if available
            pdf_content_added = False
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    try:
                        # Use the current dialog's page range settings
                        start_page = max(1, self.pdf_start_page)
                        end_page = max(start_page, self.pdf_end_page)
                        pdf_text = self._extract_page_range(
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

            # Only include notes/summary if we don't have PDF content (to avoid redundancy)
            if not pdf_content_added and fields["notes"]:
                paper_context += f"Notes: {fields['notes']}\n"

            context_parts.append(paper_context)

        return ChatPrompts.paper_context_header() + "\n".join(context_parts)

    def _extract_page_range(
        self, pdf_path: str, start_page: int = 1, end_page: int = 10
    ) -> str:
        """Extract text from a specific page range of a PDF."""
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                text_parts = []
                total_pages = len(pdf_reader.pages)

                # Ensure valid page range
                # If requested range exceeds this PDF's total pages in any way,
                # send the entire document for this paper.
                if end_page > total_pages or start_page > total_pages:
                    start_idx = 0
                    end_idx = total_pages
                else:
                    start_idx = max(0, start_page - 1)  # Convert to 0-based index
                    end_idx = min(
                        total_pages, end_page
                    )  # Convert to 0-based, inclusive

                for page_num in range(start_idx, end_idx):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text.strip():
                        # Clean text to remove surrogates and other problematic characters
                        cleaned_text = self._clean_pdf_text(page_text.strip())
                        if cleaned_text:
                            text_parts.append(f"Page {page_num + 1}:\n{cleaned_text}")

                return "\n\n".join(text_parts)
        except Exception as e:
            if self.app:
                self.app._add_log(
                    "pdf_extract_error", f"Failed to extract PDF text: {e}"
                )
            return ""

    def _calculate_total_pdf_pages(self) -> int:
        """Calculate the maximum number of pages across all PDFs."""
        max_pages = 0
        for paper in self.papers:
            fields = self._get_paper_fields(paper)
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    try:
                        with open(absolute_path, "rb") as file:
                            pdf_reader = PyPDF2.PdfReader(file)
                            pages = len(pdf_reader.pages)
                            max_pages = max(max_pages, pages)
                    except Exception as e:
                        if self.app:
                            self.app._add_log(
                                "pdf_page_count_error",
                                f"Failed to count pages for '{fields['title']}': {e}",
                            )
        return max_pages

    def _has_available_pdfs(self) -> bool:
        """Check if any papers have available PDF files."""
        for paper in self.papers:
            fields = self._get_paper_fields(paper)
            if fields["pdf_path"]:
                absolute_path = self.pdf_manager.get_absolute_path(fields["pdf_path"])
                if os.path.exists(absolute_path):
                    return True
        return False

    def _update_pdf_controls_state(self):
        """Update the state of PDF page range controls based on available PDFs."""
        has_pdfs = self._has_available_pdfs()

        if has_pdfs:
            self.total_pdf_pages = self._calculate_total_pdf_pages()
        else:
            self.total_pdf_pages = 0

        # Update input controls
        try:
            start_input = self.query_one("#pdf-start-input", Input)
            end_input = self.query_one("#pdf-end-input", Input)

            start_input.disabled = not has_pdfs
            end_input.disabled = not has_pdfs

            if not has_pdfs:
                start_input.placeholder = "No PDF"
                end_input.placeholder = "No PDF"
                start_input.value = ""
                end_input.value = ""
            else:
                start_input.placeholder = "1"
                end_input.placeholder = str(self.total_pdf_pages)

                # Validate current values
                if self.pdf_start_page > self.total_pdf_pages:
                    self.pdf_start_page = self.total_pdf_pages
                if self.pdf_end_page > self.total_pdf_pages:
                    self.pdf_end_page = self.total_pdf_pages
                if self.pdf_end_page < self.pdf_start_page:
                    self.pdf_end_page = self.pdf_start_page

                start_input.value = str(self.pdf_start_page)
                end_input.value = str(self.pdf_end_page)

        except Exception:
            # Controls might not be mounted yet
            pass

    def _generate_chat_filename(self) -> str:
        """Generate a chat filename using PDF naming convention but with .md extension."""

        # Use the first paper to generate filename
        first_paper = self.papers[0]

        # Reuse the same paper field extraction logic as _build_paper_context
        fields = self._get_paper_fields(first_paper)

        # Parse authors string into list (PDFManager expects list of strings)
        authors_list = []
        if fields["authors"] and fields["authors"] != "Unknown Authors":
            authors_list = [name.strip() for name in fields["authors"].split(",")]

        # Create paper data dict for PDF filename generation
        paper_data = {
            "title": fields["title"],
            "authors": authors_list,
            "year": fields["year"] if fields["year"] != "Unknown Year" else None,
        }

        # Use PDFManager's filename generation logic
        pdf_filename = self.pdf_manager._generate_pdf_filename(paper_data, "")

        # Remove the hash part and add timestamp
        base_filename = pdf_filename.rsplit("_", 1)[0]  # Remove hash
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chat_filename = f"{base_filename}_{timestamp}.md"

        return chat_filename

    def _handle_save(self):
        """Handle saving the chat to a file with PDF naming convention and file opening."""
        if not self.chat_history:
            self._add_system_message("No chat history to save.")
            return

        try:
            # Get data directory
            data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
            if data_dir_env:
                data_dir = Path(data_dir_env).expanduser().resolve()
            else:
                data_dir = Path.home() / ".papercli"

            # Create chats directory
            chats_dir = data_dir / "chats"
            chats_dir.mkdir(exist_ok=True, parents=True)

            # Generate filename using PDF naming convention
            filename = self._generate_chat_filename()
            filepath = chats_dir / filename

            # Handle filename conflicts
            counter = 1
            base_name = filename[:-3]  # Remove .md extension
            final_filename = filename
            final_filepath = filepath

            while final_filepath.exists():
                final_filename = f"{base_name}_{counter:02d}.md"
                final_filepath = chats_dir / final_filename
                counter += 1

            # Write chat to file
            content = self._format_chat_for_file()
            with open(final_filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # Open file location in Finder/File Explorer
            success, error_msg = self.system_service.open_file_location(
                str(final_filepath)
            )
            if not success:
                if self.app:
                    self.app._add_log(
                        "chat_save_open_error",
                        f"Failed to open file location: {error_msg}",
                    )

            self._add_system_message(f"💾 Chat saved to {final_filepath}")

        except Exception as e:
            self._add_system_message(f"Error saving chat: {e}")

    def _format_chat_for_file(self) -> str:
        """Format chat for saving to file (app version logic)."""
        lines = []
        lines.append("# Chat Session")
        lines.append(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Model**: {self.model_name} (current at session end)")
        lines.append("")

        # Add paper info
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

        # Add chat history (including system messages with model info)
        lines.append("## Chat History")
        lines.append("")

        for entry in self.chat_history:
            # Don't skip system messages - include them with model info
            pass

            role = entry["role"]
            content = entry["content"]

            if role == "user":
                lines.append(f"**You**: {content}")
            elif role == "assistant":
                lines.append(f"**Assistant ({self.model_name})**: {content}")
            elif role == "system":
                lines.append(f"**System ({self.model_name})**: {content}")

            lines.append("")

        return "\n".join(lines)
