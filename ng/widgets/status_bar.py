from textual.widgets import Static
from textual.containers import Container
from textual.app import App, ComposeResult
from textual.reactive import reactive
import threading
import time

class StatusBar(Static):
    """A custom status bar widget for PaperCLI."""

    DEFAULT_CSS = """
    StatusBar, #status-bar {
        height: 1;
        background: $panel;
        color: $text;
        width: 100%;
        max-width: 100%;
        min-width: 100%;
        margin: 0;
        padding: 0;
    }
    """

    status_text = reactive("Ready")
    progress_text = reactive("")
    status_type = reactive("info") # info, success, error, warning, llm

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._animation_thread = None
        self._is_animating = False
        self._animation_frame = 0
        self._original_text = ""

    def watch_status_text(self, new_text: str) -> None:
        self.update_display()

    def watch_progress_text(self, new_text: str) -> None:
        self.update_display()

    def watch_status_type(self, new_type: str) -> None:
        self.update_display()

    def update_display(self) -> None:
        try:
            # Try to get the console width from the app
            if hasattr(self, 'app') and hasattr(self.app, 'console'):
                width = self.app.console.width
            elif hasattr(self, 'screen') and hasattr(self.screen, 'size'):
                width = self.screen.size.width
            elif hasattr(self, 'size') and self.size.width > 0:
                width = self.size.width
            else:
                # Get terminal width from console size
                import os
                width = os.get_terminal_size().columns
        except:
            width = 120  # fallback width
        
        base_content = self.progress_text if self.progress_text else self.status_text
        content = f" {base_content}"
        
        # Pad content to fill the full width so background spans entire width
        padded_content = content.ljust(width)

        # Apply styling based on status_type
        if self.status_type == "success":
            self.update(f"[green on black]{padded_content}[/]")
        elif self.status_type == "error":
            self.update(f"[red on black]{padded_content}[/]")
        elif self.status_type == "warning":
            self.update(f"[yellow on black]{padded_content}[/]")
        elif self.status_type == "llm":
            self.update(f"[blue on black]{padded_content}[/]")
        else:
            self.update(f"[white on black]{padded_content}[/]")

    def set_status(self, text: str, status_type: str = "info"):
        """Set status text with optional type for color coding and icon."""
        self._stop_animation()

        if status_type == "llm" and ("streaming" in text.lower() or "generating" in text.lower()):
            self._original_text = text
            self._start_llm_animation(text)
        else:
            self.status_text = text
            self.status_type = status_type

    def set_success(self, text: str):
        """Set success status (green background with ✓ prefix)."""
        self.set_status(text, "success")

    def set_error(self, text: str):
        """Set error status (red background with ✗ prefix)."""
        self.set_status(text, "error")

    def set_warning(self, text: str):
        """Set warning status (yellow background with ⚠ prefix)."""
        self.set_status(text, "warning")

    def set_progress(self, text: str):
        """Set progress text."""
        self.progress_text = text

    def _start_llm_animation(self, base_text: str):
        """Start LLM animation with star frames."""
        if self._is_animating:
            return

        self._is_animating = True
        self._animation_frame = 0

        def animate():
            star_frames = ["✶", "✸", "✹", "✺", "✹", "✷"]
            while self._is_animating:
                current_star = star_frames[self._animation_frame % len(star_frames)]
                self.status_text = f"{current_star} {base_text}"
                self._animation_frame += 1
                time.sleep(0.2)

        self._animation_thread = threading.Thread(target=animate, daemon=True)
        self._animation_thread.start()

    def _stop_animation(self):
        """Stop any running animation."""
        if self._is_animating:
            self._is_animating = False
            if self._animation_thread:
                self._animation_thread = None