from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

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

        thread = threading.Thread(
            target=lambda: self._background_worker(
                operation_func, operation_name, on_complete
            ),
            daemon=True,
        )
        thread.start()
        return thread

    def _background_worker(self, operation_func, operation_name, on_complete):
        """Execute the operation in background with proper error handling."""
        try:
            self.app._add_log(
                "background_ops_start",
                f"Started background operation: {operation_name}",
            )

            result = operation_func()
            self.app.call_from_thread(
                lambda: self._schedule_success(operation_name, result, on_complete)
            )

        except Exception as e:
            self.app.call_from_thread(
                lambda: self._schedule_error(operation_name, e, on_complete)
            )

    def _schedule_success(self, operation_name, result, on_complete):
        """Handle successful operation completion."""
        self.app._add_log(
            "background_ops_complete",
            f"Completed background operation: {operation_name}",
        )
        if on_complete:
            on_complete(result, None)

    def _schedule_error(self, operation_name, error, on_complete):
        """Handle operation error."""
        self.app._add_log(
            f"{operation_name}_error",
            f"Error in {operation_name}: {error}",
        )
        if on_complete:
            on_complete(None, error)
