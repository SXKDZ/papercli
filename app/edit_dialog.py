"""
Custom dialog for editing paper metadata in a full-window form with paper type buttons.
"""

from typing import Callable, Dict, Any, List, Optional

from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout import ScrollablePane
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Button, Dialog, Frame, TextArea
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.application import get_app

from .models import Paper
from .services import CollectionService, AuthorService


class EditDialog:
    """A full-window dialog for editing paper metadata with paper type buttons."""

    def __init__(self, paper_data: Dict[str, Any], callback: Callable, read_only_fields: List[str] = None):
        self.paper_data = paper_data
        self.callback = callback
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
        self.text_areas = {}
        self._create_layout()
        self._add_key_bindings()

    def _create_text_areas(self):
        """Create text areas for fields visible in the current paper type."""
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        self.text_areas = {}

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
                style = "class:textarea.readonly" if is_read_only else "class:textarea"
                
                text_area = TextArea(
                    text=value, multiline=field_name in ["abstract", "notes"],
                    focusable=not is_read_only, read_only=is_read_only, style=style,
                    height=Dimension(preferred=3, max=6) if field_name in ["abstract", "notes"] else Dimension(preferred=1, max=1)
                )
                self.text_areas[field_name] = text_area

    def _build_body_components(self):
        """Builds the UI components for the dialog body."""
        self._create_text_areas()

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
            if field_name in self.text_areas:
                label_text = field_name.replace("_", " ").title()
                field_container = VSplit([
                    Window(content=FormattedTextControl(f"{label_text}:"), width=16, style="class:dialog.label"),
                    self.text_areas[field_name]
                ])
                all_field_containers.append(field_container)
        
        fields_content = HSplit(all_field_containers, padding=1)
        fields_layout = ScrollablePane(content=fields_content, show_scrollbar=True, keep_cursor_visible=True)
        
        return [
            Window(content=FormattedTextControl("Paper Type:"), style="class:dialog.label", height=1),
            type_buttons_row,
            Window(height=1),
            fields_layout,
        ]

    def _create_layout(self):
        """Creates the dialog layout upon initialization."""
        body_components = self._build_body_components()
        self.body_container = HSplit(body_components, padding=1)
        
        self.dialog = Dialog(
            title="Edit Paper Metadata",
            body=self.body_container,
            buttons=[Button(text="Save", handler=self._handle_save), Button(text="Cancel", handler=self._handle_cancel)],
            with_background=True, modal=True,
        )
        self._set_initial_focus()

    def _set_paper_type(self, paper_type: str):
        """Sets the paper type and rebuilds the dialog body."""
        current_values = {name: ta.text for name, ta in self.text_areas.items()}
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
        for field_name, text_area in self.text_areas.items():
            if field_name in self.read_only_fields:
                continue
            
            value = text_area.text.strip()
            if field_name == "author_names":
                names = [name.strip() for name in value.split(",") if name.strip()]
                result["authors"] = [self.author_service.get_or_create_author(name) for name in names]
            elif field_name == "collections":
                names = [name.strip() for name in value.split(",") if name.strip()]
                result["collections"] = [self.collection_service.get_or_create_collection(name) for name in names]
            elif field_name == "year":
                result["year"] = int(value) if value.isdigit() else None
            else:
                result[field_name] = value if value else None
        
        self.result = result
        self.callback(self.result)

    def _handle_cancel(self):
        self.callback(None)

    def _set_initial_focus(self):
        """Sets the initial focus to the first editable field."""
        visible_fields = self.fields_by_type.get(self.current_paper_type, self.fields_by_type["other"])
        for field_name in visible_fields:
            if field_name in self.text_areas and not self.text_areas[field_name].read_only:
                self.initial_focus = self.text_areas[field_name]
                return
        self.initial_focus = self.dialog.buttons[0]

    def _focus_first_visible_field(self):
        """Focuses the first editable field in the dialog."""
        self._set_initial_focus()
        if self.initial_focus:
            get_app().layout.focus(self.initial_focus)

    def get_initial_focus(self):
        return getattr(self, 'initial_focus', None)

    def _add_key_bindings(self):
        kb = KeyBindings()
        @kb.add("c-s")
        def _(event): self._handle_save()
        @kb.add("escape")
        def _(event): self._handle_cancel()
        
        if hasattr(self.dialog.container, 'key_bindings'):
            self.dialog.container.key_bindings = merge_key_bindings([self.dialog.container.key_bindings, kb])
        else:
            self.dialog.container.key_bindings = kb

    def __pt_container__(self):
        return self.dialog