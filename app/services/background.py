"""Background service - Background task management with status updates."""

import threading

from prompt_toolkit.application import get_app


class BackgroundOperationService:
    """Service for running operations in background threads with status updates."""

    def __init__(self, status_bar=None, log_callback=None):
        self.status_bar = status_bar
        self.log_callback = log_callback

    def run_operation(
        self, operation_func, operation_name, initial_message=None, on_complete=None
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
            get_app().invalidate()

        def background_worker():
            try:
                if self.log_callback:
                    self.log_callback(
                        "background_ops_start",
                        f"Started background operation: {operation_name}",
                    )

                # Run the operation
                result = operation_func()

                def schedule_success():
                    if self.log_callback:
                        self.log_callback(
                            "background_ops_complete",
                            f"Completed background operation: {operation_name}",
                        )

                    # Call completion callback with result
                    if on_complete:
                        on_complete(result, None)

                    get_app().invalidate()

                return get_app().loop.call_soon_threadsafe(schedule_success)

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

                    get_app().invalidate()

                return get_app().loop.call_soon_threadsafe(schedule_error)

        thread = threading.Thread(target=background_worker, daemon=True)
        thread.start()
        return thread
