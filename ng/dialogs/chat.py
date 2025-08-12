import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import PyPDF2
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, RichLog, Static, TextArea

from ng.services import (
    BackgroundOperationService,
    LLMSummaryService,
    PaperService,
    PDFManager,
    ThemeService,
)


class ChatDialog(ModalScreen):
    """A modal dialog for chat interactions with OpenAI."""

    DEFAULT_CSS = """
    ChatDialog {
        width: 100%;
        height: 100%;
        max-width: 100%;
        overflow-x: hidden;
    }
    
    #chat-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
        max-width: 100%;
    }
    
    #chat-container {
        width: 100%;
        height: 100%;
        max-width: 100%;
        border: solid $primary;
        background: $surface;
        overflow-x: hidden;
    }
    
    #chat-history {
        height: 1fr;
        width: 100%;
        max-width: 100%;
        border: solid $accent;
        margin: 0;
        padding: 1;
        overflow-x: hidden;
    }
    
    #input-area {
        height: auto;
        width: 100%;
        max-width: 100%;
        margin: 0;
        padding: 0;
    }
    
    #user-input {
        height: 3;
        width: 100%;
        max-width: 100%;
        margin: 0;
        border: solid $accent;
        padding: 1;
    }
    
    #button-bar {
        height: auto;
        width: 100%;
        max-width: 100%;
        align: center middle;
        margin: 0;
        padding: 1;
    }
    #button-bar Button {
        height: 3;
        content-align: center middle;
        text-align: center;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+enter", "send_message", "Send"),
        ("enter", "send_message", "Send"),
        ("ctrl+s", "save_chat", "Save Chat"),
        ("ctrl+k", "cut_line", "Cut Line"),
        ("ctrl+j", "new_line", "New Line"),
        ("shift+enter", "new_line", "New Line"),
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
        self.openai_client = None
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.pdf_manager = PDFManager()
        self.ui_initialized = False
        self.summary_in_progress = False

        # Initialize services for summary generation
        self.paper_service = PaperService()
        self.background_service = BackgroundOperationService(app=None)
        # Set the app reference for the background service
        self.background_service.app = self.app
        self.llm_service = LLMSummaryService(
            paper_service=self.paper_service,
            background_service=self.background_service,
            app=None,
        )

        # Initialize OpenAI client if API key is available
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        with Container(id="chat-container"):
            yield Static(
                f"Chat with Papers ({len(self.papers)} selected)", id="chat-title"
            )
            yield RichLog(id="chat-history", markup=True, wrap=True, highlight=True)
            with Container(id="input-area"):
                yield TextArea(id="user-input")
            with Horizontal(id="button-bar"):
                yield Button("Send", id="send-button", variant="primary")
                yield Button("Save Chat", id="save-button", variant="default")
                yield Button("Close", id="close-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the chat with paper information."""
        # Set the app reference for services now that we have it
        self.background_service.app = self.app
        self.llm_service.app = self.app

        chat_log = self.query_one("#chat-history", RichLog)

        if not self.papers:
            chat_log.write("No papers selected for chat.", style="dim")
            return

        if not self.openai_client:
            chat_log.write(
                self._theme_markup("OpenAI API key not configured. Set OPENAI_API_KEY environment variable.", "error")
            )
            return

        # Build initial content similar to app version
        self._initialize_chat_display()
        self.ui_initialized = True

    def action_send_message(self) -> None:
        """Send the user message."""
        self._send_message()

    def action_save_chat(self) -> None:
        """Save the chat history."""
        self._save_chat()

    def action_cut_line(self) -> None:
        """Cut current line or remaining text after cursor."""
        user_input = self.query_one("#user-input", TextArea)
        if user_input.text:
            cursor_position = user_input.cursor_position
            lines = user_input.text.split("\n")
            current_line_start = 0

            current_line_idx = 0

            # Find which line the cursor is on
            for i, line in enumerate(lines):
                line_end = current_line_start + len(line)
                if cursor_position <= line_end:
                    current_line_idx = i
                    break
                current_line_start = line_end + 1  # +1 for newline

            # Cut from cursor to end of current line, or whole line if at start
            if cursor_position == current_line_start:
                # At start of line, cut whole line
                lines.pop(current_line_idx)
                user_input.text = "\n".join(lines)
                user_input.cursor_position = current_line_start
            else:
                # Cut from cursor to end of line
                current_line = lines[current_line_idx]
                char_pos_in_line = cursor_position - current_line_start
                lines[current_line_idx] = current_line[:char_pos_in_line]
                user_input.text = "\n".join(lines)
                user_input.cursor_position = cursor_position

    def action_new_line(self) -> None:
        """Insert a new line at cursor position."""
        user_input = self.query_one("#user-input", TextArea)
        cursor_pos = user_input.cursor_position
        current_text = user_input.text
        new_text = current_text[:cursor_pos] + "\n" + current_text[cursor_pos:]
        user_input.text = new_text
        user_input.cursor_position = cursor_pos + 1

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-button":
            self._send_message()
        elif event.button.id == "save-button":
            self._save_chat()
        elif event.button.id == "close-button":
            self.dismiss(None)

    def _send_message(self) -> None:
        """Send user message to OpenAI."""
        user_input = self.query_one("#user-input", TextArea)
        chat_log = self.query_one("#chat-history", RichLog)

        message = user_input.text.strip()
        if not message:
            return

        if not self.openai_client:
            chat_log.write(self._theme_markup("OpenAI API key not configured.", "error"))
            return

        # Display user message
        chat_log.write(f"[bold green]You:[/bold green] {message}")
        user_input.text = ""

        # Add to chat history
        self.chat_history.append({"role": "user", "content": message})

        # Add loading indicator
        chat_log.write(self._theme_markup("🤖 Thinking...", "dim"))

        # Debug: Show we're starting the process
        chat_log.write(self._theme_markup("🔧 Preparing message...", "dim"))

        # Send request in background thread
        def send_request():
            try:
                # Prepare messages for API call
                messages = self._build_conversation_messages(message)

                # Debug: Check if we have messages
                if not messages:
                    raise Exception("No messages prepared for OpenAI API")

                # Debug: Show we're making the API call
                self.app.call_from_thread(
                    lambda: chat_log.write(self._theme_markup("📡 Sending request to OpenAI...", "dim"))
                )

                # Get streaming response from OpenAI
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
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        chunk_text = chunk.choices[0].delta.content
                        full_response += chunk_text

                assistant_message = full_response.strip()

                # Debug: Check if we got a response
                if not assistant_message:
                    assistant_message = "No response received from the AI model."

                # Update UI in main thread
                self.app.call_from_thread(self._display_response, assistant_message)

            except Exception as e:
                error_msg = f"Chat Error: {str(e)}"
                self.app.call_from_thread(self._display_error, error_msg)

        # Start background thread
        thread = threading.Thread(target=send_request, daemon=True)
        thread.start()

    def _display_response(self, response: str) -> None:
        """Display AI response in chat log."""
        chat_log = self.query_one("#chat-history", RichLog)

        # Store in history first
        self.chat_history.append({"role": "assistant", "content": response})

        # Remove loading indicator by clearing and re-adding history
        chat_log.clear()

        # Add initial content if UI was initialized
        if self.ui_initialized:
            self._initialize_chat_display_content()

        # Re-add all chat history properly formatted
        for entry in self.chat_history:
            if entry["role"] == "user":
                chat_log.write(f"[bold green]You:[/bold green] {entry['content']}")
            elif entry["role"] == "assistant":
                chat_log.write("[bold blue]🤖 Assistant:[/bold blue]")
                self._render_markdown(entry["content"])

    def _display_error(self, error: str) -> None:
        """Display error message."""
        chat_log = self.query_one("#chat-history", RichLog)
        chat_log.write(self._theme_markup(error, "error"))

    def _build_paper_context(self) -> str:
        """Build context string about papers."""
        context_parts = []
        for i, paper in enumerate(self.papers, 1):
            title = getattr(paper, "title", "Unknown Title")
            authors = getattr(paper, "author_names", "Unknown Authors")
            year = getattr(paper, "year", "Unknown Year")
            abstract = getattr(paper, "abstract", "")

            paper_info = f"Paper {i}: {title}\nAuthors: {authors}\nYear: {year}"
            if abstract:
                paper_info += f"\nAbstract: {abstract}"
            context_parts.append(paper_info)

        return "\n\n".join(context_parts)

    def _save_chat(self) -> None:
        """Save chat history to file with enhanced formatting."""
        if not self.chat_history:
            chat_log = self.query_one("#chat-history", RichLog)
            chat_log.write(self._theme_markup("No chat history to save.", "warning"))
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

            # Generate filename with timestamp and paper info
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            paper_titles = []
            for paper in self.papers:
                title = getattr(paper, "title", "Unknown")
                clean_title = "".join(
                    c for c in title if c.isalnum() or c in (" ", "-", "_")
                ).rstrip()
                paper_titles.append(clean_title[:30])  # Limit length

            if paper_titles:
                filename = f"chat_{timestamp}_{'-'.join(paper_titles[:2])}.md"
            else:
                filename = f"chat_{timestamp}.md"

            filepath = chats_dir / filename

            # Write enhanced chat format to file
            content = self._format_chat_for_file()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            chat_log = self.query_one("#chat-history", RichLog)
            chat_log.write(self._theme_markup(f"💾 Chat saved to {filepath.name}", "success"))

        except Exception as e:
            chat_log = self.query_one("#chat-history", RichLog)
            chat_log.write(self._theme_markup(f"Error saving chat: {e}", "error"))

    def action_cancel(self) -> None:
        self.dismiss(None)
    
    def _theme_markup(self, text: str, color_name: str) -> str:
        """Generate theme-aware markup for Rich text."""
        color = ThemeService.get_markup_color(color_name, app=self.app)
        return f"[{color}]{text}[/{color}]"

    def _render_markdown(self, text: str) -> None:
        """Render markdown directly to RichLog using Rich's markdown renderer."""
        chat_log = self.query_one("#chat-history", RichLog)

        # Use Rich's markdown renderer
        markdown = RichMarkdown(text)

        # Create a console to render the markdown
        from io import StringIO

        string_io = StringIO()
        console = Console(file=string_io, width=80, legacy_windows=False)
        console.print(markdown)

        # Get the rendered output and write to RichLog
        rendered_text = string_io.getvalue()
        chat_log.write(rendered_text)

    def _initialize_chat_display(self):
        """Initialize the chat display with paper information."""
        # Initialize the content display
        self._initialize_chat_display_content()

        # Check for papers that need summaries and start generation
        papers_need_summaries = []
        for paper in self.papers:
            notes = getattr(paper, "notes", "")
            pdf_path = getattr(paper, "pdf_path", "")
            if not (notes and notes.strip()) and pdf_path and pdf_path.strip():
                try:
                    pdf_absolute_path = self.pdf_manager.get_absolute_path(pdf_path)
                    if os.path.exists(pdf_absolute_path):
                        papers_need_summaries.append(paper)
                except Exception:
                    pass

        # Generate summaries for papers that need them
        if papers_need_summaries and self.openai_client:
            self._generate_summaries_for_papers(papers_need_summaries)

    def _format_single_paper_info(self, paper):
        """Format information for a single paper."""
        title = getattr(paper, "title", "Unknown Title")
        authors = getattr(paper, "author_names", "Unknown Authors")
        year = getattr(paper, "year", "Unknown Year")
        venue = getattr(paper, "venue_full", "Unknown Venue")
        abstract = getattr(paper, "abstract", "")
        notes = getattr(paper, "notes", "")
        pdf_path = getattr(paper, "pdf_path", "")

        info = f"{self._theme_markup(title, 'header')}\n\n"
        info += f"[bold]Authors:[/bold] {authors}\n"
        info += f"[bold]Venue:[/bold] {venue} ({year})\n"

        if abstract:
            info += f"\n[bold]Abstract:[/bold] {abstract}\n"

        # Show summary if available
        if notes and notes.strip():
            info += f"\n[bold]Summary:[/bold] {notes}\n"
        elif pdf_path and pdf_path.strip():
            # Show summary generation status if needed
            try:
                pdf_absolute_path = self.pdf_manager.get_absolute_path(pdf_path)
                if os.path.exists(pdf_absolute_path):
                    bg_msg = self._theme_markup('(Being generated in background...)', 'warning')
                    info += f"\n[bold]Summary:[/bold] {bg_msg}"
                else:
                    info += f"\n[bold]Summary:[/bold] {self._theme_markup('PDF not found', 'dim')}"
            except Exception:
                info += f"\n[bold]Summary:[/bold] {self._theme_markup('PDF error', 'dim')}"
        else:
            info += f"\n[bold]Summary:[/bold] {self._theme_markup('No notes available', 'dim')}"

        return info

    def _format_paper_info(self, paper, index):
        """Format paper information for display in multi-paper view."""
        title = getattr(paper, "title", "Unknown Title")
        authors = getattr(paper, "author_names", "Unknown Authors")
        year = getattr(paper, "year", "Unknown Year")
        venue = getattr(paper, "venue_full", "Unknown Venue")
        abstract = getattr(paper, "abstract", "")
        notes = getattr(paper, "notes", "")
        pdf_path = getattr(paper, "pdf_path", "")

        info = f"[bold]Paper {index}: {title}[/bold]\n\n"
        info += f"[bold]Authors:[/bold] {authors}\n"
        info += f"[bold]Venue:[/bold] {venue} ({year})\n"

        if abstract:
            info += f"\n[bold]Abstract:[/bold] {abstract}\n"

        # Show summary if available
        if notes and notes.strip():
            info += f"\n[bold]Summary:[/bold] {notes}\n"
        elif pdf_path and pdf_path.strip():
            # Show summary generation status if needed
            try:
                pdf_absolute_path = self.pdf_manager.get_absolute_path(pdf_path)
                if os.path.exists(pdf_absolute_path):
                    bg_msg = self._theme_markup('(Being generated in background...)', 'warning')
                    info += f"\n[bold]Summary:[/bold] {bg_msg}"
                else:
                    info += f"\n[bold]Summary:[/bold] {self._theme_markup('PDF not found', 'dim')}"
            except Exception:
                info += f"\n[bold]Summary:[/bold] {self._theme_markup('PDF error', 'dim')}"
        else:
            info += f"\n[bold]Summary:[/bold] {self._theme_markup('No notes available', 'dim')}"

        return info

    def _generate_summaries_for_papers(self, papers):
        """Generate summaries for papers that don't have notes using LLMSummaryService."""
        if self.summary_in_progress:
            return

        self.summary_in_progress = True

        # Disable send button
        send_button = self.query_one("#send-button", Button)
        send_button.disabled = True

        # Show notification
        self.notify("LLM summary generation started...", severity="information")

        def on_summaries_complete(tracking):
            """Called when all summaries are complete."""
            # Re-enable send button
            send_button = self.query_one("#send-button", Button)
            send_button.disabled = False
            self.summary_in_progress = False

            # Refresh the paper objects from database to get updated summaries
            self._refresh_paper_objects()

            # Refresh the chat display with updated summaries
            self._refresh_chat_display()

        # Use the LLMSummaryService to generate summaries
        tracking = self.llm_service.generate_summaries(
            papers=papers,
            on_all_complete=on_summaries_complete,
            operation_prefix="chat_summary",
        )

        if tracking is None:
            # No papers with PDFs, re-enable button
            send_button.disabled = False
            self.summary_in_progress = False

    def _refresh_paper_objects(self):
        """Refresh paper objects from database to get updated data."""
        try:
            # Refresh each paper from the database
            for i, paper in enumerate(self.papers):
                updated_paper = self.paper_service.get_paper_by_id(paper.id)
                if updated_paper:
                    self.papers[i] = updated_paper
        except Exception as e:
            # Could log error here if needed
            pass

    def _refresh_chat_display(self):
        """Refresh the chat display with updated paper information."""
        chat_log = self.query_one("#chat-history", RichLog)

        # Clear existing display
        chat_log.clear()

        # Re-initialize the display with updated data
        self._initialize_chat_display_content()

    def _initialize_chat_display_content(self):
        """Initialize just the content part of the chat display."""
        chat_log = self.query_one("#chat-history", RichLog)

        # Display paper information following original app format
        if len(self.papers) == 1:
            paper_info = self._format_single_paper_info(self.papers[0])
            chat_log.write(paper_info)
        else:
            chat_log.write(
                f"[bold blue]📚 Selected Papers ({len(self.papers)}):[/bold blue]\n"
            )
            for i, paper in enumerate(self.papers, 1):
                paper_info = self._format_paper_info(paper, i)
                chat_log.write(paper_info)
                if i < len(self.papers):
                    chat_log.write("\n---\n")

        chat_log.write(
            "\n[bold green]💬 Ready to chat! Ask questions about the selected papers.[/bold green]"
        )

    def _update_paper_summary_display(self, paper, summary):
        """Update the chat display with generated summary."""
        chat_log = self.query_one("#chat-history", RichLog)
        title_short = getattr(paper, 'title', 'Unknown')[:50]
        success_msg = self._theme_markup(f"✓ Generated summary for: {title_short}...", "success")
        chat_log.write(success_msg)
        chat_log.write(
            f"   {self._theme_markup('Summary:', 'dim')} {summary[:200]}{'...' if len(summary) > 200 else ''}"
        )

    def _extract_first_pages(self, pdf_path: str, max_pages: int = 5) -> str:
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
                        text_parts.append(page_text.strip())

                return "\n\n".join(text_parts)
        except Exception:
            return ""

    def _build_conversation_messages(self, user_message: str) -> list:
        """Build messages array for OpenAI API call."""
        messages = []

        # Add system message with paper context
        paper_context = self._build_enhanced_paper_context()
        system_message = f"""You are a helpful AI assistant discussing research papers. Here are the papers we're discussing:

{paper_context}

Please provide helpful, accurate, and detailed responses about these papers. You can reference specific papers by number, discuss their methodologies, findings, and implications. If asked about comparisons, highlight similarities and differences between the papers."""

        messages.append({"role": "system", "content": system_message})

        # Add recent conversation history (last 6 messages to stay within token limits)
        recent_history = (
            self.chat_history[-6:] if len(self.chat_history) > 6 else self.chat_history
        )
        for entry in recent_history:
            if entry["role"] in ["user", "assistant"] and entry["content"].strip():
                messages.append({"role": entry["role"], "content": entry["content"]})

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _build_enhanced_paper_context(self) -> str:
        """Build comprehensive context string about papers for LLM."""
        if not self.papers:
            return "No papers are currently selected for discussion."

        context_parts = []
        for i, paper in enumerate(self.papers, 1):
            title = getattr(paper, "title", "Unknown Title")
            authors = getattr(paper, "author_names", "Unknown Authors")
            year = getattr(paper, "year", "Unknown Year")
            venue = getattr(paper, "venue_full", "Unknown Venue")
            abstract = getattr(paper, "abstract", "")
            notes = getattr(paper, "notes", "")
            pdf_path = getattr(paper, "pdf_path", "")

            paper_context = f"Paper {i}: {title}\n"
            paper_context += f"Authors: {authors}\n"
            paper_context += f"Venue: {venue} ({year})\n"

            if abstract:
                paper_context += f"Abstract: {abstract}\n"

            # Try to extract PDF content if available
            pdf_content_added = False
            if pdf_path:
                absolute_path = self.pdf_manager.get_absolute_path(pdf_path)
                if os.path.exists(absolute_path):
                    try:
                        max_pages = int(
                            os.getenv("PAPERCLI_PDF_PAGES", "5")
                        )  # Fewer pages for chat
                        pdf_text = self._extract_first_pages(
                            absolute_path, max_pages=max_pages
                        )
                        if pdf_text:
                            paper_context += f"First {max_pages} pages:\n{pdf_text}\n"
                            pdf_content_added = True
                    except Exception:
                        pass  # Silently continue if PDF extraction fails

            # Include notes/summary if no PDF content was added
            if not pdf_content_added and notes and notes.strip():
                paper_context += f"Notes/Summary: {notes}\n"

            context_parts.append(paper_context)

        return "\n".join(context_parts)

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
                title = getattr(paper, "title", "Unknown Title")
                authors = getattr(paper, "author_names", "Unknown Authors")
                year = getattr(paper, "year", "Unknown Year")
                venue = getattr(paper, "venue_full", "Unknown Venue")
                abstract = getattr(paper, "abstract", "")

                lines.append(f"**Paper {i}**: {title}")
                lines.append(f"- Authors: {authors}")
                lines.append(f"- Venue: {venue} ({year})")
                if abstract:
                    lines.append(f"- Abstract: {abstract}")
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
                lines.append(f"**Assistant ({self.model_name})**: {content}")

            lines.append("")

        return "\n".join(lines)
