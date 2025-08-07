import os
from textual.app import ComposeResult
from textual.containers import VerticalScroll, HorizontalScroll, Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Button, Static, TextArea, RichLog
from textual.screen import ModalScreen
from typing import Callable, Dict, Any, List, Optional
import threading
import openai
from openai import OpenAI

class ChatDialog(ModalScreen):
    """A modal dialog for chat interactions with OpenAI."""

    DEFAULT_CSS = """
    ChatDialog {
        align: center middle;
    }
    
    #chat-container {
        width: 90%;
        height: 80%;
        border: thick $primary;
        background: $surface;
    }
    
    #chat-history {
        height: 1fr;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }
    
    #input-area {
        height: auto;
        margin: 1;
    }
    
    #user-input {
        height: 3;
        margin: 0 1;
    }
    
    #button-bar {
        height: auto;
        align: center middle;
        margin: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+enter", "send_message", "Send"),
    ]

    def __init__(self, papers: List[Any], callback: Callable[[Dict[str, Any] | None], None], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.papers = papers or []
        self.callback = callback
        self.chat_history = []
        self.openai_client = None
        
        # Initialize OpenAI client if API key is available
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        with Container(id="chat-container"):
            yield Static(f"Chat with Papers ({len(self.papers)} selected)", id="chat-title")
            yield RichLog(id="chat-history", markup=True)
            with Container(id="input-area"):
                yield TextArea(id="user-input")
            with Horizontal(id="button-bar"):
                yield Button("Send", id="send-button", variant="primary")
                yield Button("Save Chat", id="save-button", variant="default")
                yield Button("Close", id="close-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the chat with paper information."""
        chat_log = self.query_one("#chat-history", RichLog)
        
        if not self.papers:
            chat_log.write("No papers selected for chat.", style="dim")
            return
            
        if not self.openai_client:
            chat_log.write("[red]OpenAI API key not configured. Set OPENAI_API_KEY environment variable.[/red]")
            return
            
        # Display paper information
        chat_log.write("[bold blue]📚 Selected Papers:[/bold blue]")
        for i, paper in enumerate(self.papers, 1):
            title = getattr(paper, 'title', 'Unknown Title')
            authors = getattr(paper, 'author_names', 'Unknown Authors')
            year = getattr(paper, 'year', 'Unknown Year')
            chat_log.write(f"[bold]{i}.[/bold] {title}")
            chat_log.write(f"   [dim]Authors:[/dim] {authors} [dim]({year})[/dim]")
            
        chat_log.write("\n[bold green]💬 Ready to chat! Ask questions about the selected papers.[/bold green]")

    def action_send_message(self) -> None:
        """Send the user message."""
        self._send_message()

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
            chat_log.write("[red]OpenAI API key not configured.[/red]")
            return
            
        # Display user message
        chat_log.write(f"[bold green]You:[/bold green] {message}")
        user_input.text = ""
        
        # Add loading indicator
        chat_log.write("[dim]🤖 Thinking...[/dim]")
        
        # Send request in background thread
        def send_request():
            try:
                # Prepare context about papers
                paper_context = self._build_paper_context()
                
                # Build messages for API
                messages = [
                    {
                        "role": "system", 
                        "content": f"You are a helpful AI assistant discussing research papers. Here are the papers we're discussing:\n\n{paper_context}\n\nPlease provide helpful, accurate responses about these papers."
                    },
                    {"role": "user", "content": message}
                ]
                
                # Get response from OpenAI
                model = os.getenv("OPENAI_MODEL", "gpt-4o")
                response = self.openai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1000,
                    temperature=0.7
                )
                
                assistant_message = response.choices[0].message.content
                
                # Update UI in main thread
                self.app.call_from_thread(self._display_response, assistant_message)
                
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                self.app.call_from_thread(self._display_error, error_msg)
        
        # Start background thread
        thread = threading.Thread(target=send_request, daemon=True)
        thread.start()

    def _display_response(self, response: str) -> None:
        """Display AI response in chat log."""
        chat_log = self.query_one("#chat-history", RichLog)
        # Remove loading indicator (last line)
        chat_log.clear()
        # Re-add all previous content
        for entry in self.chat_history:
            chat_log.write(entry["content"], style=entry.get("style", ""))
        
        # Add new response
        chat_log.write(f"[bold blue]🤖 Assistant:[/bold blue] {response}")
        
        # Store in history
        self.chat_history.append({"role": "assistant", "content": response, "style": ""})

    def _display_error(self, error: str) -> None:
        """Display error message."""
        chat_log = self.query_one("#chat-history", RichLog)
        chat_log.write(f"[red]{error}[/red]")

    def _build_paper_context(self) -> str:
        """Build context string about papers."""
        context_parts = []
        for i, paper in enumerate(self.papers, 1):
            title = getattr(paper, 'title', 'Unknown Title')
            authors = getattr(paper, 'author_names', 'Unknown Authors') 
            year = getattr(paper, 'year', 'Unknown Year')
            abstract = getattr(paper, 'abstract', '')
            
            paper_info = f"Paper {i}: {title}\nAuthors: {authors}\nYear: {year}"
            if abstract:
                paper_info += f"\nAbstract: {abstract}"
            context_parts.append(paper_info)
        
        return "\n\n".join(context_parts)

    def _save_chat(self) -> None:
        """Save chat history to file."""
        if not self.chat_history:
            return
            
        try:
            from pathlib import Path
            from datetime import datetime
            
            # Get data directory
            data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
            if data_dir_env:
                data_dir = Path(data_dir_env).expanduser().resolve()
            else:
                data_dir = Path.home() / ".papercli"
            
            # Create chats directory
            chats_dir = data_dir / "chats"
            chats_dir.mkdir(exist_ok=True, parents=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chat_{timestamp}.md"
            filepath = chats_dir / filename
            
            # Write chat to file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# Chat Session - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("## Papers Discussed\n")
                for i, paper in enumerate(self.papers, 1):
                    title = getattr(paper, 'title', 'Unknown Title')
                    authors = getattr(paper, 'author_names', 'Unknown Authors')
                    f.write(f"{i}. **{title}** - {authors}\n")
                f.write("\n## Chat History\n\n")
                for entry in self.chat_history:
                    role = entry["role"].title()
                    content = entry["content"]
                    f.write(f"**{role}:** {content}\n\n")
            
            chat_log = self.query_one("#chat-history", RichLog)
            chat_log.write(f"[green]💾 Chat saved to {filepath.name}[/green]")
            
        except Exception as e:
            chat_log = self.query_one("#chat-history", RichLog)  
            chat_log.write(f"[red]Error saving chat: {e}[/red]")

    def action_cancel(self) -> None:
        self.dismiss(None)
