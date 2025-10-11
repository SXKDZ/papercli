from __future__ import annotations

import os
import platform
import re
import subprocess
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import pyperclip

if TYPE_CHECKING:
    from ng.services import PDFManager


class SystemService:
    """Service for system integrations."""

    def __init__(self, pdf_manager: PDFManager, app):
        self.pdf_manager = pdf_manager
        self.app = app

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

    def open_file(self, file_path: str, file_type: str = "file") -> Tuple[bool, str]:
        """Open file in system default application. Returns (success, error_message)."""
        try:
            if not os.path.exists(file_path):
                return False, f"{file_type} file not found: {file_path}"

            # Cross-platform file opening
            if platform.system() == "Windows":  # Windows
                os.startfile(file_path)
            elif platform.system() == "Darwin":  # macOS
                result = subprocess.run(
                    ["open", file_path], capture_output=True, text=True
                )
                if result.returncode != 0:
                    return False, f"Failed to open {file_type}: {result.stderr}"
            else:  # Linux and other Unix-like systems
                # Check if xdg-open is available
                try:
                    result = subprocess.run(
                        ["which", "xdg-open"], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return (
                            False,
                            "xdg-open not found. Please install xdg-utils.",
                        )

                    result = subprocess.run(
                        ["xdg-open", file_path], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return False, f"Failed to open {file_type}: {result.stderr}"
                except FileNotFoundError:
                    return (
                        False,
                        "xdg-open not found. Please install xdg-utils.",
                    )

            return True, ""

        except Exception as e:
            return False, f"Error opening {file_type}: {str(e)}"

    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to system clipboard."""
        pyperclip.copy(text)
        return True

    def download_pdf(
        self,
        source: str,
        identifier: str,
        download_dir: str,
        paper_data: Dict[str, Any] = None,
    ) -> Tuple[Optional[str], str, float]:
        """
        Download PDF from various sources (arXiv, OpenReview, etc.).

        Returns:
            tuple[Optional[str], str, float]: (pdf_path, error_message, download_duration_seconds)
            If successful: (path, "", duration)
            If error: (None, error_message, duration)
        """
        try:
            self.app._add_log(
                "system_download_start",
                f"SystemService.download_pdf called with source='{source}', identifier='{identifier}', download_dir='{download_dir}'",
            )

            # Create download directory
            os.makedirs(download_dir, exist_ok=True)
            self.app._add_log(
                "system_download_debug",
                f"Created/verified download directory: {download_dir}",
            )

            # Generate URL based on source
            if source == "arxiv":
                # Clean arXiv ID while preserving version numbers
                clean_id = re.sub(r"arxiv[:\s]*", "", identifier, flags=re.IGNORECASE)
                clean_id = re.sub(
                    r"[^\d\.v]", "", clean_id
                )  # Allow digits, dots, and 'v' for versions
                pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
                self.app._add_log(
                    "system_download_debug",
                    f"arXiv: original_id='{identifier}' -> clean_id='{clean_id}' -> url='{pdf_url}'",
                )
            elif source == "openreview":
                pdf_url = f"https://openreview.net/pdf?id={identifier}"
                self.app._add_log(
                    "system_download_debug",
                    f"OpenReview: identifier='{identifier}' -> url='{pdf_url}'",
                )
            else:
                error_msg = f"Unsupported source: {source}"
                self.app._add_log("system_download_error", error_msg)
                return None, error_msg

            # Use PDFManager to handle everything with proper naming
            self.app._add_log(
                "system_download_debug",
                f"Setting PDFManager pdf_dir to: {download_dir}",
            )
            self.pdf_manager.pdf_dir = download_dir  # Set download directory
            # Set app reference for PDFManager logging
            self.pdf_manager.app = self.app

            # Download with proper temp->final naming
            self.app._add_log(
                "system_download_debug",
                f"Calling PDFManager.download_pdf_from_url_with_proper_naming with url='{pdf_url}'",
            )

            pdf_path, error_msg, download_duration = (
                self.pdf_manager.download_pdf_from_url_with_proper_naming(
                    pdf_url, paper_data
                )
            )

            self.app._add_log(
                "system_download_timing",
                f"PDFManager operation took {download_duration:.2f} seconds",
            )

            self.app._add_log(
                "system_download_result",
                f"PDFManager result: pdf_path='{pdf_path}', error_msg='{error_msg}'",
            )

            if error_msg:
                self.app._add_log(
                    "system_download_error", f"PDF download failed: {error_msg}"
                )
                return None, error_msg, download_duration

            self.app._add_log(
                "system_download_success", f"PDF download successful: {pdf_path}"
            )
            return pdf_path, "", download_duration

        except Exception as e:
            error_msg = f"Error downloading PDF: {str(e)}\n{traceback.format_exc()}"
            self.app._add_log(
                "system_download_exception",
                f"Exception in SystemService.download_pdf: {error_msg}",
            )
            return None, error_msg, 0.0

    def open_file_location(self, file_path: str) -> Tuple[bool, str]:
        """Open file location in Finder/File Explorer and select the file. Returns (success, error_message)."""
        try:
            if not os.path.exists(file_path):
                return False, f"File not found: {file_path}"

            # Cross-platform file location opening
            if platform.system() == "Windows":  # Windows
                # Use explorer.exe with /select to highlight the file
                subprocess.run(["explorer.exe", "/select,", file_path], check=True)
            elif platform.system() == "Darwin":  # macOS
                # Use open -R to reveal in Finder
                result = subprocess.run(
                    ["open", "-R", file_path], capture_output=True, text=True
                )
                if result.returncode != 0:
                    return False, f"Failed to open file location: {result.stderr}"
            else:  # Linux and other Unix-like systems
                # Try to open the parent directory
                parent_dir = os.path.dirname(file_path)
                try:
                    result = subprocess.run(
                        ["which", "xdg-open"], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return (
                            False,
                            "xdg-open not found. Please install xdg-utils or set a file manager.",
                        )

                    result = subprocess.run(
                        ["xdg-open", parent_dir], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return False, f"Failed to open file location: {result.stderr}"
                except FileNotFoundError:
                    return (
                        False,
                        "xdg-open not found. Please install xdg-utils or set a file manager.",
                    )

            return True, ""

        except Exception as e:
            return False, f"Error opening file location: {str(e)}"
