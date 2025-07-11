"""
Export dialog for selecting export format and destination.
"""

from typing import Optional, Dict, Any
from prompt_toolkit.shortcuts import input_dialog, button_dialog, radiolist_dialog, yes_no_dialog
import os


class ExportDialog:
    """Dialog for export options."""
    
    def show_export_dialog(self, paper_count: int) -> Optional[Dict[str, Any]]:
        """Show export dialog and return export parameters or None if cancelled."""
        try:
            # Select format
            format_choice = radiolist_dialog(
                title="Export Format",
                text=f"Select format for {paper_count} papers:",
                values=[
                    ("bibtex", "BibTeX (.bib)"),
                    ("markdown", "Markdown (.md)"),
                    ("html", "HTML (.html)"),
                    ("json", "JSON (.json)"),
                ]
            ).run()
            
            if not format_choice:
                return None
            
            # Select destination
            destination_choice = radiolist_dialog(
                title="Export Destination",
                text="Where to export:",
                values=[
                    ("file", "Save to File"),
                    ("clipboard", "Copy to Clipboard"),
                ]
            ).run()
            
            if not destination_choice:
                return None
            
            result = {
                "format": format_choice,
                "destination": destination_choice
            }
            
            # If saving to file, get filename
            if destination_choice == "file":
                extensions = {
                    "bibtex": ".bib",
                    "markdown": ".md", 
                    "html": ".html",
                    "json": ".json"
                }
                
                default_filename = f"papers{extensions[format_choice]}"
                
                filename = input_dialog(
                    title="Export Filename",
                    text="Enter filename:",
                    default=default_filename
                ).run()
                
                if not filename:
                    return None
                
                # Check if file exists
                if os.path.exists(filename):
                    overwrite = yes_no_dialog(
                        title="File Exists",
                        text=f"File '{filename}' already exists. Overwrite?"
                    ).run()
                    
                    if not overwrite:
                        return None
                
                result["filename"] = filename
            
            return result
            
        except Exception as e:
            return None


class SimpleExportDialog:
    """Simple command-line export dialog."""
    
    def show_export_dialog(self, paper_count: int) -> Optional[Dict[str, Any]]:
        """Show simple export dialog using default values."""
        # Default to BibTeX file export
        return {
            "format": "bibtex",
            "destination": "file", 
            "filename": "papers.bib"
        }