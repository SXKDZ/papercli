from __future__ import annotations
import os
import platform
import subprocess
import traceback
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

import pyperclip

if TYPE_CHECKING:
    from ng.services import PDFManager


class SystemService:
    """Service for system integrations."""

    def __init__(self, pdf_manager: PDFManager):
        self.pdf_manager = pdf_manager

    def open_pdf(self, pdf_path: str) -> Tuple[bool, str]:
        """Open PDF file in system default viewer. Returns (success, error_message)."""
        try:
            if not os.path.exists(pdf_path):
                return False, f"PDF file not found: {pdf_path}"

            # Cross-platform PDF opening
            if platform.system() == "Windows":  # Windows
                os.startfile(pdf_path)
            elif platform.system() == "Darwin":  # macOS
                result = subprocess.run(
                    ["open", pdf_path], capture_output=True, text=True
                )
                if result.returncode != 0:
                    return False, f"Failed to open PDF: {result.stderr}"
            else:  # Linux and other Unix-like systems
                # Check if xdg-open is available
                try:
                    result = subprocess.run(
                        ["which", "xdg-open"], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return (
                            False,
                            "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                        )

                    result = subprocess.run(
                        ["xdg-open", pdf_path], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return False, f"Failed to open PDF: {result.stderr}"
                except FileNotFoundError:
                    return (
                        False,
                        "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                    )

            return True, ""

        except Exception as e:
            return False, f"Error opening PDF: {str(e)}"

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to system clipboard."""
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            # Fallback to system commands if pyperclip fails
            if platform.system() == "Windows":  # Windows
                subprocess.run(["clip"], input=text.encode(), check=True)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            else:  # Linux
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=True,
                )
            return True

        return False  # Should not reach here if any method succeeds

    def download_pdf(
        self,
        source: str,
        identifier: str,
        download_dir: str,
        paper_data: Dict[str, Any] = None,
    ) -> Tuple[Optional[str], str]:
        """
        Download PDF from various sources (arXiv, OpenReview, etc.).

        Returns:
            tuple[Optional[str], str]: (pdf_path, error_message)
            If successful: (path, "")
            If error: (None, error_message)
        """
        try:
            # Create download directory
            os.makedirs(download_dir, exist_ok=True)

            # Generate URL based on source
            if source == "arxiv":
                # Clean arXiv ID while preserving version numbers
                clean_id = re.sub(r"arxiv[:\s]*", "", identifier, flags=re.IGNORECASE)
                clean_id = re.sub(
                    r"[^\d\.v]", "", clean_id
                )  # Allow digits, dots, and 'v' for versions
                pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
            elif source == "openreview":
                pdf_url = f"https://openreview.net/pdf?id={identifier}"
            else:
                return None, f"Unsupported source: {source}"

            # Use PDFManager to handle everything with proper naming
            self.pdf_manager.pdf_dir = download_dir  # Set download directory

            # Download with proper temp->final naming
            pdf_path, error_msg = (
                self.pdf_manager.download_pdf_from_url_with_proper_naming(
                    pdf_url, paper_data
                )
            )

            if error_msg:
                return None, error_msg

            return pdf_path, ""

        except Exception as e:
            return None, f"Error downloading PDF: {str(e)}\n{traceback.format_exc()}"
