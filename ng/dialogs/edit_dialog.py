import os
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, Input, TextArea, RadioSet, RadioButton, Label
from textual.screen import ModalScreen
from textual.reactive import reactive
from typing import Callable, Dict, Any, List, Optional

from ng.services.author import AuthorService
from ng.services.collection import CollectionService
from ng.services.metadata import MetadataExtractor
from ng.services.pdf import PDFManager
from ng.services.utils import normalize_paper_data
from ng.services.background import BackgroundOperationService
from ng.db.database import get_pdf_directory


class EditDialog(ModalScreen):
    """A floating modal dialog for editing paper metadata with field visibility based on paper type."""

    DEFAULT_CSS = """
    EditDialog {
        align: center middle;
        layer: dialog;
    }
    EditDialog > Container {
        width: 90;
        height: 40;
        max-width: 100;
        max-height: 45;
        border: thick $accent;
        background: $panel;
    }
    EditDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
        margin: 0 0 1 0;
    }
    EditDialog .paper-type-section {
        height: auto;
        margin: 0 0 1 0;
    }
    EditDialog .paper-type-label {
        text-style: bold;
        width: 15;
        margin: 0 1 0 0;
    }
    EditDialog .form-fields {
        height: 1fr;
        border: solid grey;
        margin: 0 0 1 0;
    }
    EditDialog .form-row {
        height: auto;
        margin: 0 0 1 0;
    }
    EditDialog .field-label {
        width: 15;
        margin: 0 1 0 0;
        text-align: right;
    }
    EditDialog .field-input {
        width: 1fr;
    }
    EditDialog .multiline-input {
        height: 3;
    }
    EditDialog .changed-field {
        text-style: italic;
    }
    EditDialog .button-row {
        height: 3;
        align: center middle;
    }
    EditDialog .button-row Button {
        margin: 0 1;
        min-width: 10;
    }
    EditDialog RadioSet {
        height: 1;
        layout: horizontal;
    }
    EditDialog RadioButton {
        margin: 0 1 0 0;
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
            "title", "author_names", "venue_full", "venue_acronym", "year",
            "pages", "doi", "url", "pdf_path", "collections", "abstract", "notes",
        ],
        "journal": [
            "title", "author_names", "venue_full", "venue_acronym", "year",
            "volume", "issue", "pages", "doi", "pdf_path", "collections", "abstract", "notes",
        ],
        "workshop": [
            "title", "author_names", "venue_full", "venue_acronym", "year",
            "pages", "doi", "url", "pdf_path", "collections", "abstract", "notes",
        ],
        "preprint": [
            "title", "author_names", "venue_full", "year", "preprint_id",
            "category", "doi", "url", "pdf_path", "collections", "abstract", "notes",
        ],
        "website": [
            "title", "author_names", "year", "url", "pdf_path", "collections",
            "abstract", "notes",
        ],
        "other": [
            "title", "author_names", "venue_full", "venue_acronym", "year",
            "volume", "issue", "pages", "doi", "preprint_id", "category",
            "url", "pdf_path", "collections", "abstract", "notes",
        ],
    }

    current_paper_type = reactive("conference")
    changed_fields = reactive(set())

    def __init__(
        self,
        paper_data: Dict[str, Any],
        callback: Callable[[Dict[str, Any] | None], None],
        log_callback: Callable = None,
        error_display_callback: Callable = None,
        read_only_fields: List[str] = None,
        status_bar=None,
        app=None,
        *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.paper_data = paper_data
        self.callback = callback
        self.log_callback = log_callback
        self.error_display_callback = error_display_callback
        self.read_only_fields = read_only_fields or []
        self.status_bar = status_bar
        self.parent_app = app  # Renamed to avoid conflict with Textual's app property

        self.collection_service = CollectionService()
        self.author_service = AuthorService()
        self.pdf_manager = PDFManager(pdf_dir=get_pdf_directory())
        
        # Initialize BackgroundOperationService - use parent_app if available, otherwise create a minimal version
        if self.parent_app:
            self.background_service = BackgroundOperationService(
                app=self.parent_app, log_callback=self.log_callback
            )
        else:
            # Fallback: create a simple version without background operations
            self.background_service = None

        self.input_widgets: Dict[str, Input | TextArea] = {}
        self.current_paper_type = paper_data.get("paper_type", "conference")
        self.changed_fields = set()

    def _get_full_pdf_path(self):
        """Get the full absolute path for the PDF file."""
        pdf_path = self.paper_data.get("pdf_path", "")
        if not pdf_path:
            return ""
        return self.pdf_manager.get_absolute_path(pdf_path)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Edit Paper Metadata", classes="dialog-title")
            
            # Paper Type Selection
            with Horizontal(classes="paper-type-section"):
                yield Label("Paper Type:", classes="paper-type-label")
                with RadioSet(id="paper-type-radio-set"):
                    for display_name, type_value in self.paper_types.items():
                        yield RadioButton(
                            display_name, 
                            value=type_value == self.current_paper_type,
                            id=f"type-{type_value}"
                        )

            # Scrollable form fields
            with VerticalScroll(classes="form-fields", id="form-fields"):
                yield Container(id="field-container")

            # Action buttons
            with Horizontal(classes="button-row"):
                yield Button("Extract", id="extract-button", variant="default")
                yield Button("Summarize", id="summarize-button", variant="default")
                yield Button("Save", id="save-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the dialog on mount."""
        self._create_all_input_fields()
        self._update_visible_fields()
        
        # Set initial paper type selection
        try:
            radio_set = self.query_one("#paper-type-radio-set", RadioSet)
            for button in radio_set.query(RadioButton):
                if button.id == f"type-{self.current_paper_type}":
                    button.value = True
                    break
        except:
            pass

    def _create_all_input_fields(self):
        """Create all possible input fields for all paper types."""
        # Get all field values from paper data
        authors = self.paper_data.get("authors", [])
        if isinstance(authors, list):
            author_names = ", ".join([getattr(a, "full_name", str(a)) for a in authors])
        else:
            author_names = str(authors) if authors else ""

        collections = self.paper_data.get("collections", [])
        if isinstance(collections, list):
            collection_names = ", ".join([getattr(c, "name", str(c)) for c in collections])
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
            "collections": collection_names,
            "abstract": self.paper_data.get("abstract", ""),
            "notes": self.paper_data.get("notes", ""),
        }

        # Custom label mappings
        label_mappings = {
            "doi": "DOI",
            "pdf_path": "PDF Path",
            "preprint_id": "Preprint ID",
            "url": "URL",
            "venue_full": "Venue Full",
            "venue_acronym": "Venue Acronym",
            "author_names": "Authors",
        }

        for field_name, value in all_field_values.items():
            is_read_only = field_name in self.read_only_fields
            is_multiline = field_name in ["title", "author_names", "abstract", "notes"]
            
            safe_value = str(value) if value is not None else ""

            if is_multiline:
                widget = TextArea(
                    text=safe_value,
                    id=f"input-{field_name}",
                    read_only=is_read_only,
                    classes="field-input multiline-input"
                )
            else:
                widget = Input(
                    value=safe_value,
                    id=f"input-{field_name}",
                    disabled=is_read_only,
                    classes="field-input"
                )
            
            self.input_widgets[field_name] = widget

    def _update_visible_fields(self):
        """Update visible fields based on current paper type."""
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )
        
        # Get field container
        field_container = self.query_one("#field-container", Container)
        field_container.remove_children()

        # Custom label mappings
        label_mappings = {
            "doi": "DOI",
            "pdf_path": "PDF Path",
            "preprint_id": "ID" if self.current_paper_type == "preprint" else "Preprint ID",
            "url": "URL",
            "venue_full": "Website" if self.current_paper_type == "preprint" else "Venue Full",
            "venue_acronym": "Venue Acronym",
            "author_names": "Authors",
        }

        for field_name in visible_fields:
            if field_name in self.input_widgets:
                label_text = label_mappings.get(
                    field_name, field_name.replace("_", " ").title()
                )
                
                # Check if field has pending changes for styling
                label_classes = "field-label"
                input_classes = "field-input"
                if field_name in self.changed_fields:
                    input_classes += " changed-field"
                
                if field_name in ["title", "author_names", "abstract", "notes"]:
                    input_classes += " multiline-input"
                
                # Update widget classes
                widget = self.input_widgets[field_name]
                widget.classes = input_classes

                field_container.mount(
                    Horizontal(
                        Label(f"{label_text}:", classes=label_classes),
                        widget,
                        classes="form-row"
                    )
                )

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle paper type change."""
        if event.radio_set.id == "paper-type-radio-set" and event.pressed:
            new_type = event.pressed.id.replace("type-", "")
            if new_type != self.current_paper_type:
                self.current_paper_type = new_type
                self._update_visible_fields()

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

    def action_save(self) -> None:
        """Handle save action."""
        result = {"paper_type": self.current_paper_type}
        changes_made = []

        for field_name, input_widget in self.input_widgets.items():
            if field_name in self.read_only_fields:
                continue

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
                    old_value = ", ".join([getattr(a, "full_name", str(a)) for a in authors])
                else:
                    old_value = str(authors) if authors else ""
            elif field_name == "collections":
                collections = self.paper_data.get("collections", [])
                if isinstance(collections, list):
                    old_value = ", ".join([getattr(c, "name", str(c)) for c in collections])
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
                result["authors"] = [
                    self.author_service.get_or_create_author(name) for name in names
                ]
            elif field_name == "collections":
                names = [name.strip() for name in new_value.split(",") if name.strip()]
                result["collections"] = [
                    self.collection_service.get_or_create_collection(name)
                    for name in names
                ]
            elif field_name == "year":
                result["year"] = int(new_value) if new_value.isdigit() else None
            else:
                result[field_name] = new_value if new_value else None

        if changes_made and self.log_callback:
            paper_id = self.paper_data.get("id", "New Paper")
            changes_text = "  \n".join(changes_made)
            log_message = f"Paper '{self.paper_data.get('title')}' (ID: {paper_id}) updated: \n{changes_text}"
            self.log_callback("edit", log_message)

        # Clear changed fields when saving
        self.changed_fields.clear()

        if self.callback:
            self.callback(result)
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Handle cancel action."""
        self.changed_fields.clear()
        if self.callback:
            self.callback(None)
        self.dismiss(None)

    def action_extract_pdf(self) -> None:
        """Handle Extract PDF action."""
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

        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        def extract_operation():
            extractor = MetadataExtractor(log_callback=self.log_callback)
            extracted_data = extractor.extract_from_pdf(pdf_path)
            if not extracted_data:
                raise Exception("No metadata could be extracted from PDF")
            return extracted_data

        def on_extract_complete(extracted_data, error):
            if error:
                if self.status_bar:
                    self.status_bar.set_error(f"Failed to extract metadata: {error}")
                return

            if not extracted_data:
                if self.status_bar:
                    self.status_bar.set_error("Failed to extract metadata: No data extracted")
                return

            changes = self._compare_extracted_with_current_form(extracted_data)
            if not changes:
                if self.status_bar:
                    self.status_bar.set_status("ℹ No changes found - extracted metadata matches current values")
                return

            self._update_fields_with_extracted_data(extracted_data)
            if self.status_bar:
                self.status_bar.set_success(f"PDF metadata extracted and applied - {len(changes)} fields updated")

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
        """Handle Summarize action."""
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

        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        def generate_summary_operation():
            extractor = MetadataExtractor(log_callback=self.log_callback)
            summary = extractor.generate_paper_summary(pdf_path)
            if not summary:
                raise Exception("Failed to generate summary - empty response")
            return {"summary": summary}

        def on_summary_complete(result, error):
            if error:
                if self.status_bar:
                    self.status_bar.set_error(f"Failed to generate summary: {error}")
                return

            if not result:
                if self.status_bar:
                    self.status_bar.set_error("No summary generated")
                return

            summary = result["summary"]
            if summary and "notes" in self.input_widgets:
                current_notes = self.input_widgets["notes"].text if hasattr(self.input_widgets["notes"], 'text') else self.input_widgets["notes"].value
                if current_notes.strip() != summary.strip():
                    if hasattr(self.input_widgets["notes"], 'text'):
                        self.input_widgets["notes"].text = summary
                    else:
                        self.input_widgets["notes"].value = summary
                    self.changed_fields.add("notes")
                    self._update_visible_fields()  # Refresh to show italic styling
                    if self.status_bar:
                        self.status_bar.set_success("Summary generated and applied to notes field")
                else:
                    if self.status_bar:
                        self.status_bar.set_status("Summary matches existing notes - no changes made")
            else:
                if self.status_bar:
                    self.status_bar.set_error("Failed to generate summary or notes field not available")

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
                        self.current_paper_type = value
                        updated_fields.append(form_field)
                        # Update radio buttons
                        try:
                            radio_set = self.query_one("#paper-type-radio-set", RadioSet)
                            for button in radio_set.query(RadioButton):
                                button.value = button.id == f"type-{value}"
                        except:
                            pass
                        self._update_visible_fields()
                    continue

                if form_field in self.input_widgets:
                    widget = self.input_widgets[form_field]
                    if hasattr(widget, 'text'):
                        old_value = widget.text or ""
                    else:
                        old_value = widget.value or ""
                    
                    new_value = str(value) if value else ""

                    if old_value.strip() != new_value.strip():
                        if hasattr(widget, 'text'):
                            widget.text = new_value
                        else:
                            widget.value = new_value
                        updated_fields.append(form_field)

        # Add updated fields to changed_fields set for italic styling
        self.changed_fields.update(updated_fields)
        self._update_visible_fields()  # Refresh to show styling changes

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
                elif form_field in self.input_widgets:
                    widget = self.input_widgets[form_field]
                    if hasattr(widget, 'text'):
                        current_value = widget.text or ""
                    else:
                        current_value = widget.value or ""
                else:
                    current_value = ""

                if new_value.strip() != current_value.strip():
                    changes.append(f"{form_field}: '{current_value}' → '{new_value}'")

        return changes