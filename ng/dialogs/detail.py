import os
import webbrowser
from typing import Any, Callable, Dict

from pluralizer import Pluralizer
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

from ng.db.models import Paper
from ng.dialogs.chat import ChatDialog
from ng.dialogs.confirm import ConfirmDialog
from ng.dialogs.edit import EditDialog
from ng.services import PDFManager, PDFService, SystemService, theme
from ng.services.formatting import format_file_size

_pluralizer = Pluralizer()


class DetailDialog(ModalScreen):
    """A modal dialog for displaying detailed paper information."""

    DEFAULT_CSS = """
    DetailDialog {
        align: center middle;
    }

    #detail-container {
        width: 90%;
        height: 80%;
        border: solid $accent;
        background: $panel;
    }

    DetailDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }

    #detail-content {
        height: 1fr;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }

    #button-bar {
        height: auto;
        align: center middle;
        margin: 1;
    }
    #button-bar Button {
        height: 3;
        content-align: center middle;
        text-align: center;
        margin: 0 1;
        min-width: 12;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(
        self,
        paper: Paper,
        callback: Callable[[Dict[str, Any] | None], None],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.paper = paper
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container(id="detail-container"):
            yield Static("Paper Details", classes="dialog-title")
            with VerticalScroll(id="detail-content"):
                yield Markdown("", id="detail-text")
            with Horizontal(id="button-bar"):
                yield Button("Open PDF", id="pdf-button", disabled=True)
                yield Button("Open HTML", id="html-button", disabled=True)
                yield Button("Open Folder", id="folder-button", disabled=True)
                yield Button(
                    "Open Website",
                    id="website-button",
                    disabled=True,
                )
                yield Button("Chat", id="chat-button", variant="default")
                yield Button("Edit", id="edit-button", variant="default")
                yield Button("Delete", id="delete-button", variant="default")
                yield Button("Close", id="close-button", variant="default")

    def on_mount(self) -> None:
        """Initialize the detail display with paper information."""
        detail_text_widget = self.query_one("#detail-text", Markdown)

        if not self.paper:
            detail_text_widget.update("No paper selected for detail view.")
            return

        # Format the detail text with markdown formatting
        formatted_content = self._format_paper_details_markdown(self.paper)
        detail_text_widget.update(formatted_content)

        # Enable/disable buttons based on availability
        website_button = self.query_one("#website-button", Button)
        pdf_button = self.query_one("#pdf-button", Button)
        folder_button = self.query_one("#folder-button", Button)
        html_button = self.query_one("#html-button", Button)

        # Enable website button if URL is available
        if self.paper.url:
            website_button.disabled = False

        # For website papers: hide PDF button, show HTML button and folder button if snapshot exists
        is_website = self.paper.paper_type == "website"

        if is_website:
            # Hide PDF button for websites
            pdf_button.display = False
            html_button.display = True
            folder_button.display = True
            html_button.disabled = True
            folder_button.disabled = True

            # Show and enable HTML button and folder button if snapshot exists
            try:
                if (
                    hasattr(self.paper, "html_snapshot_path")
                    and self.paper.html_snapshot_path
                ):
                    from ng.db.database import get_db_manager

                    db_manager = get_db_manager()
                    data_dir = os.path.dirname(db_manager.db_path)
                    html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
                    html_absolute_path = os.path.join(
                        html_snapshot_dir, self.paper.html_snapshot_path
                    )
                    if os.path.exists(html_absolute_path):
                        html_button.disabled = False
                        folder_button.disabled = False
            except Exception:
                html_button.disabled = True
                folder_button.disabled = True
        else:
            # For non-website papers: hide HTML button, show PDF/folder if available
            html_button.display = False

            # Enable PDF and folder buttons if PDF path is available
            if self.paper.pdf_path:
                pdf_manager = PDFManager(app=self.app)
                pdf_path = pdf_manager.get_absolute_path(self.paper.pdf_path)
                if os.path.exists(pdf_path):
                    pdf_button.disabled = False
                    folder_button.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-button":
            self.dismiss(None)
        elif event.button.id == "website-button":
            self._open_website()
        elif event.button.id == "pdf-button":
            self._open_pdf()
        elif event.button.id == "folder-button":
            self._show_in_folder()
        elif event.button.id == "html-button":
            self._open_html()
        elif event.button.id == "chat-button":
            self._handle_chat()
        elif event.button.id == "edit-button":
            self._handle_edit_paper()
        elif event.button.id == "delete-button":
            self._handle_delete_paper()

    def _open_website(self) -> None:
        """Open the paper's website URL."""
        if self.paper.url:
            try:
                webbrowser.open(self.paper.url)
                self.app.notify(
                    f"Opened website for '{self.paper.title}'", severity="information"
                )
            except Exception as e:
                self.app.notify(f"Failed to open website: {str(e)}", severity="error")

    def _open_pdf(self) -> None:
        """Open the paper's PDF file."""
        if not self.paper.pdf_path:
            return
        pdf_manager = PDFManager(app=self.app)
        file_path = pdf_manager.get_absolute_path(self.paper.pdf_path)
        self._open_file(file_path, "PDF")

    def _show_in_folder(self) -> None:
        """Show the file in Finder/File Explorer - PDF for papers, HTML for websites."""
        try:
            # For website papers, show HTML snapshot folder
            if self.paper.paper_type == "website":
                if not (
                    hasattr(self.paper, "html_snapshot_path")
                    and self.paper.html_snapshot_path
                ):
                    return
                from ng.db.database import get_db_manager

                db_manager = get_db_manager()
                data_dir = os.path.dirname(db_manager.db_path)
                html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
                file_path = os.path.join(
                    html_snapshot_dir, self.paper.html_snapshot_path
                )
                file_type = "HTML snapshot"
            # For non-website papers, show PDF folder
            else:
                if not self.paper.pdf_path:
                    return
                pdf_manager = PDFManager(app=self.app)
                file_path = pdf_manager.get_absolute_path(self.paper.pdf_path)
                file_type = "PDF"

            # Use SystemService for cross-platform file location opening
            pdf_manager = PDFManager(app=self.app)
            system_service = SystemService(pdf_manager=pdf_manager, app=self.app)
            success, error_msg = system_service.open_file_location(file_path)

            if success:
                self.app.notify(
                    f"Revealed {file_type} location for '{self.paper.title}'",
                    severity="information",
                )
            else:
                self.app.notify(
                    f"Failed to show file location: {error_msg}", severity="error"
                )
        except Exception as e:
            self.app.notify(f"Failed to show file location: {str(e)}", severity="error")

    def _open_html(self) -> None:
        """Open the HTML snapshot."""
        if not (
            hasattr(self.paper, "html_snapshot_path") and self.paper.html_snapshot_path
        ):
            return
        from ng.db.database import get_db_manager

        db_manager = get_db_manager()
        data_dir = os.path.dirname(db_manager.db_path)
        html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
        html_absolute_path = os.path.join(
            html_snapshot_dir, self.paper.html_snapshot_path
        )
        self._open_file(html_absolute_path, "HTML snapshot")

    def _open_file(self, file_path: str, file_type: str) -> None:
        """Open a file using SystemService."""
        try:
            if not os.path.exists(file_path):
                self.app.notify(f"{file_type} file not found", severity="error")
                return

            pdf_manager = PDFManager(app=self.app)
            system_service = SystemService(pdf_manager=pdf_manager, app=self.app)
            success, error_msg = system_service.open_file(
                file_path, file_type=file_type
            )

            if success:
                self.app.notify(
                    f"Opened {file_type.lower()} for '{self.paper.title}'",
                    severity="information",
                )
            else:
                self.app.notify(
                    f"Failed to open {file_type.lower()}: {error_msg}", severity="error"
                )
        except Exception as e:
            self.app.notify(
                f"Failed to open {file_type.lower()}: {str(e)}", severity="error"
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _handle_chat(self) -> None:
        """Open the chat dialog for the current paper."""
        self.app.push_screen(ChatDialog(papers=[self.paper], callback=None))

    def _format_paper_details_markdown(self, paper: Paper) -> str:
        """Format paper details with markdown formatting."""
        content = []

        # Title
        content.append("## Title")
        content.append(f"{paper.title}")
        content.append("")

        # Authors
        content.append("## Authors")
        authors = paper.author_names if paper.author_names else "Unknown Authors"
        content.append(f"{authors}")
        content.append("")

        # Year and Venue
        content.append("## Venue")
        year = str(paper.year) if paper.year else "Unknown"
        venue = paper.venue_full or paper.venue_acronym or "Unknown Venue"
        content.append(f"{venue} ({year})")
        content.append("")

        # Publication Details
        publication_items = []
        if hasattr(paper, "volume") and paper.volume:
            publication_items.append(f"* **Volume:** {paper.volume}")
        if hasattr(paper, "issue") and paper.issue:
            publication_items.append(f"* **Issue:** {paper.issue}")
        if paper.pages:
            publication_items.append(f"* **Pages:** {paper.pages}")

        if publication_items:
            content.append("## Publication Details")
            content.extend(publication_items)
            content.append("")

        # DOI
        if paper.doi:
            content.append("## DOI")
            content.append(f"`{paper.doi}`")
            content.append("")

        # URL
        if paper.url:
            content.append("## Website")
            content.append(f"[{paper.url}]({paper.url})")
            content.append("")

        # Preprint ID
        if paper.preprint_id:
            content.append("## Preprint ID")
            content.append(f"`{paper.preprint_id}`")
            content.append("")

        # Category (e.g., cs.LG for arXiv papers)
        if paper.category:
            content.append("## Category")
            content.append(f"`{paper.category}`")
            content.append("")

        # PDF Path and Info (skip for website papers)
        if paper.paper_type != "website":
            content.append("## PDF")
            if paper.pdf_path:
                # Display absolute path for user convenience
                pdf_manager = PDFManager(app=self.app)
                pdf_service = PDFService(app=self.app)
                absolute_path = pdf_manager.get_absolute_path(paper.pdf_path)

                # Get and display enhanced PDF info using both services
                pdf_info = pdf_manager.get_pdf_info(paper.pdf_path)
                if pdf_info["exists"]:
                    info_parts = []

                    # Use formatting utility for better formatting
                    if pdf_info["size_bytes"] > 0:
                        formatted_size = format_file_size(pdf_info["size_bytes"])
                        info_parts.append(formatted_size)

                    # Get page count using PDFService
                    page_count = pdf_service.get_pdf_page_count(absolute_path)
                    if page_count > 0:
                        page_text = "page" if page_count == 1 else "pages"
                        info_parts.append(f"{page_count} {page_text}")

                    if info_parts:
                        content.append(f"{absolute_path} ({', '.join(info_parts)})")
                    else:
                        content.append(f"{absolute_path}")
                elif pdf_info["error"]:
                    content.append(f"{absolute_path} ({pdf_info['error']})")
                else:
                    content.append(f"{absolute_path}")
            else:
                content.append("*No PDF available*")
            content.append("")

        # HTML Snapshot (for website type papers)
        if hasattr(paper, "html_snapshot_path") and paper.html_snapshot_path:
            content.append("## HTML Snapshot")
            # Get absolute path for HTML snapshot
            import os
            from ng.db.database import get_db_manager

            db_manager = get_db_manager()
            data_dir = os.path.dirname(db_manager.db_path)
            html_snapshot_dir = os.path.join(data_dir, "html_snapshots")
            html_absolute_path = os.path.join(
                html_snapshot_dir, paper.html_snapshot_path
            )

            # Get file info
            if os.path.exists(html_absolute_path):
                file_size = os.path.getsize(html_absolute_path)
                formatted_size = format_file_size(file_size)
                # Display snapshot date from added_date
                snapshot_date = (
                    paper.added_date.strftime("%Y-%m-%d %H:%M:%S")
                    if paper.added_date
                    else "Unknown"
                )
                content.append(
                    f"{html_absolute_path} ({formatted_size}, captured {snapshot_date})"
                )
            else:
                content.append(f"{html_absolute_path} (file not found)")
            content.append("")

        # Collections
        if hasattr(paper, "collections") and paper.collections:
            content.append("## Collections")
            collection_names = [c.name for c in paper.collections]
            collection_list = "\n".join([f"- {name}" for name in collection_names])
            content.append(collection_list)
            content.append("")

        # Abstract
        if paper.abstract:
            content.append("## Abstract")
            content.append(f"{paper.abstract}")
            content.append("")

        # Notes
        if paper.notes:
            content.append("## Notes")
            content.append(f"{paper.notes}")
            content.append("")

        # Metadata
        content.append("## Metadata")
        metadata_items = []
        if paper.paper_type:
            metadata_items.append(f"* **Type:** {paper.paper_type}")
        metadata_items.append(f"* **Added:** {paper.added_date or 'Unknown'}")
        metadata_items.append(f"* **Modified:** {paper.modified_date or 'Unknown'}")

        content.extend(metadata_items)

        return "\n".join(content)

    def _handle_edit_paper(self) -> None:
        """Open the edit dialog for the current paper using existing command handler logic."""
        if not self.paper:
            return
        # Use PaperService method to prepare paper data for editing
        paper_data = self.app.paper_commands.paper_service.prepare_paper_data_for_edit(
            self.paper
        )

        # Create a callback that includes detail dialog specific logic
        def edit_dialog_callback(result):
            # Use the PaperService edit callback method
            base_callback = self.app.paper_commands.paper_service.create_edit_callback(
                self.app, self.paper.id
            )
            updated_paper = base_callback(result)

            # Add detail dialog specific logic
            if updated_paper:
                # Fetch a fresh copy of the paper to avoid detached instances
                try:
                    fresh_paper = self.app.paper_commands.paper_service.get_paper_by_id(
                        updated_paper.id
                    )
                    if fresh_paper:
                        self.paper = fresh_paper  # Update our reference with fresh data
                        self.on_mount()  # Refresh the detail display
                        if self.callback:
                            self.callback({"action": "updated", "paper": fresh_paper})
                    else:
                        self.app._add_log(
                            "debug",
                            "Fresh paper fetch returned None, using updated_paper",
                        )
                        # Fallback to updated_paper if fresh fetch fails
                        self.paper = updated_paper
                        if self.callback:
                            self.callback({"action": "updated", "paper": updated_paper})
                except Exception as e:
                    # If there's an error fetching fresh data, just update our reference without refresh
                    self.paper = updated_paper
                    if self.callback:
                        self.callback({"action": "updated", "paper": updated_paper})

        self.app.push_screen(
            EditDialog(
                paper_data=paper_data,
                callback=edit_dialog_callback,
                error_display_callback=lambda title, message: None,
                app=self.app,
            )
        )

    def _handle_delete_paper(self) -> None:
        """Delete the current paper using existing command handler logic."""
        if not self.paper:
            return

        confirm_message = (
            f"Are you sure you want to delete this paper?\n\n- {self.paper.title}"
        )

        def confirm_callback(confirmed: bool):
            if confirmed:
                try:
                    deleted_count = self.app.paper_commands.paper_service.delete_papers(
                        [self.paper.id]
                    )
                    self.app.load_papers()  # Reload papers to reflect changes
                    self.app.notify(
                        f"Successfully deleted {_pluralizer.pluralize('paper', deleted_count, True)}",
                        severity="information",
                    )
                    if self.callback:
                        self.callback({"action": "deleted", "paper": self.paper})

                    # Use call_later to dismiss after the confirm dialog is closed
                    self.app.call_later(lambda: self.dismiss(None))
                except Exception as e:
                    self.app.notify(f"Failed to delete paper: {e}", severity="error")

        self.app.push_screen(
            ConfirmDialog("Confirm Deletion", confirm_message, confirm_callback)
        )
