"""
Custom dialog for editing paper metadata in a full-window form with paper type buttons.
"""

from typing import Callable, Dict, Any, List, Optional

from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.application import get_app
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.validation import Validator, ValidationError
from titlecase import titlecase

from .services import CollectionService, AuthorService
from .validators import FilePathValidator, ArxivValidator, URLValidator, YearValidator


class CustomInputField:
    """A custom input field using FormattedTextControl with manual key handling."""
    
    def __init__(self, initial_text: str = "", multiline: bool = False, read_only: bool = False, field_name: str = ""):
        self.text = initial_text
        # Always position cursor one character after the last character
        self.cursor_position = len(initial_text)
        self.multiline = multiline
        self.read_only = read_only
        self.focused = False
        self.field_name = field_name
        
        # Create the control - disable built-in cursor since we'll draw our own
        self.control = FormattedTextControl(
            text=self._get_formatted_text,
            focusable=not read_only,
            show_cursor=False  # Disable built-in cursor to avoid double cursor
        )
        
        # Create the window with proper width
        self.window = Window(
            content=self.control,
            style="class:textarea" if not read_only else "class:textarea.readonly",
            width=Dimension(min=60, preferred=100)  # Make input fields wider
        )
        
        # Add key bindings
        if not read_only:
            self._setup_key_bindings()
    
    def _get_formatted_text(self):
        """Get the formatted text for display."""
        if self.read_only:
            return FormattedText([("class:textarea.readonly", self.text)])
        
        # Check if this window is currently focused
        try:
            current_window = get_app().layout.current_window
            is_currently_focused = (current_window == self.window)
        except:
            is_currently_focused = False
        
        # Define maximum line width to prevent window resizing
        max_line_width = 100  # Wider to match the new input field width
        
        # For multiline fields, handle scrolling
        if self.multiline and self.text:
            lines = self.text.split('\n')
            
            # Wrap long lines to prevent window width changes
            wrapped_lines = []
            for line in lines:
                if len(line) <= max_line_width:
                    wrapped_lines.append(line)
                else:
                    # Break long lines into chunks
                    for i in range(0, len(line), max_line_width):
                        wrapped_lines.append(line[i:i + max_line_width])
            
            lines = wrapped_lines
            
            if not is_currently_focused:
                # When not focused, show first few lines with ellipsis if needed
                window_height = getattr(self.window, 'height', None)
                if hasattr(window_height, 'preferred'):
                    max_lines = window_height.preferred
                else:
                    max_lines = 2  # Default for title/author
                
                if len(lines) > max_lines:
                    display_lines = lines[:max_lines]
                    if len(display_lines) > 0:
                        display_lines[-1] += "..."
                else:
                    display_lines = lines
                
                display_text = '\n'.join(display_lines)
                return FormattedText([("class:textarea", display_text)])
            else:
                # When focused, show scrollable view around cursor
                window_height = getattr(self.window, 'height', None)
                if hasattr(window_height, 'preferred'):
                    visible_lines = window_height.preferred
                else:
                    visible_lines = 4  # Default for abstract/notes
                
                # Find which wrapped line the cursor is on
                char_count = 0
                cursor_line = 0
                original_lines = self.text.split('\n')
                
                # Calculate cursor position considering line wrapping
                for orig_line_idx, orig_line in enumerate(original_lines):
                    if char_count + len(orig_line) >= self.cursor_position:
                        # Cursor is in this original line
                        cursor_pos_in_line = self.cursor_position - char_count
                        # Find which wrapped line this cursor position corresponds to
                        wrapped_line_offset = cursor_pos_in_line // max_line_width
                        
                        # Count how many wrapped lines came before this original line
                        wrapped_lines_before = 0
                        for prev_idx in range(orig_line_idx):
                            prev_line = original_lines[prev_idx]
                            wrapped_lines_before += max(1, (len(prev_line) + max_line_width - 1) // max_line_width)
                        
                        cursor_line = wrapped_lines_before + wrapped_line_offset
                        break
                    char_count += len(orig_line) + 1
                
                # Calculate which lines to show (scroll to show cursor)
                if len(lines) <= visible_lines:
                    # Show all lines if they fit
                    start_line = 0
                    end_line = len(lines)
                else:
                    # Show last visible_lines worth of content with cursor in the bottom portion
                    # This addresses the user's requirement to show last few lines when focus moves in
                    start_line = max(0, len(lines) - visible_lines)
                    end_line = len(lines)
                    
                    # If cursor is before the visible area, scroll to show cursor
                    if cursor_line < start_line:
                        start_line = max(0, cursor_line - 1)
                        end_line = min(len(lines), start_line + visible_lines)
                    # If cursor is after visible area, scroll to show cursor
                    elif cursor_line >= end_line:
                        end_line = min(len(lines), cursor_line + 1)
                        start_line = max(0, end_line - visible_lines)
                
                # Get the visible lines
                visible_text_lines = lines[start_line:end_line]
                
                # Calculate cursor position within visible text
                visible_text = '\n'.join(visible_text_lines)
                
                # Adjust cursor position for visible text
                if start_line > 0:
                    # Calculate how many characters are before the visible area
                    chars_before_visible = sum(len(lines[i]) + 1 for i in range(start_line))
                    adjusted_cursor_pos = self.cursor_position - chars_before_visible
                else:
                    adjusted_cursor_pos = self.cursor_position
                
                # Add cursor - for multiline, cursor should be one position after when at end
                if self.cursor_position >= len(self.text):
                    # For multiline at end: cursor should be one position after last character
                    display_text = visible_text + "█"
                    return FormattedText([("class:textarea", display_text)])
                elif adjusted_cursor_pos >= len(visible_text):
                    # Cursor is after visible area but not at end of text
                    display_text = visible_text + "█"
                    return FormattedText([("class:textarea", display_text)])
                elif adjusted_cursor_pos >= 0:
                    # Cursor is in the middle - overlap with the character at cursor position
                    before_cursor = visible_text[:adjusted_cursor_pos]
                    cursor_char = visible_text[adjusted_cursor_pos] if adjusted_cursor_pos < len(visible_text) else " "
                    after_cursor = visible_text[adjusted_cursor_pos + 1:] if adjusted_cursor_pos + 1 < len(visible_text) else ""
                    
                    return FormattedText([
                        ("class:textarea", before_cursor),
                        ("class:textarea bg:#ffffff fg:#000000", cursor_char),
                        ("class:textarea", after_cursor)
                    ])
                else:
                    return FormattedText([("class:textarea", visible_text)])
        
        # For single-line fields or empty multiline fields
        if not is_currently_focused:
            # For long single lines, truncate to prevent window width changes
            if len(self.text) > max_line_width:
                display_text = self.text[:max_line_width-3] + "..."
            else:
                display_text = self.text
            return FormattedText([("class:textarea", display_text)])
        
        # Show cursor only when focused
        text_to_display = self.text
        
        # For long single lines when focused, handle scrolling
        if not self.multiline and len(self.text) > max_line_width:
            # Calculate which part of the line to show
            if self.cursor_position < max_line_width - 10:
                # Show from beginning
                start_pos = 0
                end_pos = max_line_width
            elif self.cursor_position > len(self.text) - 10:
                # Show end
                start_pos = max(0, len(self.text) - max_line_width)
                end_pos = len(self.text)
            else:
                # Show around cursor
                start_pos = max(0, self.cursor_position - max_line_width // 2)
                end_pos = min(len(self.text), start_pos + max_line_width)
            
            text_to_display = self.text[start_pos:end_pos]
            cursor_pos_in_display = self.cursor_position - start_pos
        else:
            cursor_pos_in_display = self.cursor_position
        
        if cursor_pos_in_display >= len(text_to_display):
            # Cursor at end - add cursor marker
            display_text = text_to_display + "█"
            return FormattedText([("class:textarea", display_text)])
        else:
            # Cursor in middle - overlap with the character at cursor position
            before_cursor = text_to_display[:cursor_pos_in_display]
            cursor_char = text_to_display[cursor_pos_in_display] if cursor_pos_in_display < len(text_to_display) else " "
            after_cursor = text_to_display[cursor_pos_in_display + 1:] if cursor_pos_in_display + 1 < len(text_to_display) else ""
            
            # Show cursor overlapping the character at cursor position
            return FormattedText([
                ("class:textarea", before_cursor),
                ("class:textarea bg:#ffffff fg:#000000", cursor_char),
                ("class:textarea", after_cursor)
            ])
    
    def _setup_key_bindings(self):
        """Setup key bindings for text input."""
        kb = KeyBindings()
        
        # Handle specific navigation keys first (higher priority)
        @kb.add("left")
        def move_left(event):
            if self.cursor_position > 0:
                self.cursor_position -= 1
                get_app().invalidate()
        
        @kb.add("right")
        def move_right(event):
            if self.cursor_position < len(self.text):
                self.cursor_position += 1
                get_app().invalidate()
        
        @kb.add("up")
        def move_up(event):
            if self.multiline:
                lines = self.text.split('\n')
                if len(lines) <= 1:
                    return
                
                # Find which line we're on
                char_count = 0
                current_line_idx = 0
                current_line_pos = self.cursor_position
                
                for i, line in enumerate(lines):
                    if char_count + len(line) >= self.cursor_position:
                        current_line_idx = i
                        current_line_pos = self.cursor_position - char_count
                        break
                    char_count += len(line) + 1  # +1 for newline
                
                # Move to previous line if possible
                if current_line_idx > 0:
                    prev_line = lines[current_line_idx - 1]
                    # Calculate position in previous line
                    prev_line_pos = min(current_line_pos, len(prev_line))
                    
                    # Calculate new cursor position
                    new_pos = sum(len(lines[i]) + 1 for i in range(current_line_idx - 1)) + prev_line_pos
                    self.cursor_position = new_pos
                    
                    # Force scroll recalculation by invalidating
                    self.control.text = self._get_formatted_text
                    get_app().invalidate()
        
        @kb.add("down")
        def move_down(event):
            if self.multiline:
                lines = self.text.split('\n')
                if len(lines) <= 1:
                    return
                
                # Find which line we're on
                char_count = 0
                current_line_idx = 0
                current_line_pos = self.cursor_position
                
                for i, line in enumerate(lines):
                    if char_count + len(line) >= self.cursor_position:
                        current_line_idx = i
                        current_line_pos = self.cursor_position - char_count
                        break
                    char_count += len(line) + 1  # +1 for newline
                
                # Move to next line if possible
                if current_line_idx < len(lines) - 1:
                    next_line = lines[current_line_idx + 1]
                    # Calculate position in next line
                    next_line_pos = min(current_line_pos, len(next_line))
                    
                    # Calculate new cursor position
                    new_pos = sum(len(lines[i]) + 1 for i in range(current_line_idx + 1)) + next_line_pos
                    self.cursor_position = new_pos
                    
                    # Force scroll recalculation by invalidating
                    self.control.text = self._get_formatted_text
                    get_app().invalidate()
        
        # Handle spacebar specifically
        @kb.add(" ")
        def handle_space(event):
            self.text = self.text[:self.cursor_position] + " " + self.text[self.cursor_position:]
            self.cursor_position += 1
            get_app().invalidate()

        # Handle any other character input (lower priority than specific keys)
        @kb.add("<any>")
        def handle_character(event):
            if event.data and len(event.data) == 1:
                char = event.data
                if char.isprintable(): # Space is handled by its own binding now
                    # Insert character at cursor position
                    self.text = self.text[:self.cursor_position] + char + self.text[self.cursor_position:]
                    self.cursor_position += 1
                    get_app().invalidate()
        
        # Backspace
        @kb.add("backspace")
        def backspace(event):
            if self.cursor_position > 0:
                self.text = self.text[:self.cursor_position-1] + self.text[self.cursor_position:]
                self.cursor_position -= 1
                get_app().invalidate()
        
        # Delete
        @kb.add("delete")
        def delete(event):
            if self.cursor_position < len(self.text):
                self.text = self.text[:self.cursor_position] + self.text[self.cursor_position+1:]
                get_app().invalidate()
        
        
        # Home/End
        @kb.add("home")
        def move_home(event):
            self.cursor_position = 0
            get_app().invalidate()
        
        @kb.add("end")
        def move_end(event):
            self.cursor_position = len(self.text)
            get_app().invalidate()
        
        # Enter for multiline
        if self.multiline:
            @kb.add("enter")
            def insert_newline(event):
                self.text = self.text[:self.cursor_position] + "\n" + self.text[self.cursor_position:]
                self.cursor_position += 1
                get_app().invalidate()
        
        self.control.key_bindings = kb
    
    def focus(self):
        """Set focus to this field."""
        self.focused = True
        get_app().layout.focus(self.window)
        get_app().invalidate()
    
    def unfocus(self):
        """Remove focus from this field."""
        self.focused = False
        get_app().invalidate()


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
                
                input_field = CustomInputField(
                    initial_text=value,
                    multiline=is_multiline,
                    read_only=is_read_only,
                    field_name=field_name
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
        
        return [
            paper_type_row,
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
                field.focused = False
            
            get_app().layout.focus(self.initial_focus)
            
            # Set the corresponding input field as focused
            visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
            for field_name in visible_fields:
                if field_name in self.input_fields and not self.input_fields[field_name].read_only:
                    if self.input_fields[field_name].window == self.initial_focus:
                        self.input_fields[field_name].focused = True
                        break

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
        
        # Update focused state
        for field in self.input_fields.values():
            field.focused = (field.window == prev_window)
        
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
        
        # Don't override Tab here - let the dialog handle it naturally for now
        
        if hasattr(self.dialog.container, 'key_bindings'):
            self.dialog.container.key_bindings = merge_key_bindings([self.dialog.container.key_bindings, kb])
        else:
            self.dialog.container.key_bindings = kb

    def __pt_container__(self):
        return self.dialog