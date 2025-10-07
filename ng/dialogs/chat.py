import os
from datetime import datetime
from typing import Any, Callable, Dict, List

import PyPDF2
from pluralizer import Pluralizer
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Markdown, Static

from ng.services import (
    BackgroundOperationService,
    ChatService,
    LLMSummaryService,
    PaperService,
    PDFManager,
    SystemService,
    dialog_utils,
    llm_utils,
    prompts,
    theme,
)
from ng.services.formatting import format_title_by_words

_pluralizer = Pluralizer()


class ChatDialog(ModalScreen):
    """A modal dialog for chat interactions with OpenAI."""

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
    #controls-left, #controls-right {
        height: auto;
        width: 50%;
    }
    #controls-left {
        align: left middle;
    }
    #controls-right {
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
    .compact-model-input:focus, .compact-input:focus {
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
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.summary_in_progress = False
        self.default_pdf_pages_limit = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
        self.pdf_start_page = 1
        self.pdf_end_page = self.default_pdf_pages_limit
        self.total_pdf_pages = 0

        # Services
        self.pdf_manager = PDFManager(self.app)
        self.paper_service = PaperService(app=self.app)
        self.background_service = BackgroundOperationService(app=None)
        self.llm_service = LLMSummaryService(
            paper_service=self.paper_service,
            background_service=self.background_service,
            app=self.app,
        )
        self.system_service = SystemService(self.pdf_manager, app=self.app)
        self.chat_service = ChatService(app=self.app)

        # Thread-safe state
        self._streaming_content = ""
        self._streaming_widget = None
        self._thinking_content = ""
        self._input_tokens = 0
        self._output_tokens = 0
        self._loading_animation_active = False
        self._loading_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._loading_frame_index = 0

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
        # Set app reference for background service
        self.background_service.app = self.app

        user_input = self.query_one("#user-input", Input)
        # Ensure Input is properly configured for input
        user_input.can_focus = True
        user_input.focus()

        # Calculate total PDF pages and update input states
        self._update_pdf_controls_state()

        if not self.papers:
            self._add_system_message("No papers selected for chat.")
            return

        if not self.chat_service.openai_client:
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
            fields = dialog_utils.get_paper_fields(paper)
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
                                    f"Updated in-memory paper: {format_title_by_words(paper.title or '')}",
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

        self._build_initial_chat_content()

    def _format_paper_info(self, paper, index):
        """Format paper information for display (app version logic)."""
        fields = dialog_utils.get_paper_fields(paper)

        paper_info = (
            f"**Paper {index}: {fields['title']}**\n\n"
            f"Authors: {fields['authors']}\n\n"
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
            initial_content = prompts.chat_initial_single_paper(paper_details[0])
        else:
            initial_content = prompts.chat_initial_multiple_papers(
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

                # Get theme-appropriate colors using theme service
                if role == "user":
                    role_color = theme.get_markup_color("accent", app=self.app)
                    role_text = "⏵ User"
                elif role == "assistant":
                    role_color = theme.get_markup_color("success", app=self.app)
                    role_text = f"⏵ Model ({self.model_name})"
                elif role == "system":
                    role_color = theme.get_markup_color("warning", app=self.app)
                    role_text = "⏵ System"
                elif role == "loading":
                    role_color = theme.get_markup_color("info", app=self.app)
                    role_text = content
                    # For loading messages, just show the text
                    loading_widget = Static(role_text, classes="chat-role-header")
                    loading_widget.styles.color = role_color
                    loading_widget.can_focus = True
                    chat_container.mount(loading_widget)
                    continue
                elif role == "error":
                    role_color = theme.get_markup_color("error", app=self.app)
                    role_text = f"Error: {content}"
                    # For error messages, just show the text
                    error_widget = Static(role_text, classes="chat-role-header")
                    error_widget.styles.color = role_color
                    error_widget.can_focus = True
                    chat_container.mount(error_widget)
                    continue
                elif role == "thinking":
                    role_color = theme.get_markup_color("info", app=self.app)
                    role_text = "⏵ Thinking"
                else:
                    # Unknown role, use default
                    role_color = theme.get_markup_color("text", app=self.app)
                    role_text = f"⏵ {role.capitalize()}"

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

    def _on_streaming_update(self, content: str, thinking: str = "") -> None:
        """Handle streaming content updates."""
        # Stop loading animation on first content update and ensure widget ref
        if self._loading_animation_active:
            self._loading_animation_active = False
        if not self._streaming_widget:
            try:
                chat_container = self.query_one("#chat-history", VerticalScroll)
                for child in reversed(list(chat_container.children)):
                    if isinstance(child, Markdown):
                        self._streaming_widget = child
                        break
            except Exception:
                self._streaming_widget = None

        self._streaming_content = content

        # Build display content. While streaming, do NOT insert the
        # separator between thinking and content yet; only add it on completion.
        display_content = content
        if thinking:
            display_content = f"**◆ Thinking**\n\n{thinking}\n\n{content}"

        if self._streaming_widget:
            self._streaming_widget.update(display_content)
            # Scroll to end
            chat_container = self.query_one("#chat-history", VerticalScroll)
            chat_container.scroll_end(animate=False)
        else:
            self.app._add_log(
                "chat_stream_error", "No streaming widget found for content update"
            )

    def _on_streaming_complete(
        self, final_content: str, final_thinking: str = ""
    ) -> None:
        """Handle streaming completion."""
        # Stop loading animation if active and ensure widget exists
        if self._loading_animation_active:
            self._loading_animation_active = False
        if not self._streaming_widget:
            try:
                chat_container = self.query_one("#chat-history", VerticalScroll)
                for child in reversed(list(chat_container.children)):
                    if isinstance(child, Markdown):
                        self._streaming_widget = child
                        break
            except Exception:
                self._streaming_widget = None
        # Estimate output tokens
        self._output_tokens = self.chat_service.estimate_tokens(
            final_content, self.model_name
        )

        # Build display content with thinking prepended if available
        display_content = final_content
        if final_thinking:
            display_content = (
                f"**◆ Thinking**\n\n{final_thinking}\n\n---\n\n{final_content}"
            )

        # Add token info to response
        final_content_with_tokens = f"{display_content}\n\n*(~{self._input_tokens} input tokens, ~{self._output_tokens} output tokens)*"

        # Update chat history with final content
        if self.chat_history and self.chat_history[-1]["role"] == "assistant":
            self.chat_history[-1]["content"] = final_content_with_tokens
            # Store thinking separately for potential export
            if final_thinking:
                self.chat_history[-1]["thinking"] = final_thinking

        # Final widget update (fallback to full refresh if needed)
        if self._streaming_widget:
            self._streaming_widget.update(final_content_with_tokens)
            chat_container = self.query_one("#chat-history", VerticalScroll)
            chat_container.scroll_end(animate=False)
        else:
            self._update_display()

        # Re-enable buttons
        self._enable_buttons()

        # Log successful completion with token usage
        response_preview = (
            final_content[:100] + "..." if len(final_content) > 100 else final_content
        )
        self.app._add_log(
            "chat_response",
            f"LLM response completed: {response_preview} (~{self._input_tokens} input, ~{self._output_tokens} output tokens)",
        )

        # Ensure we have some response
        if not final_content.strip():
            if self.chat_history and self.chat_history[-1]["role"] == "assistant":
                self.chat_history[-1][
                    "content"
                ] = "No response received from the AI model."
                self.app._add_log(
                    "chat_stream_warning", "Received empty response from LLM"
                )
            self._update_display()

    def _on_streaming_error(self, error_message: str) -> None:
        """Handle streaming errors."""
        # Stop loading animation
        self._loading_animation_active = False

        self.app._add_log("chat_stream_error", f"LLM streaming failed: {error_message}")

        # Replace the last message with error and re-enable input
        if self.chat_history:
            self.chat_history[-1] = {"role": "error", "content": error_message}
        self._update_display()
        self._enable_buttons()

    def _update_loading_animation(self) -> None:
        """Update the loading animation frame inside assistant message."""
        if not self._loading_animation_active:
            return

        # Update frame index
        self._loading_frame_index = (self._loading_frame_index + 1) % len(
            self._loading_frames
        )
        spinner = self._loading_frames[self._loading_frame_index]

        # Update the last assistant message's content
        if self.chat_history and self.chat_history[-1]["role"] == "assistant":
            self.chat_history[-1]["content"] = f"{spinner} Generating response..."

            # Update the assistant Markdown widget directly if available
            try:
                if self._streaming_widget:
                    self._streaming_widget.update(f"{spinner} Generating response...")
                else:
                    chat_container = self.query_one("#chat-history", VerticalScroll)
                    for child in reversed(list(chat_container.children)):
                        if isinstance(child, Markdown):
                            child.update(f"{spinner} Generating response...")
                            break
            except Exception:
                pass

        # Schedule next update if still active
        if self._loading_animation_active:
            self.set_timer(0.1, self._update_loading_animation)

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
            fields = dialog_utils.get_paper_fields(paper)
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
        messages = self.chat_service.build_conversation_messages(
            user_message,
            self.chat_history,
            self.papers,
            self.pdf_start_page,
            self.pdf_end_page,
        )
        total_input_text = " ".join([msg["content"] for msg in messages])
        self._input_tokens = self.chat_service.estimate_tokens(
            total_input_text, self.model_name
        )

        self.chat_history.append({"role": "user", "content": user_content})

        # Log the user message
        user_preview = (
            user_message[:100] + "..." if len(user_message) > 100 else user_message
        )
        self.app._add_log(
            "chat_user",
            f"User: {user_preview} ({len(user_message)} characters total)",
        )

        # Clear input and disable UI during response
        user_input.value = ""
        self._disable_buttons()
        self._update_display()

        # Check if we should show thinking
        show_thinking = (
            llm_utils.is_reasoning_model(self.model_name)
            and os.getenv("OPENAI_SHOW_THINKING", "false").lower() == "true"
        )
        self._thinking_content = ""

        # Add assistant placeholder that will animate until first content arrives
        self._loading_animation_active = True
        self._loading_frame_index = 0
        initial_spinner = self._loading_frames[self._loading_frame_index]
        self.chat_history.append(
            {
                "role": "assistant",
                "content": f"{initial_spinner} Generating response...",
            }
        )
        self._update_display()

        # Get reference to the assistant Markdown widget for updates
        chat_container = self.query_one("#chat-history", VerticalScroll)
        self._streaming_widget = None
        for child in reversed(list(chat_container.children)):
            if isinstance(child, Markdown):
                self._streaming_widget = child
                break

        # Start spinner timer
        self.set_timer(0.1, self._update_loading_animation)

        # Stream chat response using the service
        self.chat_service.stream_chat_response(
            model_name=self.model_name,
            messages=messages,
            show_thinking=show_thinking,
            on_content_update=self._on_streaming_update,
            on_complete=self._on_streaming_complete,
            on_error=self._on_streaming_error,
        )

    def _calculate_total_pdf_pages(self) -> int:
        """Calculate the maximum number of pages across all PDFs."""
        max_pages = 0
        for paper in self.papers:
            fields = dialog_utils.get_paper_fields(paper)
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
            fields = dialog_utils.get_paper_fields(paper)
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

    def _handle_save(self):
        """Handle saving the chat to a file with PDF naming convention and file opening."""
        if not self.chat_history:
            self._add_system_message("No chat history to save.")
            return

        try:
            # Get data directory and create chats subdirectory
            data_dir = dialog_utils.get_data_directory()
            chats_dir = data_dir / "chats"

            # Generate filename and create safe filepath
            filename = dialog_utils.generate_filename_from_paper(self.papers[0], ".md")
            final_filepath = dialog_utils.create_safe_filename(filename, chats_dir)

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
                fields = dialog_utils.get_paper_fields(paper)
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
            elif role == "thinking":
                lines.append(f"**Thinking ({self.model_name})**: {content}")

            lines.append("")

        return "\n".join(lines)
