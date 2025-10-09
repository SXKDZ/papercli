import os
import traceback
from typing import Any, Callable, Dict, List

from pluralizer import Pluralizer
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TextArea,
)

from ng.services import (
    BackgroundOperationService,
    CollectionService,
    MetadataExtractor,
    PDFManager,
    normalize_paper_data,
)
from ng.services.pdf import PDFExtractionHandler


class EditDialog(ModalScreen):
    """A floating modal dialog for editing paper metadata with field visibility based on paper type."""

    DEFAULT_CSS = """
    EditDialog {
        align: center middle;
        layer: dialog;
    }
    EditDialog > Container {
        width: 80%;
        height: auto;
        max-height: 90%;
        min-height: 50%;
        border: solid $accent;
        background: $panel;
    }
    EditDialog.compact > Container {
        max-height: 70%;
        min-height: 40%;
    }
    EditDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    EditDialog .paper-type-section {
        height: auto;
        margin: 0 0 1 2;
        align: left top;
    }
    EditDialog .paper-type-label {
        text-style: bold;
        width: 15;
        margin: 0 1 0 0;
        text-align: right;
        height: 3;
        content-align: center middle;
    }
    EditDialog #paper-type-radio-set {
        margin: 0 1 0 0;
        padding: 0 1;
        height: 3;
        border: solid $border;
    }
    EditDialog .form-fields,
    EditDialog .form-fields-compact {
        height: 1fr;
        margin: 0 1;
        scrollbar-size: 2 2;
        scrollbar-background: $surface;
        scrollbar-color: $primary;
        overflow-y: auto;
        border: solid $border;
    }
    EditDialog .form-fields {
        max-height: 50;
    }
    EditDialog .form-fields-compact {
        max-height: 35;
    }
    EditDialog .form-row {
        height: auto;
        margin: 0 0 1 0;
    }
    EditDialog #content-switcher > Container {
        padding: 0 1 0 0;
    }
    EditDialog .paper-content-standard {
        min-height: 37;
    }
    EditDialog .paper-content-extended {
        min-height: 39;
    }
    EditDialog .paper-content-compact {
        min-height: 29;
    }
    EditDialog .paper-content-full {
        min-height: 45;
    }
    EditDialog .field-label {
        width: 15;
        margin: 0 1 0 0;
        text-align: right;
    }
    EditDialog .field-input {
        width: 1fr;
        padding: 0 0 0 1;
    }
    EditDialog .single-line-input,
    EditDialog .single-line-input:focus {
        height: 1;
        border: none;
    }
    EditDialog .multiline-input,
    EditDialog .multiline-input:focus {
        height: 8;
        border: none;
    }
    EditDialog .changed-field {
        text-style: italic;
    }
    EditDialog .button-row {
        height: 3;
        align: center middle;
        padding: 0;
        margin: 1;
    }
    EditDialog .button-row Button {
        height: 3;
        margin: 0 1;
    }
    EditDialog RadioSet {
        height: 3;
        layout: horizontal;
        border: solid $border;
    }
    EditDialog RadioButton,
    EditDialog RadioButton:focus {
        margin: 0 1 0 0;
        height: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+e", "extract_pdf", "Extract PDF"),
        ("ctrl+l", "summarize", "Summarize"),
    ]

    # Paper type definitions matching original
    paper_types = {
        "Conference": "conference",
        "Journal": "journal",
        "Workshop": "workshop",
        "Preprint": "preprint",
        "Website": "website",
        "Other": "other",
    }

    # Field visibility by paper type (matching original exactly)
    fields_by_type = {
        "conference": [
            "title",
            "author_names",
            "venue_full",
            "venue_acronym",
            "year",
            "pages",
            "doi",
            "url",
            "pdf_path",
            "collections",
            "abstract",
            "notes",
        ],
        "journal": [
            "title",
            "author_names",
            "venue_full",
            "venue_acronym",
            "year",
            "volume",
            "issue",
            "pages",
            "doi",
            "pdf_path",
            "collections",
            "abstract",
            "notes",
        ],
        "workshop": [
            "title",
            "author_names",
            "venue_full",
            "venue_acronym",
            "year",
            "pages",
            "doi",
            "url",
            "pdf_path",
            "collections",
            "abstract",
            "notes",
        ],
        "preprint": [
            "title",
            "author_names",
            "venue_full",
            "year",
            "preprint_id",
            "category",
            "doi",
            "url",
            "pdf_path",
            "collections",
            "abstract",
            "notes",
        ],
        "website": [
            "title",
            "author_names",
            "year",
            "url",
            "html_snapshot_path",
            "collections",
            "abstract",
            "notes",
        ],
        "other": [
            "title",
            "author_names",
            "venue_full",
            "venue_acronym",
            "year",
            "volume",
            "issue",
            "pages",
            "doi",
            "preprint_id",
            "category",
            "url",
            "pdf_path",
            "collections",
            "abstract",
            "notes",
        ],
    }

    current_paper_type = reactive("conference")
    changed_fields = reactive(set())
    dialog_height = reactive("90%")
    show_snapshot_button = reactive(False)

    def __init__(
        self,
        paper_data: Dict[str, Any],
        callback: Callable[[Dict[str, Any] | None], None],
        error_display_callback: Callable = None,
        read_only_fields: List[str] = None,
        app=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.paper_data = paper_data
        self.callback = callback
        self.error_display_callback = error_display_callback
        self.read_only_fields = read_only_fields or []
        self.parent_app = app
        self._pluralizer = Pluralizer()

        if self.parent_app:
            self.background_service = BackgroundOperationService(app=self.parent_app)

        self.collection_service = CollectionService()
        self.pdf_manager = PDFManager(self.parent_app)

        self.input_widgets: Dict[str, Input | TextArea] = {}
        self.current_paper_type = paper_data.get("paper_type", "conference")
        self.changed_fields = set()

    def _get_field_count_for_type(self, paper_type: str) -> int:
        """Get the number of fields for a given paper type."""
        return len(self.fields_by_type.get(paper_type, []))

    def _get_form_fields_class(self, paper_type: str) -> str:
        """Get the appropriate CSS class for form fields based on field count."""
        field_count = self._get_field_count_for_type(paper_type)
        # Website type has 8 fields, which is significantly fewer than others (12-14)
        if field_count <= 8:
            return "form-fields-compact"
        return "form-fields"

    def _get_content_height_class(self, paper_type: str) -> str:
        """Get the appropriate CSS class for content min-height based on field configuration."""
        field_count = self._get_field_count_for_type(paper_type)

        # Calculate expected height: single-line fields = 2 lines each, multi-line = 9 lines each
        # All types have 2 multi-line fields (abstract, notes) = 18 lines
        # Remaining are single-line = (field_count - 2) * 2 lines
        # Total = 18 + (field_count - 2) * 2 - 1 (last margin)
        expected_height = 18 + (field_count - 2) * 2 - 1

        if field_count == 8:  # website
            return "paper-content-compact"  # 29 lines
        elif field_count == 13:  # journal
            return "paper-content-extended"  # 39 lines
        elif field_count == 16:  # other
            return "paper-content-full"  # 45 lines
        else:  # conference, workshop, preprint (12 fields)
            return "paper-content-standard"  # 37 lines

    def _get_full_pdf_path(self):
        """Get the full absolute path for the PDF file."""
        pdf_path = self.paper_data.get("pdf_path", "")
        if not pdf_path:
            return ""
        return self.pdf_manager.get_absolute_path(pdf_path)

    def _get_full_html_snapshot_path(self):
        """Get the full absolute path for the HTML snapshot file."""
        html_path = self.paper_data.get("html_snapshot_path", "")
        if not html_path:
            return ""
        # HTML snapshots are stored in html_snapshots folder
        import os
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = os.path.dirname(db_manager.db_path)
        html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
        return os.path.join(html_snapshot_dir, html_path)

    def _process_pdf_path(self, pdf_path: str) -> str:
        """Process PDF path: copy file if needed and return relative path for database."""
        if not pdf_path or not pdf_path.strip():
            return ""

        pdf_path = pdf_path.strip()

        # If it's already a relative path, check if it exists and return as-is
        if not os.path.isabs(pdf_path):
            # Check if file exists in pdfs directory
            abs_path = self.pdf_manager.get_absolute_path(pdf_path)
            if os.path.exists(abs_path):
                return pdf_path  # Return the relative path as-is
            else:
                return pdf_path  # Still return it, might be created later

        # Use the PDFManager's process_pdf_path method for proper handling
        try:
            # Build paper data for the PDF manager
            authors = self.paper_data.get("authors", [])
            if isinstance(authors, list):
                author_names = [getattr(a, "full_name", str(a)) for a in authors]
            else:
                author_names = [str(authors)] if authors else []

            paper_data_for_pdf = {
                "title": self.paper_data.get("title", ""),
                "authors": author_names,
                "year": self.paper_data.get("year", ""),
            }

            # Get the old PDF path for cleanup
            old_pdf_path = self.paper_data.get("pdf_path", "")
            if old_pdf_path:
                old_pdf_path = self.pdf_manager.get_absolute_path(old_pdf_path)

            # Process the PDF path using the PDFManager
            relative_path, error = self.pdf_manager.process_pdf_path(
                pdf_path, paper_data_for_pdf, old_pdf_path
            )

            if error:
                # Return the original path converted to relative as fallback
                return self.pdf_manager.get_relative_path(pdf_path)

            return relative_path

        except Exception as e:
            # Fallback: return relative path of original
            return self.pdf_manager.get_relative_path(pdf_path)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Edit Paper Metadata", classes="dialog-title")

            with Horizontal(classes="paper-type-section"):
                yield Label("Paper Type:", classes="paper-type-label")
                with RadioSet(id="paper-type-radio-set"):
                    for display_name, type_value in self.paper_types.items():
                        yield RadioButton(
                            display_name,
                            value=type_value == self.current_paper_type,
                            id=f"type-{type_value}",
                        )

            with VerticalScroll(
                classes=self._get_form_fields_class(self.current_paper_type),
                id="form-fields",
            ):
                with ContentSwitcher(
                    initial=self.current_paper_type, id="content-switcher"
                ):
                    for paper_type in self.paper_types.values():
                        content_class = self._get_content_height_class(paper_type)
                        with Container(id=paper_type, classes=content_class):
                            pass  # Will be populated in on_mount

            with Horizontal(classes="button-row"):
                yield Button("Extract", id="extract-button", variant="default")
                yield Button("Summarize", id="summarize-button", variant="default")
                yield Button("Snapshot", id="snapshot-button", variant="default")
                yield Button("Save", id="save-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the dialog on mount."""
        # Create all fields for all paper types
        self._create_all_paper_type_containers()

        # Set initial compact class if needed
        if (
            self._get_form_fields_class(self.current_paper_type)
            == "form-fields-compact"
        ):
            self.add_class("compact")

        # Set initial paper type selection
        radio_set = self.query_one("#paper-type-radio-set", RadioSet)

        # First clear all selections
        for button in radio_set.query(RadioButton):
            button.value = False

        # Then set the correct one
        try:
            target_button = radio_set.query_one(
                f"#type-{self.current_paper_type}", RadioButton
            )
            target_button.value = True

            # Force the RadioSet to recognize this selection
            radio_set._pressed = target_button

        except Exception as e:
            # Fallback: select the first button
            buttons = radio_set.query(RadioButton)
            if buttons:
                buttons[0].value = True
                radio_set._pressed = buttons[0]

        # Set initial content switcher state
        content_switcher = self.query_one("#content-switcher", ContentSwitcher)
        content_switcher.current = self.current_paper_type

        # Set initial snapshot button visibility
        self.show_snapshot_button = self.current_paper_type == "website"
        self._update_snapshot_button_visibility()

    def _update_snapshot_button_visibility(self):
        """Update snapshot button visibility based on paper type."""
        try:
            snapshot_button = self.query_one("#snapshot-button", Button)
            snapshot_button.display = self.show_snapshot_button
        except Exception:
            # Button not yet available
            pass

    def watch_current_paper_type(self, new_type: str) -> None:
        """Update snapshot button visibility when paper type changes."""
        self.show_snapshot_button = new_type == "website"
        self._update_snapshot_button_visibility()

    def _create_all_paper_type_containers(self):
        """Create field containers for each paper type with their specific fields."""
        # Get all field values from paper data
        authors = self.paper_data.get("authors", [])
        if isinstance(authors, list):
            author_names = ", ".join([getattr(a, "full_name", str(a)) for a in authors])
        else:
            author_names = str(authors) if authors else ""

        collections = self.paper_data.get("collections", [])
        if isinstance(collections, list):
            collection_names = ", ".join(
                [getattr(c, "name", str(c)) for c in collections]
            )
        else:
            collection_names = str(collections) if collections else ""

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
            "preprint_id": self.paper_data.get("preprint_id", ""),
            "category": self.paper_data.get("category", ""),
            "url": self.paper_data.get("url", ""),
            "pdf_path": self._get_full_pdf_path(),
            "html_snapshot_path": self._get_full_html_snapshot_path(),
            "collections": collection_names,
            "abstract": self.paper_data.get("abstract", ""),
            "notes": self.paper_data.get("notes", ""),
        }

        # Custom label mappings
        label_mappings = {
            "doi": "DOI",
            "pdf_path": "PDF Path",
            "html_snapshot_path": "HTML Path",
            "url": "URL",
            "venue_acronym": "Venue Acronym",
            "author_names": "Authors",
        }

        # Create containers for each paper type
        for paper_type, visible_fields in self.fields_by_type.items():
            container = self.query_one(f"#{paper_type}", Container)

            for field_name in visible_fields:
                if field_name in all_field_values:
                    value = all_field_values[field_name]
                    is_read_only = field_name in self.read_only_fields
                    safe_value = str(value) if value is not None else ""

                    # Create the widget
                    if field_name in ["notes"]:
                        widget = TextArea(
                            text=safe_value,
                            id=f"input-{field_name}-{paper_type}",
                            read_only=is_read_only,
                            classes="field-input multiline-input",
                        )
                    elif field_name in ["abstract"]:
                        widget = TextArea(
                            text=safe_value,
                            id=f"input-{field_name}-{paper_type}",
                            read_only=is_read_only,
                            classes="field-input multiline-input",
                        )
                    else:
                        widget = Input(
                            value=safe_value,
                            id=f"input-{field_name}-{paper_type}",
                            disabled=is_read_only,
                            classes="field-input single-line-input",
                        )

                    # Store widget reference with paper type suffix for later access
                    widget_key = f"{field_name}_{paper_type}"
                    self.input_widgets[widget_key] = widget

                    # Get label text
                    if field_name == "preprint_id":
                        label_text = "ID" if paper_type == "preprint" else "Preprint ID"
                    elif field_name == "venue_full":
                        label_text = (
                            "Website" if paper_type == "preprint" else "Venue Full"
                        )
                    else:
                        label_text = label_mappings.get(
                            field_name, field_name.replace("_", " ").title()
                        )

                    # Create row with label and widget
                    row = Horizontal(
                        Label(f"{label_text}:", classes="field-label"),
                        widget,
                        classes="form-row",
                    )

                    container.mount(row)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle paper type change."""
        if event.radio_set.id == "paper-type-radio-set" and event.pressed:
            new_type = event.pressed.id.replace("type-", "")

            if new_type != self.current_paper_type:
                old_type = self.current_paper_type
                self.current_paper_type = new_type

                # Switch to the new paper type content
                content_switcher = self.query_one("#content-switcher", ContentSwitcher)
                content_switcher.current = new_type

                # Update form fields CSS class for dynamic height
                form_fields = self.query_one("#form-fields", VerticalScroll)
                old_class = self._get_form_fields_class(old_type)
                new_class = self._get_form_fields_class(new_type)
                if old_class != new_class:
                    form_fields.remove_class(old_class)
                    form_fields.add_class(new_class)

                    # Also update dialog compact class
                    if new_class == "form-fields-compact":
                        self.add_class("compact")
                    else:
                        self.remove_class("compact")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-button":
            self.action_save()
        elif event.button.id == "cancel-button":
            self.action_cancel()
        elif event.button.id == "extract-button":
            self.action_extract_pdf()
        elif event.button.id == "summarize-button":
            self.action_summarize()
        elif event.button.id == "snapshot-button":
            self.action_refresh_snapshot()

    def action_save(self) -> None:
        """Handle save action."""
        result = {"paper_type": self.current_paper_type}
        changes_made = []

        # Get the current paper type's visible fields
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )

        for field_name in visible_fields:
            if field_name in self.read_only_fields:
                continue

            # Get the widget for the current paper type
            widget_key = f"{field_name}_{self.current_paper_type}"
            if widget_key not in self.input_widgets:
                continue

            input_widget = self.input_widgets[widget_key]

            if isinstance(input_widget, TextArea):
                new_value = input_widget.text.strip()
            else:
                new_value = input_widget.value.strip()

            # Apply centralized normalization for all fields
            if new_value:
                temp_data = {field_name: new_value}
                normalized_data = normalize_paper_data(temp_data)
                new_value = normalized_data.get(field_name, new_value)

            # Get the original value
            if field_name == "author_names":
                authors = self.paper_data.get("authors", [])
                if isinstance(authors, list):
                    old_value = ", ".join(
                        [getattr(a, "full_name", str(a)) for a in authors]
                    )
                else:
                    old_value = str(authors) if authors else ""
            elif field_name == "collections":
                collections = self.paper_data.get("collections", [])
                if isinstance(collections, list):
                    old_value = ", ".join(
                        [getattr(c, "name", str(c)) for c in collections]
                    )
                else:
                    old_value = str(collections) if collections else ""
            else:
                old_value = self.paper_data.get(field_name, "")
                old_value = str(old_value) if old_value is not None else ""

            # Compare values
            if old_value != new_value:
                changes_made.append(f"{field_name} from '{old_value}' to '{new_value}'")

            # Process field values for result
            if field_name == "author_names":
                names = [name.strip() for name in new_value.split(",") if name.strip()]
                result["authors"] = names
            elif field_name == "collections":
                names = [name.strip() for name in new_value.split(",") if name.strip()]
                try:
                    result["collections"] = [
                        self.collection_service.get_or_create_collection(name)
                        for name in names
                    ]
                except Exception as e:
                    if self.parent_app:
                        error_details = f"Error processing collections: {str(e)}\nFull traceback:\n{traceback.format_exc()}"
                    # Fallback: just store the names as strings
                    result["collection_names"] = new_value
            elif field_name == "year":
                result["year"] = int(new_value) if new_value.isdigit() else None
            elif field_name == "pdf_path":
                # Special handling for PDF path
                result["pdf_path"] = (
                    self._process_pdf_path(new_value) if new_value else None
                )
            else:
                result[field_name] = new_value if new_value else None

        # Clear changed fields when saving
        self.changed_fields.clear()

        if self.callback:
            try:
                callback_result = self.callback(result)
                # If callback returns None when result is not None, paper may have been deleted
                if callback_result is None and result is not None:
                    # Paper was deleted or failed to update, close dialog silently
                    self.dismiss(None)
                    return
            except Exception as e:
                # Handle any errors from callback
                if self.parent_app:
                    error_details = f"Error saving paper: {str(e)}\nFull traceback:\n{traceback.format_exc()}"
                    self.parent_app.notify(f"Error saving paper: {e}", severity="error")
                return
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Handle cancel action."""
        self.changed_fields.clear()
        if self.callback:
            self.callback(None)
        self.dismiss(None)

    def action_extract_pdf(self) -> None:
        """Handle Extract action - from PDF or HTML depending on paper type."""
        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        # For website papers, extract from HTML
        if self.current_paper_type == "website":
            html_path = self.paper_data.get("html_snapshot_path")
            if not html_path:
                self.error_display_callback(
                    "Extract Error",
                    "No HTML snapshot file path specified for this paper.",
                )
                return

            # Get absolute path
            from ng.db.database import get_db_manager

            db_manager = get_db_manager()
            data_dir = os.path.dirname(db_manager.db_path)
            html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
            html_absolute_path = os.path.join(html_snapshot_dir, html_path)

            if not os.path.exists(html_absolute_path):
                self.error_display_callback(
                    "Extract Error",
                    f"HTML snapshot file not found: {html_absolute_path}",
                )
                return

            # Get URL from form
            url_widget_key = f"url_{self.current_paper_type}"
            url = ""
            if url_widget_key in self.input_widgets:
                url = self.input_widgets[url_widget_key].value.strip()

            def extract_from_html_operation():
                """Extract metadata from HTML snapshot."""
                # Read HTML content
                with open(html_absolute_path, "r", encoding="utf-8") as f:
                    html_content = f.read()

                # Extract metadata
                metadata_extractor = MetadataExtractor(
                    pdf_manager=self.pdf_manager, app=self.parent_app
                )
                metadata = metadata_extractor.extract_from_webpage(
                    url or "unknown", html_content
                )
                return metadata

            def on_extraction_success(extracted_data):
                if not extracted_data:
                    if self.parent_app:
                        self.parent_app.notify(
                            "No metadata extracted from HTML",
                            severity="warning",
                        )
                    return

                changes = self._compare_extracted_with_current_form(extracted_data)
                if not changes:
                    if self.parent_app:
                        self.parent_app.notify(
                            "No changes found: extracted metadata matches current values",
                            severity="information",
                        )
                    return
                self._update_fields_with_extracted_data(extracted_data)

            def on_extract_complete(result, error):
                if error:
                    if self.parent_app:
                        self.parent_app.notify(
                            f"Failed to extract metadata: {error}", severity="error"
                        )
                    return
                on_extraction_success(result)

            if self.background_service:
                self.background_service.run_operation(
                    operation_func=extract_from_html_operation,
                    operation_name=f"edit_extract_{paper_id}",
                    initial_message=f"Extracting metadata from HTML for '{title}'...",
                    on_complete=on_extract_complete,
                )
            else:
                # Fallback: run synchronously
                try:
                    extracted_data = extract_from_html_operation()
                    on_extract_complete(extracted_data, None)
                except Exception as e:
                    on_extract_complete(None, str(e))

            return

        # For non-website papers, extract from PDF
        pdf_path = self.paper_data.get("pdf_path")
        if not pdf_path:
            self.error_display_callback(
                "Extract PDF Error",
                "No PDF file path specified for this paper.",
            )
            return

        original_path = pdf_path
        pdf_path = self.pdf_manager.get_absolute_path(pdf_path)

        if not os.path.exists(pdf_path):
            self.error_display_callback(
                "Extract PDF Error",
                f"PDF file not found. Original path: '{original_path}', Resolved path: '{pdf_path}'. Please ensure the file exists.",
            )
            return

        # Use extraction handler to manage the operation
        extraction_handler = PDFExtractionHandler(self.parent_app, self.pdf_manager)

        def on_extraction_success(extracted_data):
            changes = self._compare_extracted_with_current_form(extracted_data)
            if not changes:
                if self.parent_app:
                    self.parent_app.notify(
                        "No changes found: extracted metadata matches current values",
                        severity="information",
                    )
                return
            self._update_fields_with_extracted_data(extracted_data)

        extract_operation = extraction_handler.create_extraction_task(pdf_path)
        on_extract_complete = extraction_handler.create_extraction_completion_callback(
            on_extraction_success
        )

        if self.background_service:
            self.background_service.run_operation(
                operation_func=extract_operation,
                operation_name=f"edit_extract_{paper_id}",
                initial_message=f"Extracting metadata from PDF for '{title}'...",
                on_complete=on_extract_complete,
            )
        else:
            # Fallback: run synchronously
            try:
                extracted_data = extract_operation()
                on_extract_complete(extracted_data, None)
            except Exception as e:
                on_extract_complete(None, str(e))

    def action_summarize(self) -> None:
        """Handle Summarize action - from PDF or HTML depending on paper type."""
        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        # For website papers, summarize from HTML
        if self.current_paper_type == "website":
            html_path = self.paper_data.get("html_snapshot_path")
            if not html_path:
                self.error_display_callback(
                    "Summarize Error",
                    "No HTML snapshot file path specified for this paper.",
                )
                return

            # Get absolute path
            from ng.db.database import get_db_manager

            db_manager = get_db_manager()
            data_dir = os.path.dirname(db_manager.db_path)
            html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
            html_absolute_path = os.path.join(html_snapshot_dir, html_path)

            if not os.path.exists(html_absolute_path):
                self.error_display_callback(
                    "Summarize Error",
                    f"HTML snapshot file not found: {html_absolute_path}",
                )
                return

            def generate_summary_from_html_operation():
                """Generate summary from HTML using metadata service."""
                extractor = MetadataExtractor(
                    pdf_manager=self.pdf_manager, app=self.parent_app
                )
                summary = extractor.generate_webpage_summary(html_path)
                if not summary:
                    raise Exception("Failed to generate summary - empty response")
                return {"summary": summary}

            def on_summary_complete(result, error):
                if error:
                    if self.parent_app:
                        self.parent_app.notify(
                            f"Failed to generate summary: {error}", severity="error"
                        )
                    return

                if not result:
                    if self.parent_app:
                        self.parent_app.notify("No summary generated", severity="error")
                    return

                summary = result["summary"]
                notes_widget_key = f"notes_{self.current_paper_type}"
                if summary and notes_widget_key in self.input_widgets:
                    notes_widget = self.input_widgets[notes_widget_key]
                    current_notes = (
                        notes_widget.text
                        if hasattr(notes_widget, "text")
                        else notes_widget.value
                    )
                    if current_notes.strip() != summary.strip():
                        if hasattr(notes_widget, "text"):
                            notes_widget.text = summary
                        else:
                            notes_widget.value = summary
                        self.changed_fields.add("notes")
                        self._update_field_styling()
                        if self.parent_app:
                            self.parent_app.notify(
                                "Summary generated and applied to notes field",
                                severity="information",
                            )
                    else:
                        if self.parent_app:
                            self.parent_app.notify(
                                "Summary matches existing notes - no changes made",
                                severity="information",
                            )
                else:
                    if self.parent_app:
                        self.parent_app.notify(
                            "Failed to generate summary or notes field not available",
                            severity="error",
                        )

            if self.background_service:
                self.background_service.run_operation(
                    operation_func=generate_summary_from_html_operation,
                    operation_name=f"edit_summary_{paper_id}",
                    initial_message=f"Generating summary from HTML for '{title}'...",
                    on_complete=on_summary_complete,
                )
            else:
                # Fallback: run synchronously
                try:
                    result = generate_summary_from_html_operation()
                    on_summary_complete(result, None)
                except Exception as e:
                    on_summary_complete(None, str(e))

            return

        # For non-website papers, summarize from PDF
        pdf_path = self.paper_data.get("pdf_path")
        if not pdf_path:
            self.error_display_callback(
                "Summarize Error",
                "No PDF file path specified for this paper.",
            )
            return

        original_path = pdf_path
        pdf_path = self.pdf_manager.get_absolute_path(pdf_path)

        if not os.path.exists(pdf_path):
            self.error_display_callback(
                "Summarize Error",
                f"PDF file not found. Original path: '{original_path}', Resolved path: '{pdf_path}'. Please ensure the file exists.",
            )
            return

        def generate_summary_operation():
            extractor = MetadataExtractor(
                pdf_manager=self.pdf_manager, app=self.parent_app
            )
            summary = extractor.generate_paper_summary(pdf_path)
            if not summary:
                raise Exception("Failed to generate summary - empty response")
            return {"summary": summary}

        def on_summary_complete(result, error):
            if error:
                if self.parent_app:
                    self.parent_app.notify(
                        f"Failed to generate summary: {error}", severity="error"
                    )
                return

            if not result:
                if self.parent_app:
                    self.parent_app.notify("No summary generated", severity="error")
                return

            summary = result["summary"]
            # Get notes widget with current paper type suffix
            notes_widget_key = f"notes_{self.current_paper_type}"
            if summary and notes_widget_key in self.input_widgets:
                notes_widget = self.input_widgets[notes_widget_key]
                current_notes = (
                    notes_widget.text
                    if hasattr(notes_widget, "text")
                    else notes_widget.value
                )
                if current_notes.strip() != summary.strip():
                    if hasattr(notes_widget, "text"):
                        notes_widget.text = summary
                    else:
                        notes_widget.value = summary
                    self.changed_fields.add("notes")
                    self._update_field_styling()  # Refresh to show italic styling
                    if self.parent_app:
                        self.parent_app.notify(
                            "Summary generated and applied to notes field",
                            severity="information",
                        )
                else:
                    if self.parent_app:
                        self.parent_app.notify(
                            "Summary matches existing notes - no changes made",
                            severity="information",
                        )
            else:
                if self.parent_app:
                    self.parent_app.notify(
                        "Failed to generate summary or notes field not available",
                        severity="error",
                    )

        if self.background_service:
            self.background_service.run_operation(
                operation_func=generate_summary_operation,
                operation_name=f"edit_summary_{paper_id}",
                initial_message=f"Generating summary for '{title}'...",
                on_complete=on_summary_complete,
            )
        else:
            # Fallback: run synchronously
            try:
                result = generate_summary_operation()
                on_summary_complete(result, None)
            except Exception as e:
                on_summary_complete(None, str(e))

    def action_refresh_snapshot(self) -> None:
        """Handle Refresh Snapshot action for website papers."""
        if self.current_paper_type != "website":
            if self.parent_app:
                self.parent_app.notify(
                    "Snapshot refresh is only available for website papers",
                    severity="warning",
                )
            return

        # Get the current URL from the form
        url_widget_key = f"url_{self.current_paper_type}"
        if url_widget_key not in self.input_widgets:
            if self.parent_app:
                self.parent_app.notify("URL field not found", severity="error")
            return

        url_widget = self.input_widgets[url_widget_key]
        url = url_widget.value.strip()

        if not url:
            if self.parent_app:
                self.parent_app.notify(
                    "Please enter a URL before refreshing snapshot",
                    severity="warning",
                )
            return

        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        def refresh_snapshot_operation():
            """Refresh the webpage snapshot."""
            from ng.services.webpage import WebpageSnapshotService
            from ng.services.pdf import get_pdf_directory
            import os

            # Get directories
            pdf_dir = get_pdf_directory()
            data_dir = os.path.dirname(pdf_dir)
            html_snapshot_dir = os.path.join(data_dir, "html_snapshots")

            # Get initial title for filename
            import requests
            from bs4 import BeautifulSoup

            try:
                response = requests.get(url, timeout=30)
                soup = BeautifulSoup(response.content, "html.parser")
                title_tag = soup.find("title")
                initial_title = (
                    title_tag.get_text(strip=True) if title_tag else "webpage"
                )
            except Exception:
                initial_title = title or "webpage"

            # Create snapshot
            webpage_service = WebpageSnapshotService(app=self.parent_app)
            html_path, html_content = webpage_service.snapshot_webpage(
                url=url,
                title=initial_title,
                html_output_dir=html_snapshot_dir,
            )

            # Extract metadata
            metadata_extractor = MetadataExtractor(
                pdf_manager=self.pdf_manager, app=self.parent_app
            )
            metadata = metadata_extractor.extract_from_webpage(url, html_content)

            # Convert to relative path
            relative_html_path = os.path.relpath(html_path, html_snapshot_dir)

            return {
                "html_snapshot_path": relative_html_path,
                "html_absolute_path": html_path,
                "metadata": metadata,
            }

        def on_snapshot_complete(result, error):
            """Handle snapshot completion."""
            if error:
                if self.parent_app:
                    self.parent_app.notify(
                        f"Failed to refresh snapshot: {error}", severity="error"
                    )
                return

            if not result:
                if self.parent_app:
                    self.parent_app.notify("No snapshot created", severity="error")
                return

            # Update the html_snapshot_path field
            html_path_widget_key = f"html_snapshot_path_{self.current_paper_type}"
            if html_path_widget_key in self.input_widgets:
                html_path_widget = self.input_widgets[html_path_widget_key]
                html_path_widget.value = result["html_absolute_path"]
                self.changed_fields.add("html_snapshot_path")

            # Update metadata fields if extracted
            metadata = result.get("metadata", {})
            if metadata:
                self._update_fields_with_extracted_data(metadata)

            self._update_field_styling()

            if self.parent_app:
                self.parent_app.notify(
                    "Snapshot refreshed successfully", severity="information"
                )

        if self.background_service:
            self.background_service.run_operation(
                operation_func=refresh_snapshot_operation,
                operation_name=f"edit_snapshot_{paper_id}",
                initial_message=f"Refreshing snapshot for '{title}'...",
                on_complete=on_snapshot_complete,
            )
        else:
            # Fallback: run synchronously
            try:
                result = refresh_snapshot_operation()
                on_snapshot_complete(result, None)
            except Exception as e:
                on_snapshot_complete(None, str(e))

    def _update_fields_with_extracted_data(self, extracted_data):
        """Update form fields with extracted PDF data."""
        field_mapping = {
            "title": "title",
            "authors": "author_names",
            "abstract": "abstract",
            "year": "year",
            "venue_full": "venue_full",
            "venue_acronym": "venue_acronym",
            "doi": "doi",
            "url": "url",
            "category": "category",
            "paper_type": "paper_type",
        }

        updated_fields = []

        for extracted_field, form_field in field_mapping.items():
            if extracted_field in extracted_data:
                value = extracted_data[extracted_field]

                if not value and extracted_field not in ["paper_type"]:
                    continue

                if extracted_field == "authors" and isinstance(value, list):
                    value = ", ".join(value)
                elif extracted_field == "year" and isinstance(value, int):
                    value = str(value)
                elif extracted_field == "paper_type":
                    if value != self.current_paper_type:
                        old_paper_type = self.current_paper_type
                        self.current_paper_type = value
                        updated_fields.append(form_field)
                        # Update radio buttons
                        try:
                            radio_set = self.query_one(
                                "#paper-type-radio-set", RadioSet
                            )
                            for button in radio_set.query(RadioButton):
                                button.value = button.id == f"type-{value}"
                        except Exception:
                            pass
                        # Switch to new paper type content
                        content_switcher = self.query_one(
                            "#content-switcher", ContentSwitcher
                        )
                        content_switcher.current = value
                    continue

                # Get widget with current paper type suffix
                widget_key = f"{form_field}_{self.current_paper_type}"
                if widget_key in self.input_widgets:
                    widget = self.input_widgets[widget_key]
                    if hasattr(widget, "text"):
                        old_value = widget.text or ""
                    else:
                        old_value = widget.value or ""

                    new_value = str(value) if value else ""

                    if old_value.strip() != new_value.strip():
                        if hasattr(widget, "text"):
                            widget.text = new_value
                        else:
                            widget.value = new_value
                        updated_fields.append(form_field)

        # Add updated fields to changed_fields set for italic styling
        self.changed_fields.update(updated_fields)
        # Update styling for changed fields without rebuilding the entire UI
        self._update_field_styling()

    def _update_field_styling(self):
        """Update styling for changed fields without rebuilding the UI."""
        # Update styling for the current paper type's widgets
        for field_name in self.changed_fields:
            widget_key = f"{field_name}_{self.current_paper_type}"
            if widget_key in self.input_widgets:
                self.input_widgets[widget_key].add_class("changed-field")

    def _compare_extracted_with_current_form(self, extracted_data):
        """Compare extracted data with current form values and return list of changes."""
        field_mapping = {
            "title": "title",
            "authors": "author_names",
            "abstract": "abstract",
            "year": "year",
            "venue_full": "venue_full",
            "venue_acronym": "venue_acronym",
            "doi": "doi",
            "url": "url",
            "category": "category",
            "paper_type": "paper_type",
        }

        changes = []

        for extracted_field, form_field in field_mapping.items():
            if extracted_field in extracted_data and extracted_data[extracted_field]:
                value = extracted_data[extracted_field]

                if extracted_field == "authors" and isinstance(value, list):
                    new_value = ", ".join(value)
                elif extracted_field == "year" and isinstance(value, int):
                    new_value = str(value)
                else:
                    new_value = str(value) if value else ""

                if extracted_field == "paper_type":
                    current_value = self.current_paper_type
                else:
                    # Get widget with current paper type suffix
                    widget_key = f"{form_field}_{self.current_paper_type}"
                    if widget_key in self.input_widgets:
                        widget = self.input_widgets[widget_key]
                        if hasattr(widget, "text"):
                            current_value = widget.text or ""
                        else:
                            current_value = widget.value or ""
                    else:
                        current_value = ""

                if new_value.strip() != current_value.strip():
                    changes.append(f"{form_field}: '{current_value}' → '{new_value}'")

        return changes
