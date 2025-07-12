"""
Custom dialog for editing paper metadata in a full-window form with paper type buttons.
"""

from typing import Callable, Dict, Any, List

from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.application import get_app
from titlecase import titlecase

from .services import CollectionService, AuthorService


from prompt_toolkit.widgets import TextArea


class EditDialog:
    """A full-window dialog for editing paper metadata with paper type buttons."""

    def __init__(self, paper_data: Dict[str, Any], callback: Callable, log_callback: Callable, read_only_fields: List[str] = None):
        self.paper_data = paper_data
        self.callback = callback
        self.log_callback = log_callback
        self.result = None
        self.collection_service = CollectionService()
        self.author_service = AuthorService()
        self.read_only_fields = read_only_fields or []
        
        self.paper_types = {
            "Conference": "conference", "Journal": "journal", "Workshop": "workshop",
            "Preprint": "preprint", "Website": "website", "Other": "other"
        }
        
        self.fields_by_type = {
            "conference": ["title", "author_names", "venue_full", "venue_acronym", "year", "pages", "doi", "dblp_url", "pdf_path", "collections", "abstract", "notes"],
            "journal": ["title", "author_names", "venue_full", "year", "volume", "issue", "pages", "doi", "pdf_path", "collections", "abstract", "notes"],
            "workshop": ["title", "author_names", "venue_full", "venue_acronym", "year", "pages", "doi", "dblp_url", "pdf_path", "collections", "abstract", "notes"],
            "preprint": ["title", "author_names", "venue_full", "year", "arxiv_id", "doi", "pdf_path", "collections", "abstract", "notes"],
            "website": ["title", "author_names", "year", "google_scholar_url", "pdf_path", "collections", "abstract", "notes"],
            "other": ["title", "author_names", "venue_full", "venue_acronym", "year", "volume", "issue", "pages", "doi", "arxiv_id", "dblp_url", "google_scholar_url", "pdf_path", "collections", "abstract", "notes"]
        }
        
        self.current_paper_type = paper_data.get("paper_type", "conference")
        self.input_fields = {}
        self._create_layout()
        self._add_key_bindings()

    def _create_input_fields(self):
        """Create input fields for fields visible in the current paper type."""
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        self.input_fields = {}

        authors = self.paper_data.get("authors", [])
        if isinstance(authors, list):
            author_names = ", ".join([getattr(a, 'full_name', str(a)) for a in authors])
        else:
            author_names = str(authors) if authors else ""

        collections = self.paper_data.get("collections", [])
        if isinstance(collections, list):
            collection_names = ", ".join([getattr(c, 'name', str(c)) for c in collections])
        else:
            collection_names = str(collections) if collections else ""

        all_field_values = {
            "title": self.paper_data.get("title", ""), "author_names": author_names,
            "venue_full": self.paper_data.get("venue_full", ""), "venue_acronym": self.paper_data.get("venue_acronym", ""),
            "year": str(self.paper_data.get("year", "")), "volume": self.paper_data.get("volume", ""),
            "issue": self.paper_data.get("issue", ""), "pages": self.paper_data.get("pages", ""),
            "doi": self.paper_data.get("doi", ""), "arxiv_id": self.paper_data.get("arxiv_id", ""),
            "dblp_url": self.paper_data.get("dblp_url", ""), "google_scholar_url": self.paper_data.get("google_scholar_url", ""),
            "pdf_path": self.paper_data.get("pdf_path", ""), "collections": collection_names,
            "abstract": self.paper_data.get("abstract", ""), "notes": self.paper_data.get("notes", ""),
        }

        for field_name in visible_fields:
            if field_name in all_field_values:
                value = str(all_field_values[field_name] or "")
                is_read_only = field_name in self.read_only_fields
                
                # Make title, author_names, abstract, and notes multiline
                is_multiline = field_name in ["title", "author_names", "abstract", "notes"]
                
                input_field = TextArea(
                    text=value,
                    multiline=is_multiline,
                    read_only=is_read_only,
                    width=Dimension(min=60, preferred=100), # Make input fields wider
                    style="class:textarea" if not is_read_only else "class:textarea.readonly",
                    focusable=not is_read_only, # Explicitly set focusable
                )
                
                # Set height for multiline fields
                if field_name in ["title", "author_names"]:
                    input_field.window.height = Dimension(preferred=2, max=3)
                elif field_name in ["abstract", "notes"]:
                    input_field.window.height = Dimension(preferred=4, max=6)
                else:
                    input_field.window.height = Dimension(preferred=1, max=1)
                
                self.input_fields[field_name] = input_field

    def _build_body_components(self):
        """Builds the UI components for the dialog body."""
        self._create_input_fields()

        type_buttons = []
        for display_name, type_value in self.paper_types.items():
            is_selected = self.current_paper_type == type_value
            style = "class:button.focused" if is_selected else "class:button"
            button = Button(text=display_name, handler=lambda t=type_value: self._set_paper_type(t), width=len(display_name) + 4)
            button.window.style = style
            type_buttons.append(button)
        type_buttons_row = VSplit(type_buttons, padding=1, style="class:button-row")

        all_field_containers = []
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        for field_name in visible_fields:
            if field_name in self.input_fields:
                label_text = field_name.replace("_", " ").title()
                label_window = Window(
                    content=FormattedTextControl(f"{label_text}:", focusable=False), 
                    width=18,  # Fixed width for consistent alignment
                    style="class:dialog.label"
                )
                
                field_container = VSplit([
                    label_window,
                    self.input_fields[field_name].window  # This will expand to fill remaining space
                ])
                all_field_containers.append(field_container)
        
        fields_content = HSplit(all_field_containers, padding=1)
        fields_layout = ScrollablePane(
            content=fields_content, 
            show_scrollbar=True, 
            keep_cursor_visible=True,
            width=Dimension(min=100, preferred=120)  # Ensure content fits within dialog
        )
        
        # Put "Paper Type:" label and buttons on the same line
        paper_type_row = VSplit([
            Window(content=FormattedTextControl("Paper Type:"), width=18, style="class:dialog.label"),
            type_buttons_row
        ])
        
        # Add the note below the paper type row
        note_text = FormattedTextControl("Ctrl-S: Save, Esc: Exit", style="class:dialog.note")
        note_window = Window(content=note_text, height=1, align=WindowAlign.RIGHT)

        return [
            paper_type_row,
            note_window,
            fields_layout,
        ]

    def _create_layout(self):
        """Creates the dialog layout upon initialization."""
        body_components = self._build_body_components()
        self.body_container = HSplit(
            body_components, 
            padding=2,  # Increase padding to 2 for exactly 2 lines of spacing
            width=Dimension(min=110, preferred=130)  # Ensure body fits within dialog frame
        )
        
        self.dialog = Dialog(
            title="Edit Paper Metadata",
            body=self.body_container,
            buttons=[Button(text="Save", handler=self._handle_save), Button(text="Cancel", handler=self._handle_cancel)],
            with_background=False, modal=True,  # Remove shadow by setting with_background=False
            width=Dimension(min=120, preferred=140),  # Make dialog wider
        )
        self._set_initial_focus()

    def _set_paper_type(self, paper_type: str):
        """Sets the paper type and rebuilds the dialog body."""
        current_values = {name: field.text for name, field in self.input_fields.items()}
        self.current_paper_type = paper_type

        for field_name, value in current_values.items():
            if field_name in ["author_names", "collections"]:
                self.paper_data[field_name.replace("_names", "")] = [name.strip() for name in value.split(",") if name.strip()]
            elif field_name == "year":
                self.paper_data["year"] = int(value) if value.isdigit() else None
            else:
                self.paper_data[field_name] = value
        
        self.body_container.children = self._build_body_components()
        self._set_initial_focus()
        get_app().invalidate()
        self._focus_first_visible_field()

    def _handle_save(self):
        """Handles the save button press."""
        result = {"paper_type": self.current_paper_type}
        changes_made = []
        
        for field_name, input_field in self.input_fields.items():
            if field_name in self.read_only_fields:
                continue
            
            new_value = input_field.text.strip()
            
            # Get the original value. For authors and collections, we need to format them as a string.
            if field_name == "author_names":
                authors = self.paper_data.get("authors", [])
                if isinstance(authors, list):
                    old_value = ", ".join([getattr(a, 'full_name', str(a)) for a in authors])
                else:
                    old_value = str(authors) if authors else ""
            elif field_name == "collections":
                collections = self.paper_data.get("collections", [])
                if isinstance(collections, list):
                    old_value = ", ".join([getattr(c, 'name', str(c)) for c in collections])
                else:
                    old_value = str(collections) if collections else ""
            else:
                old_value = self.paper_data.get(field_name, "")
                # Ensure old_value is a string, treating None as empty string
                old_value = str(old_value) if old_value is not None else ""

            # Normalize old_value and new_value for comparison (treat None and "" as equivalent)
            normalized_old_value = old_value
            normalized_new_value = new_value if new_value is not None else ""

            # Special handling for title to apply smart title case
            if field_name == "title":
                new_value = titlecase(new_value)
                normalized_new_value = new_value # Update normalized value after titlecase

            if normalized_old_value != normalized_new_value:
                changes_made.append(f"{field_name} from '{old_value}' to '{new_value}'")

            if field_name == "author_names":
                names = [name.strip() for name in new_value.split(",") if name.strip()]
                result["authors"] = [self.author_service.get_or_create_author(name) for name in names]
            elif field_name == "collections":
                names = [name.strip() for name in new_value.split(",") if name.strip()]
                result["collections"] = [self.collection_service.get_or_create_collection(name) for name in names]
            elif field_name == "year":
                result["year"] = int(new_value) if new_value.isdigit() else None
            else:
                result[field_name] = new_value if new_value else None
        
        if changes_made:
            paper_id = self.paper_data.get('id', 'New Paper')
            log_message = f"Paper '{self.paper_data.get('title')}' (ID: {paper_id}) updated: \n{'  \n'.join(changes_made)}"
            self.log_callback("edit", log_message)
        
        self.result = result
        self.callback(self.result)

    def _handle_cancel(self):
        self.callback(None)

    def _set_initial_focus(self):
        """Sets the initial focus to the first editable field."""
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        
        for field_name in visible_fields:
            if field_name in self.input_fields and not self.input_fields[field_name].read_only:
                self.initial_focus = self.input_fields[field_name].window
                return
        
        self.initial_focus = self.dialog.buttons[0]

    def _focus_first_visible_field(self):
        """Focuses the first editable field in the dialog."""
        self._set_initial_focus()
        if self.initial_focus:
            # First unfocus all fields
            for field in self.input_fields.values():
                # TextArea does not have a 'focused' attribute like CustomInputField did.
                # Focus is managed by the layout. We just need to ensure the correct window is focused.
                pass
            
            get_app().layout.focus(self.initial_focus)

    def get_initial_focus(self):
        return getattr(self, 'initial_focus', None)
    
    def _get_focusable_fields(self):
        """Get list of focusable input field windows in order."""
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        focusable_windows = []
        field_names = []
        
        for field_name in visible_fields:
            if field_name in self.input_fields and not self.input_fields[field_name].read_only:
                focusable_windows.append(self.input_fields[field_name].window)
                field_names.append(field_name)
        
        self.focusable_field_names = field_names  # Store for debugging
        return focusable_windows
    
    def _focus_next_field(self):
        """Focus the next input field."""
        focusable_windows = self._get_focusable_fields()
        if not focusable_windows:
            return
            
        current_window = get_app().layout.current_window
        
        try:
            current_index = focusable_windows.index(current_window)
            next_index = (current_index + 1) % len(focusable_windows)
            next_window = focusable_windows[next_index]
            current_field = self.focusable_field_names[current_index] if current_index < len(self.focusable_field_names) else "unknown"
            next_field = self.focusable_field_names[next_index] if next_index < len(self.focusable_field_names) else "unknown"
        except ValueError:
            # Current window not in list, focus first
            next_window = focusable_windows[0]
            next_field = self.focusable_field_names[0] if self.focusable_field_names else "unknown"
        
        # Update focused state - manually force focus
        for field_name, field in self.input_fields.items():
            # Check if the window of the TextArea matches the next_window
            field.focused = (field.window == next_window)
        
        get_app().layout.focus(next_window)
        get_app().invalidate()
    
    def _focus_previous_field(self):
        """Focus the previous input field."""
        focusable_windows = self._get_focusable_fields()
        if not focusable_windows:
            return
            
        current_window = get_app().layout.current_window
        try:
            current_index = focusable_windows.index(current_window)
            prev_index = (current_index - 1) % len(focusable_windows)
            prev_window = focusable_windows[prev_index]
        except ValueError:
            # Current window not in list, focus last
            prev_window = focusable_windows[-1]
        
        
        
        get_app().layout.focus(prev_window)
        get_app().invalidate()

    def _add_key_bindings(self):
        kb = KeyBindings()
        
        @kb.add("c-s")
        def _(event):
            self._handle_save()

        @kb.add("escape")
        def _(event):
            self._handle_cancel()

        

        self.body_container.key_bindings = merge_key_bindings([self.body_container.key_bindings or KeyBindings(), kb])

    def __pt_container__(self):
        return self.dialog