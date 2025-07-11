"""
Dialog for exporting papers using simple terminal input.
"""

from typing import Optional, Dict, Any
from .simple_dialogs import SimpleDialogs


class SimpleExportDialog:
    """Dialog for export functionality."""

    def __init__(self):
        self.dialogs = SimpleDialogs()

    def show_export_dialog(self, paper_count: int) -> Optional[Dict[str, Any]]:
        """Show export dialog."""
        # Export format
        export_format = self.dialogs.get_choice(
            f"Select export format for {paper_count} papers:",
            [
                ("bibtex", "BibTeX (.bib)"),
                ("markdown", "Markdown (.md)"),
                ("html", "HTML (.html)"),
                ("json", "JSON (.json)")
            ],
            "bibtex"
        )

        if not export_format:
            return None

        # Export destination
        destination = self.dialogs.get_choice(
            "Where to export:",
            [
                ("file", "Save to file"),
                ("clipboard", "Copy to clipboard")
            ],
            "file"
        )

        if not destination:
            return None

        result = {
            'format': export_format,
            'destination': destination
        }

        # Get filename if saving to file
        if destination == "file":
            extensions = {
                'bibtex': '.bib',
                'markdown': '.md',
                'html': '.html',
                'json': '.json'
            }
            
            filename = self.dialogs.get_input(
                "Enter filename:",
                f"papers{extensions.get(export_format, '.txt')}"
            )
            
            if filename:
                result['filename'] = filename
            else:
                return None
        
        return result