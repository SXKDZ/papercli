"""Path utilities for PaperCLI."""

import os
from typing import Tuple

from ng.db.database import get_pdf_directory


class PDFPathHandler:
    """Centralized handler for PDF path operations."""

    def __init__(self):
        self.pdf_dir = get_pdf_directory()

    def get_absolute_path(self, pdf_path: str) -> str:
        """Convert relative or absolute PDF path to absolute path."""
        if not pdf_path:
            return ""

        if os.path.isabs(pdf_path):
            return pdf_path

        return os.path.join(self.pdf_dir, pdf_path)

    def get_relative_path(self, pdf_path: str) -> str:
        """Convert absolute PDF path to relative path within PDF directory."""
        if not pdf_path:
            return ""

        abs_path = os.path.abspath(pdf_path)
        abs_pdf_dir = os.path.abspath(self.pdf_dir)

        try:
            return os.path.relpath(abs_path, abs_pdf_dir)
        except ValueError:
            # Path is outside PDF directory
            return pdf_path

    def normalize_path(self, pdf_path: str) -> str:
        """Normalize PDF path for storage (ensure it's relative)."""
        if not pdf_path:
            return ""

        # If it's already within our PDF directory, make it relative
        abs_path = os.path.abspath(pdf_path)
        abs_pdf_dir = os.path.abspath(self.pdf_dir)

        if abs_path.startswith(abs_pdf_dir):
            return self.get_relative_path(pdf_path)

        return pdf_path

    def is_url(self, path: str) -> bool:
        """Check if the path is a URL."""
        return path.startswith(("http://", "https://"))

    def is_relative_path(self, path: str) -> bool:
        """Check if path is a relative path (no slashes or protocol)."""
        return not ("/" in path or "\\" in path or self.is_url(path))

    def validate_pdf_path(self, pdf_path: str) -> Tuple[bool, str]:
        """Validate PDF path and return (is_valid, error_message)."""
        if not pdf_path:
            return True, ""

        if self.is_url(pdf_path):
            return True, ""  # URLs are valid for downloading

        abs_path = self.get_absolute_path(pdf_path)

        if not os.path.exists(abs_path):
            return False, f"PDF file not found: {abs_path}"

        if not os.path.isfile(abs_path):
            return False, f"Path is not a file: {abs_path}"

        try:
            with open(abs_path, "rb") as f:
                header = f.read(4)
                if header != b"%PDF":
                    return False, f"File is not a valid PDF: {abs_path}"
        except Exception as e:
            return False, f"Cannot read PDF file: {e}"

        return True, ""
