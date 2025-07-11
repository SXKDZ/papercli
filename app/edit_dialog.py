"""
Custom dialog for editing paper metadata in a full-window form with paper type buttons.
"""

from typing import Callable, Dict, Any, List, Optional

from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, Frame, Label, TextArea
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText

from .models import Paper
from .services import CollectionService


class EditDialog:
    """A full-window dialog for editing paper metadata with paper type buttons."""

    def __init__(self, paper_data: Dict[str, Any], callback: Callable):
        self.paper_data = paper_data
        self.callback = callback
        self.result = None
        self.collection_service = CollectionService()
        
        # Paper types and their corresponding fields
        self.paper_types = {
            "Conference": "conference",
            "Journal": "journal", 
            "Workshop": "workshop",
            "Preprint": "preprint",
            "Website": "website",
            "Other": "other"
        }
        
        # Define which fields are visible for each paper type
        self.fields_by_type = {
            "conference": ["title", "author_names", "venue_full", "venue_acronym", "year", "pages", "doi", "dblp_url", "pdf_path", "collections", "abstract", "notes"],
            "journal": ["title", "author_names", "venue_full", "year", "volume", "issue", "pages", "doi", "pdf_path", "collections", "abstract", "notes"],
            "workshop": ["title", "author_names", "venue_full", "venue_acronym", "year", "pages", "doi", "dblp_url", "pdf_path", "collections", "abstract", "notes"],
            "preprint": ["title", "author_names", "venue_full", "year", "arxiv_id", "doi", "pdf_path", "collections", "abstract", "notes"],
            "website": ["title", "author_names", "year", "google_scholar_url", "pdf_path", "collections", "abstract", "notes"],
            "other": ["title", "author_names", "venue_full", "venue_acronym", "year", "volume", "issue", "pages", "doi", "arxiv_id", "dblp_url", "google_scholar_url", "pdf_path", "collections", "abstract", "notes"]
        }
        
        # Current paper type
        self.current_paper_type = paper_data.get("paper_type", "conference")
        
        # Create text area widgets for visible fields only
        self.text_areas = {}
        self._create_text_areas()
        
        # Create the dialog layout
        self._create_layout()
        
        # Set initial focus to the first text area
        self._set_initial_focus()
        
        # Add key bindings
        self._add_key_bindings()
        
        
    def _create_text_areas(self):
        """Create text areas only for fields visible in current paper type."""
        # Get visible fields for current paper type
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        
        # Clear existing text areas
        self.text_areas = {}
        
        # Get author names and collections from paper data
        authors = self.paper_data.get("authors", [])
        if isinstance(authors, list):
            author_names = ", ".join(authors)
        else:
            author_names = str(authors) if authors else ""
            
        collections = self.paper_data.get("collections", [])
        if isinstance(collections, str):
            collection_names = collections
        elif isinstance(collections, list):
            collection_names = ", ".join([c.name if hasattr(c, 'name') else str(c) for c in collections])
        else:
            collection_names = str(collections) if collections else ""
        
        # Create text areas only for visible fields
        all_field_values = {
            "title": self.paper_data.get("title", ""),
            "author_names": author_names,
            "venue_full": self.paper_data.get("venue_full", ""),
            "venue_acronym": self.paper_data.get("venue_acronym", ""),
            "year": str(self.paper_data.get("year", "")),
            "volume": self.paper_data.get("volume", ""),
            "issue": self.paper_data.get("issue", ""),
            "pages": self.paper_data.get("pages", ""),
            "doi": self.paper_data.get("doi", ""),
            "arxiv_id": self.paper_data.get("arxiv_id", ""),
            "dblp_url": self.paper_data.get("dblp_url", ""),
            "google_scholar_url": self.paper_data.get("google_scholar_url", ""),
            "pdf_path": self.paper_data.get("pdf_path", ""),
            "collections": collection_names,
            "abstract": self.paper_data.get("abstract", ""),
            "notes": self.paper_data.get("notes", ""),
        }
        
        # Only create text areas for visible fields
        for field_name in visible_fields:
            if field_name in all_field_values:
                value = all_field_values[field_name]
                
                if field_name in ["abstract", "notes"]:
                    text_area = TextArea(
                        text=value,
                        multiline=True,
                        focusable=True,
                        style="class:textarea",
                        height=Dimension(preferred=3, max=6),
                    )
                else:
                    text_area = TextArea(
                        text=value,
                        multiline=False,
                        focusable=True,
                        style="class:textarea",
                        height=Dimension(preferred=1, max=1),
                    )
                
                # Force the text area to be editable
                text_area.read_only = False
                if hasattr(text_area, 'buffer'):
                    text_area.buffer.read_only = False
                if hasattr(text_area.control, 'buffer'):
                    text_area.control.buffer.read_only = False
                
                self.text_areas[field_name] = text_area
    
    def _set_paper_type(self, paper_type: str):
        """Set the current paper type and update the layout."""
        # Debug: Print what's happening
        # print(f"DEBUG: Switching from {self.current_paper_type} to {paper_type}")
        
        # Save current field values before recreating text areas
        current_values = {}
        for field_name, text_area in self.text_areas.items():
            current_values[field_name] = text_area.text
        # print(f"DEBUG: Saved current values: {list(current_values.keys())}")
        
        self.current_paper_type = paper_type
        # print(f"DEBUG: New visible fields: {self.fields_by_type.get(self.current_paper_type, [])}")
        
        # Update paper_data with current values to preserve user input
        for field_name, value in current_values.items():
            if field_name == "author_names":
                self.paper_data["authors"] = [name.strip() for name in value.split(",") if name.strip()]
            elif field_name == "collections":
                # Store collections as simple string for now
                self.paper_data["collections"] = value
            elif field_name == "year":
                try:
                    self.paper_data["year"] = int(value) if value else None
                except ValueError:
                    self.paper_data["year"] = None
            else:
                self.paper_data[field_name] = value
        
        # Dialog will be recreated in _create_layout()
        # Recreate text areas for the new paper type
        self._create_text_areas()
        # print(f"DEBUG: Created text areas: {list(self.text_areas.keys())}")
        # Recreate the layout with the new paper type fields
        self._create_layout()
        # Reapply key bindings after layout recreation
        self._add_key_bindings()
        # Reset focus to the first visible field
        self._set_initial_focus()
        # Force a refresh of the display and reset focus
        from prompt_toolkit.application import get_app
        try:
            app = get_app()
            app.invalidate()
            # Focus the first visible text area to rebuild focus chain
            visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
            for field_name in visible_fields:
                if field_name in self.text_areas:
                    app.layout.focus(self.text_areas[field_name])
                    break
        except:
            pass
    
    def _create_layout(self):
        """Create the main dialog layout."""
        # Paper type selection as VSplit for horizontal layout with better styling
        type_buttons = []
        for display_name, type_value in self.paper_types.items():
            button = Button(
                text=display_name,
                handler=lambda t=type_value: self._set_paper_type(t),
                width=len(display_name) + 2
            )
            type_buttons.append(button)
        
        type_buttons_row = VSplit(type_buttons, padding=1)
        
        # Current paper type display with better styling
        current_type_display = Window(
            content=FormattedTextControl(
                text=lambda: FormattedText([("class:selected bold", f"Selected: {self.current_paper_type.title()}")])
            ),
            height=1
        )
        
        # Fields layout - show only fields that have text areas created
        all_field_containers = []
        
        # Get fields for current paper type
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        
        # Only show fields that actually exist in text_areas (debugging safety)
        for field_name in visible_fields:
            if field_name in self.text_areas:
                if field_name in ["abstract", "notes"]:
                    all_field_containers.append(Label(text=f"{field_name.title().replace('_', ' ')}:"))
                    all_field_containers.append(self.text_areas[field_name])
                else:
                    label = field_name.replace("_", " ").title()
                    if field_name == "author_names":
                        label = "Authors"
                    elif field_name == "venue_full":
                        label = "Venue/Journal"
                    elif field_name == "venue_acronym":
                        label = "Acronym"
                    elif field_name == "collections":
                        label = "Collections"
                    elif field_name == "google_scholar_url":
                        label = "URL"
                    elif field_name == "arxiv_id":
                        label = "ArXiv ID"
                    elif field_name == "dblp_url":
                        label = "DBLP URL"
                    elif field_name == "pdf_path":
                        label = "PDF Path"
                    
                    # Use HSplit for vertical stacking
                    all_field_containers.append(Label(text=f"{label}:"))
                    all_field_containers.append(self.text_areas[field_name])
        
        # Create a scrollable fields layout using ScrollablePane
        fields_content = HSplit(all_field_containers)
        fields_layout = ScrollablePane(
            content=fields_content,
            show_scrollbar=True,
            keep_cursor_visible=True,
            keep_focused_window_visible=True
        )
        
        # Main body
        body = HSplit([
            Label(text="Paper Type:"),
            type_buttons_row,
            current_type_display,
            Window(height=1),  # Spacer
            fields_layout,
        ])
        
        # Create buttons
        self.save_button = Button(text="Save", handler=self._handle_save)
        self.cancel_button = Button(text="Cancel", handler=self._handle_cancel)
        
        # Store the body for updates
        self.body = body
        
        # Always recreate the dialog to ensure proper layout updates
        self.dialog = Dialog(
            title="Edit Paper Metadata",
            body=body,
            buttons=[self.save_button, self.cancel_button],
            with_background=False,
            modal=True,
            width=Dimension(min=80, preferred=100, max=140),
        )

    def _handle_save(self):
        """Handle the save button press."""
        # Collect all field values
        result = {
            "paper_type": self.current_paper_type,
        }
        
        for field_name, text_area in self.text_areas.items():
            value = text_area.text.strip()
            
            if field_name == "author_names":
                # Convert comma-separated authors to list
                result["authors"] = [name.strip() for name in value.split(",") if name.strip()]
            elif field_name == "collections":
                # Handle collections - pass as list of names, not objects
                if value:
                    collection_names = [name.strip() for name in value.split(",") if name.strip()]
                    result["collections"] = collection_names
                else:
                    result["collections"] = []
            elif field_name == "year":
                # Convert year to integer
                try:
                    result["year"] = int(value) if value else None
                except ValueError:
                    result["year"] = None
            else:
                # Regular field
                result[field_name] = value if value else None
        
        self.result = result
        self.callback(self.result)

    def _handle_cancel(self):
        """Handle the cancel button press."""
        self.callback(None)

    def _set_initial_focus(self):
        """Set initial focus to the first visible text area."""
        # Get fields for current paper type
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        
        # Focus the first visible field
        for field_name in visible_fields:
            if field_name in self.text_areas:
                self.initial_focus = self.text_areas[field_name]
                break
    
    def get_initial_focus(self):
        """Return the widget that should get initial focus."""
        return getattr(self, 'initial_focus', None)
    
    def _add_key_bindings(self):
        """Add key bindings for the dialog."""
        kb = KeyBindings()
        
        @kb.add("c-s")  # Ctrl+S to save
        def save_shortcut(event):
            self._handle_save()
        
        @kb.add("escape")  # Esc to cancel
        def cancel_shortcut(event):
            self._handle_cancel()
        
        @kb.add("tab")  # Custom TAB navigation for visible fields only
        def tab_next(event):
            self._focus_next_visible_field()
        
        @kb.add("s-tab")  # Shift+TAB for previous field
        def tab_prev(event):
            self._focus_prev_visible_field()
        
        # Merge with existing key bindings instead of replacing them
        if hasattr(self.dialog.container, 'key_bindings') and self.dialog.container.key_bindings:
            self.dialog.container.key_bindings = merge_key_bindings([self.dialog.container.key_bindings, kb])
        else:
            self.dialog.container.key_bindings = kb
    
    def _get_visible_fields(self):
        """Get list of currently visible field names."""
        return self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
    
    def _get_current_field_index(self):
        """Get the index of the currently focused field in the visible fields list."""
        from prompt_toolkit.application import get_app
        try:
            app = get_app()
            current_focus = app.layout.current_window
            visible_fields = self._get_visible_fields()
            
            # Find which text area is currently focused
            for i, field_name in enumerate(visible_fields):
                if field_name in self.text_areas:
                    if self.text_areas[field_name].control == current_focus.content:
                        return i
        except:
            pass
        return 0
    
    def _focus_next_visible_field(self):
        """Focus the next visible field."""
        from prompt_toolkit.application import get_app
        try:
            app = get_app()
            visible_fields = self._get_visible_fields()
            current_index = self._get_current_field_index()
            
            # Move to next field, wrap around to beginning
            next_index = (current_index + 1) % len(visible_fields)
            next_field = visible_fields[next_index]
            
            if next_field in self.text_areas:
                app.layout.focus(self.text_areas[next_field])
        except:
            pass
    
    def _focus_prev_visible_field(self):
        """Focus the previous visible field."""
        from prompt_toolkit.application import get_app
        try:
            app = get_app()
            visible_fields = self._get_visible_fields()
            current_index = self._get_current_field_index()
            
            # Move to previous field, wrap around to end
            prev_index = (current_index - 1) % len(visible_fields)
            prev_field = visible_fields[prev_index]
            
            if prev_field in self.text_areas:
                app.layout.focus(self.text_areas[prev_field])
        except:
            pass

    def __pt_container__(self):
        return self.dialog