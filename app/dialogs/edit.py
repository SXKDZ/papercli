"""
Custom dialog for editing paper metadata in a full-window form with paper type buttons.
"""

import os
from typing import Any
from typing import Callable
from typing import Dict
from typing import List

from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding import merge_key_bindings
from prompt_toolkit.layout import ScrollablePane
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.containers import VSplit
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.containers import WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Button
from prompt_toolkit.widgets import Dialog
from prompt_toolkit.widgets import TextArea

from ..services import AuthorService
from ..services import BackgroundOperationService
from ..services import CollectionService
from ..services import MetadataExtractor
from ..services import normalize_paper_data


class EditDialog:
    """A full-window dialog for editing paper metadata with paper type buttons."""

    def __init__(
        self,
        paper_data: Dict[str, Any],
        callback: Callable,
        log_callback: Callable,
        error_display_callback: Callable,
        read_only_fields: List[str] = None,
        status_bar=None,
    ):
        self.paper_data = paper_data
        self.callback = callback
        self.log_callback = log_callback
        self.error_display_callback = error_display_callback
        self.status_bar = status_bar
        self.result = None
        self.collection_service = CollectionService()
        self.author_service = AuthorService()
        self.background_service = BackgroundOperationService(
            status_bar=self.status_bar, log_callback=self.log_callback
        )
        self.read_only_fields = read_only_fields or []

        # Track fields that have been changed by Extract/Summarize operations
        self.changed_fields = set()

        self.paper_types = {
            "Conference": "conference",
            "Journal": "journal",
            "Workshop": "workshop",
            "Preprint": "preprint",
            "Website": "website",
            "Other": "other",
        }

        self.fields_by_type = {
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
                "pdf_path",
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

        self.current_paper_type = paper_data.get("paper_type", "conference")
        self.input_fields = {}
        self._create_layout()
        self._add_key_bindings()

    def _get_full_pdf_path(self):
        """Get the full absolute path for the PDF file."""
        pdf_path = self.paper_data.get("pdf_path", "")
        if not pdf_path:
            return ""

        from ..services.pdf import PDFManager

        pdf_manager = PDFManager()
        return pdf_manager.get_absolute_path(pdf_path)

    def _create_input_fields(self):
        """Create input fields for fields visible in the current paper type."""
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )
        self.input_fields = {}

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
            "collections": collection_names,
            "abstract": self.paper_data.get("abstract", ""),
            "notes": self.paper_data.get("notes", ""),
        }

        for field_name in visible_fields:
            if field_name in all_field_values:
                value = str(all_field_values[field_name] or "")
                is_read_only = field_name in self.read_only_fields

                # Make title, author_names, abstract, and notes multiline
                is_multiline = field_name in [
                    "title",
                    "author_names",
                    "abstract",
                    "notes",
                ]

                # Apply italic styling if field was changed by Extract/Summarize
                field_style = "class:textarea"
                if field_name in self.changed_fields:
                    field_style = "class:textarea italic"
                elif is_read_only:
                    field_style = "class:textarea.readonly"

                input_field = TextArea(
                    text=value,
                    multiline=is_multiline,
                    read_only=is_read_only,
                    width=Dimension(min=80, preferred=120),  # Make input fields wider
                    style=field_style,
                    focusable=not is_read_only,  # Explicitly set focusable
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
            button = Button(
                text=display_name,
                handler=lambda t=type_value: self._set_paper_type(t),
                width=len(display_name) + 4,
            )
            button.window.style = style
            type_buttons.append(button)
        type_buttons_row = VSplit(type_buttons, padding=1, style="class:button-row")

        all_field_containers = []
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )
        for field_name in visible_fields:
            if field_name in self.input_fields:
                # Custom label mappings for better display
                label_mappings = {
                    "doi": "DOI",
                    "pdf_path": "PDF Path",
                    "preprint_id": (
                        "ID" if self.current_paper_type == "preprint" else "Preprint ID"
                    ),
                    "url": "URL",
                    "venue_full": (
                        "Website"
                        if self.current_paper_type == "preprint"
                        else "Venue Full"
                    ),
                }
                label_text = label_mappings.get(
                    field_name, field_name.replace("_", " ").title()
                )
                label_window = Window(
                    content=FormattedTextControl(f"{label_text}:", focusable=False),
                    width=18,  # Fixed width for consistent alignment
                    style="class:dialog.label",
                )

                field_container = VSplit(
                    [
                        label_window,
                        self.input_fields[
                            field_name
                        ].window,  # This will expand to fill remaining space
                    ]
                )
                all_field_containers.append(field_container)

        fields_content = HSplit(all_field_containers, padding=1)
        fields_layout = ScrollablePane(
            content=fields_content,
            show_scrollbar=True,
            keep_cursor_visible=True,
            width=Dimension(
                min=120, preferred=140
            ),  # Ensure content fits within dialog
        )

        # Put "Paper Type:" label and buttons on the same line
        paper_type_row = VSplit(
            [
                Window(
                    content=FormattedTextControl("Paper Type:"),
                    width=18,
                    style="class:dialog.label",
                ),
                type_buttons_row,
            ]
        )

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
            width=Dimension(
                min=130, preferred=150
            ),  # Ensure body fits within dialog frame
        )

        # Create custom button row with centered buttons and right-aligned help text
        extract_pdf_button = Button(
            text="Extract", handler=self._handle_extract_pdf, width=13
        )
        summarize_button = Button(
            text="Summarize", handler=self._handle_summarize, width=13
        )
        save_button = Button(text="Save", handler=self._handle_save)
        cancel_button = Button(text="Cancel", handler=self._handle_cancel)

        # Create button row layout
        button_row = VSplit(
            [
                # Flexible spacer
                Window(),
                # Centered buttons
                extract_pdf_button,
                Window(width=2),  # Small gap between buttons
                summarize_button,
                Window(width=2),  # Small gap between buttons
                save_button,
                Window(width=2),  # Small gap between buttons
                cancel_button,
                # Flexible spacer with right-aligned help text
                Window(
                    content=FormattedTextControl(
                        "Ctrl-S: Save  Ctrl-E: Extract  Ctrl-L: Summarize  Esc: Cancel"
                    ),
                    align=WindowAlign.RIGHT,
                ),
            ]
        )

        self.dialog = Dialog(
            title="Edit Paper Metadata",
            body=self.body_container,
            buttons=[button_row],
            with_background=False,
            modal=True,  # Remove shadow by setting with_background=False
            width=Dimension(min=140, preferred=160),  # Make dialog wider
        )
        self._set_initial_focus()

    def _set_paper_type(self, paper_type: str):
        """Sets the paper type and rebuilds the dialog body."""
        current_values = {name: field.text for name, field in self.input_fields.items()}
        self.current_paper_type = paper_type

        for field_name, value in current_values.items():
            if field_name in ["author_names", "collections"]:
                self.paper_data[field_name.replace("_names", "")] = [
                    name.strip() for name in value.split(",") if name.strip()
                ]
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

            # Apply centralized normalization for all fields
            if new_value:
                temp_data = {field_name: new_value}
                normalized_data = normalize_paper_data(temp_data)
                new_value = normalized_data.get(field_name, new_value)

            # Get the original value. For authors and collections, we need to format them as a string.
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
                # Ensure old_value is a string, treating None as empty string
                old_value = str(old_value) if old_value is not None else ""

            # Normalize values for comparison (treat None and "" as equivalent)
            normalized_old_value = old_value
            normalized_new_value = new_value if new_value is not None else ""

            if normalized_old_value != normalized_new_value:
                changes_made.append(f"{field_name} from '{old_value}' to '{new_value}'")

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

        if changes_made:
            paper_id = self.paper_data.get("id", "New Paper")
            changes_text = "  \n".join(changes_made)
            log_message = f"Paper '{self.paper_data.get('title')}' (ID: {paper_id}) updated: \n{changes_text}"
            self.log_callback("edit", log_message)

        # Clear changed fields when saving
        self.changed_fields.clear()

        self.result = result
        self.callback(self.result)

    def _apply_styling_changes(self):
        """Apply styling changes by rebuilding the form (use sparingly)."""
        try:
            # Preserve current field values
            current_values = {
                name: field.text for name, field in self.input_fields.items()
            }
            # Rebuild form to apply styling changes
            self.body_container.children = self._build_body_components()
            # Restore all current values
            for field_name, field_value in current_values.items():
                if field_name in self.input_fields:
                    self.input_fields[field_name].text = field_value
            # Refresh the display
            get_app().invalidate()
        except Exception as e:
            # If styling update fails, just log it and continue
            if self.log_callback:
                self.log_callback(
                    "styling_error", f"Failed to update field styling: {e}"
                )

    def _restore_dialog_focus(self):
        """Restore focus to the edit dialog after background operations."""
        try:
            # Focus on the notes field if it exists (since that's what was just updated)
            if "notes" in self.input_fields:
                get_app().layout.focus(self.input_fields["notes"])
            # Otherwise focus on the first available field
            elif self.input_fields:
                first_field = next(iter(self.input_fields.values()))
                get_app().layout.focus(first_field)
        except Exception as e:
            # If focus restoration fails, just log it and continue
            if self.log_callback:
                self.log_callback("focus_error", f"Failed to restore dialog focus: {e}")

    def _handle_cancel(self):
        # Clear changed fields when cancelling
        self.changed_fields.clear()
        self.callback(None)

    def _handle_extract_pdf(self):
        """Handle Extract PDF button press."""
        pdf_path = self.paper_data.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            self.error_display_callback(
                "Extract PDF Error",
                "No PDF file available for this paper.",
                "Please ensure the paper has an associated PDF and the file exists.",
            )
            return

        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        # Extract metadata using background service
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
                    self.status_bar.set_error(
                        "Failed to extract metadata: No data extracted"
                    )
                return

            # Check what changes would be made by comparing with current form values
            changes = self._compare_extracted_with_current_form(extracted_data)

            if not changes:
                if self.status_bar:
                    self.status_bar.set_status(
                        "ℹ No changes found - extracted metadata matches current values"
                    )
                return

            # Apply changes directly to form fields (no confirmation needed for edit dialog)
            self._update_fields_with_extracted_data(extracted_data)
            # Force styling update after extraction since this is user-initiated
            self._apply_styling_changes()
            # Ensure focus returns to the edit dialog after styling update
            self._restore_dialog_focus()
            if self.status_bar:
                self.status_bar.set_success(
                    f"PDF metadata extracted and applied - {len(changes)} fields updated"
                )

        self.background_service.run_operation(
            operation_func=extract_operation,
            operation_name=f"edit_extract_{paper_id}",
            initial_message=f"Extracting metadata from PDF for '{title}'...",
            on_complete=on_extract_complete,
        )

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

        # Track which fields are being updated
        updated_fields = []

        for extracted_field, form_field in field_mapping.items():
            if extracted_field in extracted_data:
                value = extracted_data[extracted_field]

                # Skip empty/None values but not for special handling fields
                if not value and extracted_field not in ["paper_type"]:
                    continue

                if extracted_field == "authors" and isinstance(value, list):
                    value = ", ".join(value)
                elif extracted_field == "year" and isinstance(value, int):
                    value = str(value)
                elif extracted_field == "paper_type":
                    # Update paper type and rebuild form if different
                    if value != self.current_paper_type:
                        self.current_paper_type = value
                        updated_fields.append(form_field)
                        # Preserve current field values and changed fields tracking
                        current_values = {
                            name: field.text
                            for name, field in self.input_fields.items()
                        }
                        # Rebuild form
                        self.body_container.children = self._build_body_components()
                        # Restore ALL current values first
                        for field_name, field_value in current_values.items():
                            if field_name in self.input_fields:
                                self.input_fields[field_name].text = field_value
                        get_app().invalidate()
                    continue

                # Update field if it exists in current form
                if form_field in self.input_fields:
                    old_value = self.input_fields[form_field].text or ""
                    new_value = str(value) if value else ""

                    # Only update and mark as changed if values are actually different
                    if old_value.strip() != new_value.strip():
                        self.input_fields[form_field].text = new_value
                        updated_fields.append(form_field)

        # Add updated fields to changed_fields set for italic styling
        self.changed_fields.update(updated_fields)

        # Refresh the display
        get_app().invalidate()

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

                # Convert extracted value to string format for comparison
                if extracted_field == "authors" and isinstance(value, list):
                    new_value = ", ".join(value)
                elif extracted_field == "year" and isinstance(value, int):
                    new_value = str(value)
                else:
                    new_value = str(value) if value else ""

                # Get current form value
                if extracted_field == "paper_type":
                    current_value = self.current_paper_type
                elif form_field in self.input_fields:
                    current_value = self.input_fields[form_field].text or ""
                else:
                    current_value = ""

                # Compare values (strip whitespace for accurate comparison)
                if new_value.strip() != current_value.strip():
                    changes.append(f"{form_field}: '{current_value}' → '{new_value}'")

        return changes

    def _handle_summarize(self):
        """Handle Summarize button press."""
        pdf_path = self.paper_data.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            self.error_display_callback(
                "Summarize Error",
                "No PDF file available for this paper.",
                "Please ensure the paper has an associated PDF and the file exists.",
            )
            return

        title = self.paper_data.get("title", "Unknown Title")
        paper_id = self.paper_data.get("id", "unknown")

        # Generate summary using background service
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
            if summary and "notes" in self.input_fields:
                # Check if the summary is different from current notes
                current_notes = self.input_fields["notes"].text
                if current_notes != summary:
                    self.input_fields["notes"].text = summary
                    # Add notes field to changed_fields for italic styling
                    self.changed_fields.add("notes")
                    # Apply styling changes immediately to show italic
                    self._apply_styling_changes()
                    # Ensure focus returns to the edit dialog after styling update
                    self._restore_dialog_focus()
                    if self.status_bar:
                        self.status_bar.set_success(
                            "Summary generated and applied to notes field"
                        )
                else:
                    if self.status_bar:
                        self.status_bar.set_status(
                            "Summary matches existing notes - no changes made"
                        )
            else:
                if self.status_bar:
                    self.status_bar.set_error(
                        "Failed to generate summary or notes field not available"
                    )

        self.background_service.run_operation(
            operation_func=generate_summary_operation,
            operation_name=f"edit_summary_{paper_id}",
            initial_message=f"Generating summary for '{title}'...",
            on_complete=on_summary_complete,
        )

    def _set_initial_focus(self):
        """Sets the initial focus to the first editable field."""
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )

        for field_name in visible_fields:
            if (
                field_name in self.input_fields
                and not self.input_fields[field_name].read_only
            ):
                self.initial_focus = self.input_fields[field_name].window
                return

        self.initial_focus = self.dialog.buttons[0]

    def _focus_first_visible_field(self):
        """Focuses the first editable field in the dialog."""
        self._set_initial_focus()
        if self.initial_focus:
            get_app().layout.focus(self.initial_focus)

    def get_initial_focus(self):
        return getattr(self, "initial_focus", None)

    def _get_focusable_fields(self):
        """Get list of focusable input field windows in order."""
        visible_fields = self.fields_by_type.get(
            self.current_paper_type, self.fields_by_type["other"]
        )
        focusable_windows = []
        field_names = []

        for field_name in visible_fields:
            if (
                field_name in self.input_fields
                and not self.input_fields[field_name].read_only
            ):
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
            current_field = (
                self.focusable_field_names[current_index]
                if current_index < len(self.focusable_field_names)
                else "unknown"
            )
            next_field = (
                self.focusable_field_names[next_index]
                if next_index < len(self.focusable_field_names)
                else "unknown"
            )
        except ValueError:
            # Current window not in list, focus first
            next_window = focusable_windows[0]
            next_field = (
                self.focusable_field_names[0]
                if self.focusable_field_names
                else "unknown"
            )

        # Update focused state - manually force focus
        for field_name, field in self.input_fields.items():
            # Check if the window of the TextArea matches the next_window
            field.focused = field.window == next_window

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

        @kb.add("c-e")
        def _(event):
            self._handle_extract_pdf()

        @kb.add("c-l")
        def _(event):
            self._handle_summarize()

        @kb.add("enter")
        def _(event):
            # Add newline in multiline text areas
            current_control = event.app.layout.current_control
            if (
                hasattr(current_control, "buffer")
                and current_control.buffer.multiline()
            ):
                current_control.buffer.insert_text("\n")

        @kb.add("c-k")
        def _(event):
            # Cut text from cursor to end of line
            current_control = event.app.layout.current_control
            if hasattr(current_control, "buffer"):
                buffer = current_control.buffer
                buffer.delete(count=len(buffer.document.current_line_after_cursor))

        self.body_container.key_bindings = merge_key_bindings(
            [self.body_container.key_bindings or KeyBindings(), kb]
        )

    def __pt_container__(self):
        return self.dialog
