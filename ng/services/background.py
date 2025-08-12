from __future__ import annotations
import threading
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class BackgroundOperationService:
    """Service for running operations in background threads with status updates."""

    def __init__(self, app: PaperCLIApp):
        self.app = app

    def run_operation(
        self,
        operation_func: Callable,
        operation_name: str,
        initial_message: str = None,
        on_complete: Callable = None,
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
        # Show initial toast
        if initial_message:
            self.app.notify(initial_message, severity="information")

        def background_worker():
            try:
                self.app._add_log(
                    "background_ops_start",
                    f"Started background operation: {operation_name}",
                )

                # Run the operation
                result = operation_func()

                def schedule_success():
                    self.app._add_log(
                        "background_ops_complete",
                        f"Completed background operation: {operation_name}",
                    )

                    # Call completion callback with result
                    if on_complete:
                        on_complete(result, None)

                self.app.call_from_thread(schedule_success)

            except Exception as e:

                def schedule_error(error=e):
                    self.app._add_log(
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
