from __future__ import annotations
import threading
from typing import Callable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp
    from ng.widgets.status_bar import StatusBar

class BackgroundOperationService:
    """Service for running operations in background threads with status updates."""

    def __init__(self, app: PaperCLIApp, log_callback: Callable = None):
        self.app = app
        self.log_callback = log_callback
        self._status_bar = None

    @property
    def status_bar(self) -> StatusBar:
        """Lazy-load the status bar."""
        if self._status_bar is None:
            try:
                # Try to find status bar in the main screen stack
                for screen in reversed(self.app.screen_stack):
                    try:
                        self._status_bar = screen.query_one("#status-bar")
                        break
                    except:
                        continue
                if self._status_bar is None:
                    # Fallback: try current screen
                    self._status_bar = self.app.query_one("#status-bar")
            except:
                # Return None if status bar not available
                return None
        return self._status_bar

    def run_operation(
        self, operation_func: Callable, operation_name: str, initial_message: str = None, on_complete: Callable = None
    ):
        """
        Run an operation in the background with status updates.

        Args:
            operation_func: Function to run in background
            operation_name: Name for logging purposes
            initial_message: Initial status message to display
            on_complete: Callback function to call with result

        Returns:
            Thread object
        """
        # Set initial status
        if initial_message and self.status_bar:
            self.status_bar.set_status(initial_message, "loading")

        def background_worker():
            try:
                if self.log_callback:
                    self.log_callback("background_ops_start", f"Started background operation: {operation_name}")

                # Run the operation
                result = operation_func()

                def schedule_success():
                    if self.log_callback:
                        self.log_callback("background_ops_complete", f"Completed background operation: {operation_name}")

                    # Call completion callback with result
                    if on_complete:
                        on_complete(result, None)

                self.app.call_from_thread(schedule_success)

            except Exception as e:

                def schedule_error(error=e):
                    if self.log_callback:
                        self.log_callback(
                            f"{operation_name}_error",
                            f"Error in {operation_name}: {error}",
                        )

                    # Call completion callback with error
                    if on_complete:
                        on_complete(None, error)

                self.app.call_from_thread(schedule_error)

        thread = threading.Thread(target=background_worker, daemon=True)
        thread.start()
        return thread
