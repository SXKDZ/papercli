"""
Custom dialog for editing paper metadata in a full-window form.
"""

from typing import Callable, Dict, Any

from prompt_toolkit.layout.containers import HSplit, VSplit
from prompt_toolkit.widgets import Button, Dialog, Frame, Label, TextArea

class EditDialog:
    """A full-window dialog for editing paper metadata."""

    def __init__(self, paper_data: Dict[str, Any], callback: Callable):
        self.paper_data = paper_data
        self.callback = callback
        self.result = None

        # Create text area widgets for each field
        self.title_area = TextArea(
            text=paper_data.get("title", ""),
            multiline=False,
            focusable=True,
            style="class:textarea",
        )
        self.authors_area = TextArea(
            text=", ".join(paper_data.get("authors", [])),
            multiline=False,
            focusable=True,
            style="class:textarea",
        )
        self.year_area = TextArea(
            text=str(paper_data.get("year", "")),
            multiline=False,
            focusable=True,
            style="class:textarea",
        )
        self.venue_full_area = TextArea(
            text=paper_data.get("venue_full", ""),
            multiline=False,
            focusable=True,
            style="class:textarea",
        )
        self.venue_acronym_area = TextArea(
            text=paper_data.get("venue_acronym", ""),
            multiline=False,
            focusable=True,
            style="class:textarea",
        )
        self.abstract_area = TextArea(
            text=paper_data.get("abstract", ""),
            multiline=True,
            focusable=True,
            style="class:textarea",
        )
        self.notes_area = TextArea(
            text=paper_data.get("notes", ""),
            multiline=True,
            focusable=True,
            style="class:textarea",
        )

        # Create buttons
        self.save_button = Button(text="Save", handler=self._handle_save)
        self.cancel_button = Button(text="Cancel", handler=self._handle_cancel)

        # Create the dialog layout
        body = VSplit(
            [
                HSplit([Label(text="Title:", width=18), self.title_area]),
                HSplit([Label(text="Authors:", width=18), self.authors_area]),
                HSplit([Label(text="Year:", width=18), self.year_area]),
                HSplit([Label(text="Venue (Full):", width=18), self.venue_full_area]),
                HSplit([Label(text="Venue (Acronym):", width=18), self.venue_acronym_area]),
                Label(text="Abstract:"),
                Frame(self.abstract_area, height=5),
                Label(text="Notes:"),
                Frame(self.notes_area, height=5),
            ],
            padding=1,
        )

        self.dialog = Dialog(
            title="Edit Paper Metadata",
            body=body,
            buttons=[self.save_button, self.cancel_button],
            with_background=True,
            modal=True,
        )

    def _handle_save(self):
        """Handle the save button press."""
        self.result = {
            "title": self.title_area.text,
            "authors": [name.strip() for name in self.authors_area.text.split(",")],
            "year": int(self.year_area.text) if self.year_area.text.strip() else None,
            "venue_full": self.venue_full_area.text,
            "venue_acronym": self.venue_acronym_area.text,
            "abstract": self.abstract_area.text,
            "notes": self.notes_area.text,
        }
        self.callback(self.result)

    def _handle_cancel(self):
        """Handle the cancel button press."""
        self.callback(None)

    def __pt_container__(self):
        return self.dialog
