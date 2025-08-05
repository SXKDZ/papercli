"""PDF service - Business logic for PDF file management."""

import hashlib
import os
import re
import secrets
import shutil
from typing import Any, Dict, Tuple

from ..db.database import get_pdf_directory
from .http_utils import HTTPClient


class PDFManager:
    """Service for managing PDF files with smart naming and handling."""

    def __init__(self):
        self.pdf_dir = None
        self.pdf_dir = get_pdf_directory()

    def get_absolute_path(self, relative_path: str) -> str:
        """Convert a relative PDF path to absolute path."""
        if not relative_path:
            return ""

        # If path is already absolute, return as-is (for backward compatibility)
        if os.path.isabs(relative_path):
            return relative_path

        # Convert relative path to absolute
        return os.path.join(self.pdf_dir, relative_path)

    def _generate_pdf_filename(self, paper_data: Dict[str, Any], pdf_path: str) -> str:
        """Generate a smart filename for the PDF based on paper metadata."""
        # Extract first author last name
        authors = paper_data.get("authors", [])
        if authors and isinstance(authors[0], str):
            first_author = authors[0]
            # Extract last name (assume last word is surname)
            author_lastname = first_author.split()[-1].lower()
            # Remove non-alphanumeric characters
            author_lastname = re.sub(r"[^\w]", "", author_lastname)
        else:
            author_lastname = "unknown"

        # Extract year
        year = paper_data.get("year", "nodate")

        # Extract first significant word from title
        title = paper_data.get("title", "untitled")
        # Split into words and find first significant word (length > 3, not common words)
        common_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "day",
            "get",
            "has",
            "him",
            "his",
            "how",
            "its",
            "may",
            "new",
            "now",
            "old",
            "see",
            "two",
            "who",
            "boy",
            "did",
            "man",
            "run",
            "say",
            "she",
            "too",
            "use",
        }
        words = re.findall(r"\b[a-zA-Z]+\b", title.lower())
        first_word = "untitled"
        for word in words:
            if len(word) > 3 and word not in common_words:
                first_word = word
                break

        # Generate short hash from file content only
        try:
            if os.path.exists(pdf_path):
                # Hash from file content
                with open(pdf_path, "rb") as f:
                    content = f.read(8192)  # Read first 8KB for hash
                    file_hash = hashlib.md5(content).hexdigest()[:6]
            else:
                # For non-existent files (URLs), use a placeholder that will be replaced
                # when the file is actually downloaded and processed
                file_hash = "temp00"
        except Exception:
            # Fallback to random hash
            file_hash = secrets.token_hex(3)

        # Combine all parts
        filename = f"{author_lastname}{year}{first_word}_{file_hash}.pdf"

        # Ensure filename is filesystem-safe
        filename = re.sub(r"[^\w\-._]", "", filename)

        return filename

    def process_pdf_path(
        self, pdf_input: str, paper_data: Dict[str, Any], old_pdf_path: str = None
    ) -> Tuple[str, str]:
        """
        Process PDF input (local file, URL, or invalid) and return the final relative path.

        Returns:
            tuple[str, str]: (relative_pdf_path, error_message)
            If successful: (relative_path, "")
            If error: ("", error_message)
        """
        if not pdf_input or not pdf_input.strip():
            return "", "PDF path cannot be empty"

        pdf_input = pdf_input.strip()

        # Determine input type
        is_url = pdf_input.startswith(("http://", "https://"))
        is_local_file = os.path.exists(pdf_input) and os.path.isfile(pdf_input)

        if not is_url and not is_local_file:
            return (
                "",
                f"Invalid PDF input: '{pdf_input}' is neither a valid file path nor a URL",
            )

        try:
            if is_local_file:
                # Generate target filename
                target_filename = self._generate_pdf_filename(paper_data, pdf_input)
                target_path = os.path.join(self.pdf_dir, target_filename)

                # Copy local file to PDF directory
                # Check if source and destination are the same file
                if os.path.abspath(pdf_input) == os.path.abspath(target_path):
                    # File is already in the right place, no need to copy
                    relative_path = os.path.relpath(target_path, self.pdf_dir)
                    return relative_path, ""

                shutil.copy2(pdf_input, target_path)

                # Clean up old PDF only after successful copy
                if (
                    old_pdf_path
                    and os.path.exists(old_pdf_path)
                    and old_pdf_path != target_path
                ):
                    try:
                        os.remove(old_pdf_path)
                    except Exception:
                        pass  # Don't fail if cleanup fails

                # Return relative path from PDF directory
                relative_path = os.path.relpath(target_path, self.pdf_dir)
                return relative_path, ""

            elif is_url:
                # Download URL to PDF directory with proper naming
                new_path, error = self.download_pdf_from_url_with_proper_naming(
                    pdf_input, paper_data
                )

                if not error:
                    # Clean up old PDF only after successful download
                    if (
                        old_pdf_path
                        and os.path.exists(old_pdf_path)
                        and old_pdf_path != new_path
                    ):
                        try:
                            os.remove(old_pdf_path)
                        except Exception:
                            pass  # Don't fail if cleanup fails

                    # Return relative path from PDF directory
                    relative_path = os.path.relpath(new_path, self.pdf_dir)
                    return relative_path, error

                return "", error

        except Exception as e:
            return "", f"Error processing PDF: {str(e)}"

    def download_pdf_from_url_with_proper_naming(
        self, url: str, paper_data: Dict[str, Any]
    ) -> Tuple[str, str]:
        """
        Download PDF from URL with proper temp->final naming pattern.

        This function:
        1. Generates a temporary filename with random hash
        2. Downloads PDF to temp location
        3. Generates final filename based on content hash
        4. Renames to final location

        Returns:
            tuple[str, str]: (final_pdf_absolute_path, error_message)
            Note: This returns absolute path for internal use. The calling method converts to relative.
        """
        try:
            # Generate temporary filename with random hash
            temp_hash = secrets.token_hex(3)
            author_lastname = "unknown"
            year = "0000"
            first_word = "paper"

            if paper_data.get("authors"):
                if isinstance(paper_data["authors"], list) and paper_data["authors"]:
                    author_lastname = paper_data["authors"][0].split()[-1].lower()[:10]
            if paper_data.get("year"):
                year = str(paper_data["year"])
            if paper_data.get("title"):
                words = paper_data["title"].lower().split()
                first_word = next((w for w in words if len(w) > 3), "paper")[:10]

            temp_filename = f"{author_lastname}{year}{first_word}_{temp_hash}.pdf"
            temp_filepath = os.path.join(self.pdf_dir, temp_filename)

            # Download to temporary path
            downloaded_path, error = self._download_pdf_from_url(url, temp_filepath)
            if error:
                return "", error

            # Generate final filename with content-based hash
            final_filename = self._generate_pdf_filename(paper_data, downloaded_path)
            final_filepath = os.path.join(self.pdf_dir, final_filename)

            # Rename to final location if needed
            if temp_filepath != final_filepath:
                try:
                    shutil.move(temp_filepath, final_filepath)
                    return final_filepath, ""
                except Exception as e:
                    # If move fails, keep the temporary file
                    return (
                        temp_filepath,
                        f"Warning: Could not rename to final filename: {e}",
                    )

            return downloaded_path, ""

        except Exception as e:
            return "", f"Error in PDF download with proper naming: {str(e)}"

    def _download_pdf_from_url(self, url: str, target_path: str) -> Tuple[str, str]:
        """Download PDF from URL to target path using HTTPClient."""
        try:
            response = HTTPClient.get(url, timeout=60, stream=True)

            # Check if content is actually a PDF
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" not in content_type:
                # Check first few bytes for PDF signature
                first_chunk = next(response.iter_content(chunk_size=1024), b"")
                if not first_chunk.startswith(b"%PDF"):
                    # Provide more detailed error information
                    content_preview = first_chunk[:100].decode("utf-8", errors="ignore")
                    return (
                        "",
                        f"URL does not point to a valid PDF file.\nContent-Type: {content_type}\nContent preview: {content_preview}...",
                    )

            # Download the file
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return target_path, ""

        except Exception as e:
            return "", f"Failed to download PDF from URL: {str(e)}"
