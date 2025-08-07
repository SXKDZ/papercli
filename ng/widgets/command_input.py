from textual.widgets import Input
from textual.message import Message
from ng.widgets.completer import CommandCompleter

class CommandInput(Input):
    """A custom input widget for handling commands."""

    class CommandEntered(Message):
        """Posted when a command is entered."""
        def __init__(self, command: str) -> None:
            self.command = command
            super().__init__()

    def __init__(self, app=None, *args, **kwargs):
        # Set up auto-completion
        if 'suggester' not in kwargs:
            kwargs['suggester'] = CommandCompleter(app)
        super().__init__(*args, **kwargs)

    def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission."""
        self.post_message(self.CommandEntered(message.value))
        self.value = "" # Clear the input after submission