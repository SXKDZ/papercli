from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import time
from typing import Any, Dict, Tuple

from ng.db.database import get_pdf_directory
from ng.services import HTTPClient


class PDFService:
    """Centralized service for PDF operations including download, copy, and info management."""

    def __init__(self, app=None):
        self.pdf_dir = get_pdf_directory()
        self.app = app

    def calculate_file_size_formatted(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def get_pdf_page_count(self, pdf_path: str) -> int:
        """Get page count from PDF file."""
        try:
            import PyPDF2
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return len(pdf_reader.pages)
        except ImportError:
            return 0
        except Exception:
            return 0

    def format_download_duration(self, duration_seconds: float) -> str:
        """Format download duration in human readable format."""
        if duration_seconds < 60:
            return f"{duration_seconds:.1f} seconds"
        else:
            minutes = int(duration_seconds // 60)
            seconds = duration_seconds % 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} {seconds:.0f} seconds"

    def create_download_summary(self, pdf_path: str, duration_seconds: float) -> str:
        """Create a summary string for download completion notification."""
        try:
            if not os.path.exists(pdf_path):
                return "Download completed"
            
            file_size = os.path.getsize(pdf_path)
            size_formatted = self.calculate_file_size_formatted(file_size)
            duration_formatted = self.format_download_duration(duration_seconds)
            page_count = self.get_pdf_page_count(pdf_path)
            
            if page_count > 0:
                return f"Download completed: {size_formatted}, {duration_formatted}, {page_count} pages"
            else:
                return f"Download completed: {size_formatted}, {duration_formatted}"
        except Exception:
            return "Download completed"

    def download_pdf_from_website_url(self, url: str, paper_data: Dict[str, Any]) -> Tuple[str, str, float]:
        """
        Download PDF from a website URL (for RIS/BIB files that contain PDF URLs).
        
        Returns:
            tuple[str, str, float]: (pdf_path, error_message, download_duration_seconds)
        """
        try:
            if self.app:
                self.app._add_log("website_download_start", f"Attempting to download PDF from website URL: {url}")
            
            start_time = time.time()
            
            # Check if URL looks like it might be a PDF
            if not self._is_potential_pdf_url(url):
                error_msg = f"URL does not appear to be a PDF link: {url}"
                if self.app:
                    self.app._add_log("website_download_error", error_msg)
                return "", error_msg, 0.0
            
            # Generate temporary filename
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
            download_duration = time.time() - start_time
            
            if error:
                if self.app:
                    self.app._add_log("website_download_error", f"PDF download failed: {error}")
                return "", error, download_duration

            # Generate final filename with content-based hash
            final_filename = self._generate_pdf_filename(paper_data, downloaded_path)
            final_filepath = os.path.join(self.pdf_dir, final_filename)
            
            # Rename to final location if needed
            if temp_filepath != final_filepath:
                try:
                    shutil.move(temp_filepath, final_filepath)
                    if self.app:
                        self.app._add_log("website_download_success", f"Successfully downloaded and renamed to: {final_filepath}")
                    return final_filepath, "", download_duration
                except Exception as e:
                    # If move fails, keep the temporary file
                    warning_msg = f"Warning: Could not rename to final filename: {e}"
                    if self.app:
                        self.app._add_log("website_download_warning", warning_msg)
                    return temp_filepath, warning_msg, download_duration

            return downloaded_path, "", download_duration

        except Exception as e:
            download_duration = time.time() - start_time if 'start_time' in locals() else 0.0
            error_msg = f"Error downloading PDF from website: {str(e)}"
            if self.app:
                import traceback
                self.app._add_log("website_download_exception", f"Exception: {error_msg}")
                self.app._add_log("website_download_traceback", f"Traceback: {traceback.format_exc()}")
            return "", error_msg, download_duration

    def _is_potential_pdf_url(self, url: str) -> bool:
        """Check if a URL might be a PDF based on common patterns."""
        url_lower = url.lower()
        
        # Direct PDF file extension
        if url_lower.endswith('.pdf'):
            return True
        
        # Common PDF hosting patterns
        pdf_patterns = [
            'arxiv.org/pdf/',
            'openreview.net/pdf',
            'proceedings.mlr.press/',
            'papers.nips.cc/',
            'aclanthology.org/',
            '/pdf/',
            'download.pdf',
            'view=pdf',
            'filetype=pdf'
        ]
        
        return any(pattern in url_lower for pattern in pdf_patterns)

    def copy_local_pdf_to_collection(self, source_path: str, paper_data: Dict[str, Any]) -> Tuple[str, str, float]:
        """
        Copy a local PDF file to the PDF collection directory.
        
        Returns:
            tuple[str, str, float]: (relative_pdf_path, error_message, copy_duration_seconds)
        """
        try:
            if self.app:
                self.app._add_log("pdf_copy_start", f"Copying local PDF from: {source_path}")
            
            start_time = time.time()
            
            # Expand and validate source path
            source_path = os.path.expanduser(source_path)
            source_path = os.path.abspath(source_path)
            
            if not os.path.exists(source_path):
                error_msg = f"Source PDF file not found: {source_path}"
                if self.app:
                    self.app._add_log("pdf_copy_error", error_msg)
                return "", error_msg, 0.0
            
            if not source_path.lower().endswith('.pdf'):
                error_msg = f"File is not a PDF: {source_path}"
                if self.app:
                    self.app._add_log("pdf_copy_error", error_msg)
                return "", error_msg, 0.0
            
            # Generate target filename
            target_filename = self._generate_pdf_filename(paper_data, source_path)
            target_path = os.path.join(self.pdf_dir, target_filename)
            
            # Check if source and destination are the same file
            if os.path.abspath(source_path) == os.path.abspath(target_path):
                # File is already in the right place, no need to copy
                relative_path = os.path.relpath(target_path, self.pdf_dir)
                copy_duration = time.time() - start_time
                if self.app:
                    self.app._add_log("pdf_copy_info", f"File already in correct location: {relative_path}")
                return relative_path, "", copy_duration
            
            # Copy the file
            shutil.copy2(source_path, target_path)
            copy_duration = time.time() - start_time
            
            # Return relative path from PDF directory
            relative_path = os.path.relpath(target_path, self.pdf_dir)
            
            if self.app:
                self.app._add_log("pdf_copy_success", f"Successfully copied PDF to: {relative_path}")
            
            return relative_path, "", copy_duration
            
        except Exception as e:
            copy_duration = time.time() - start_time if 'start_time' in locals() else 0.0
            error_msg = f"Error copying PDF file: {str(e)}"
            if self.app:
                import traceback
                self.app._add_log("pdf_copy_exception", f"Exception: {error_msg}")
                self.app._add_log("pdf_copy_traceback", f"Traceback: {traceback.format_exc()}")
            return "", error_msg, copy_duration


class PDFManager:
    """Service for managing PDF files with smart naming and handling."""

    def __init__(self, app=None):
        self.pdf_dir = None
        self.pdf_dir = get_pdf_directory()
        self.app = app

    def get_absolute_path(self, relative_path: str) -> str:
        """Convert a relative PDF path to absolute path."""
        if not relative_path:
            return ""

        # If path is already absolute, return as-is (for backward compatibility)
        if os.path.isabs(relative_path):
            return relative_path

        # Convert relative path to absolute
        return os.path.join(self.pdf_dir, relative_path)

    def get_relative_path(self, absolute_path: str) -> str:
        """Convert an absolute PDF path to relative path."""
        if not absolute_path:
            return ""
        
        # If path is already relative, return as-is
        if not os.path.isabs(absolute_path):
            return absolute_path
        
        # Convert absolute path to relative
        try:
            return os.path.relpath(absolute_path, self.pdf_dir)
        except ValueError:
            # If path is outside pdf_dir, just return the filename
            return os.path.basename(absolute_path)

    def get_pdfs_directory(self) -> str:
        """Get the absolute path to the PDFs directory."""
        return self.pdf_dir

    def get_pdf_info(self, relative_path: str) -> Dict[str, Any]:
        """Get PDF file information including size and page count."""
        info = {
            "exists": False,
            "size_bytes": 0,
            "size_formatted": "Unknown",
            "page_count": 0,
            "error": None
        }
        
        if not relative_path:
            info["error"] = "No PDF path provided"
            return info
        
        absolute_path = self.get_absolute_path(relative_path)
        
        if not os.path.exists(absolute_path):
            info["error"] = "PDF file not found"
            return info
        
        try:
            # Get file size
            file_size = os.path.getsize(absolute_path)
            info["size_bytes"] = file_size
            info["exists"] = True
            
            # Format file size
            if file_size < 1024:
                info["size_formatted"] = f"{file_size} B"
            elif file_size < 1024 * 1024:
                info["size_formatted"] = f"{file_size / 1024:.1f} KB"
            elif file_size < 1024 * 1024 * 1024:
                info["size_formatted"] = f"{file_size / (1024 * 1024):.1f} MB"
            else:
                info["size_formatted"] = f"{file_size / (1024 * 1024 * 1024):.1f} GB"
            
            # Get page count using PyPDF2
            try:
                import PyPDF2
                with open(absolute_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    info["page_count"] = len(pdf_reader.pages)
            except ImportError:
                info["error"] = "PyPDF2 not available for page count"
            except Exception as e:
                info["error"] = f"Could not read PDF: {str(e)}"
                # Still return file size even if page count fails
                
        except Exception as e:
            info["error"] = f"Error accessing PDF file: {str(e)}"
        
        return info

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
    ) -> Tuple[str, str, float]:
        """
        Download PDF from URL with proper temp->final naming pattern.

        This function:
        1. Generates a temporary filename with random hash
        2. Downloads PDF to temp location
        3. Generates final filename based on content hash
        4. Renames to final location

        Returns:
            tuple[str, str, float]: (final_pdf_absolute_path, error_message, download_duration_seconds)
            Note: This returns absolute path for internal use. The calling method converts to relative.
        """
        try:
            if self.app:
                self.app._add_log("pdf_manager_start", f"PDFManager.download_pdf_from_url_with_proper_naming called with url='{url}'")
                self.app._add_log("pdf_manager_debug", f"Paper data for naming: {paper_data}")
            
            start_time = time.time()
            
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
            
            if self.app:
                self.app._add_log("pdf_manager_debug", f"Generated temp filename: {temp_filename}")
                self.app._add_log("pdf_manager_debug", f"Full temp path: {temp_filepath}")

            # Download to temporary path
            if self.app:
                self.app._add_log("pdf_manager_debug", "Starting download to temp path...")
            downloaded_path, error = self._download_pdf_from_url(url, temp_filepath)
            download_duration = time.time() - start_time
            
            if self.app:
                self.app._add_log("pdf_manager_result", f"Download result: downloaded_path='{downloaded_path}', error='{error}'")
            
            if error:
                if self.app:
                    self.app._add_log("pdf_manager_error", f"PDF download failed: {error}")
                return "", error, download_duration

            if self.app:
                self.app._add_log("pdf_manager_success", f"PDF downloaded successfully to: {downloaded_path}")

            # Generate final filename with content-based hash
            if self.app:
                self.app._add_log("pdf_manager_debug", "Generating final filename based on content...")
            final_filename = self._generate_pdf_filename(paper_data, downloaded_path)
            final_filepath = os.path.join(self.pdf_dir, final_filename)
            
            if self.app:
                self.app._add_log("pdf_manager_debug", f"Final filename: {final_filename}")
                self.app._add_log("pdf_manager_debug", f"Final filepath: {final_filepath}")

            # Rename to final location if needed
            if temp_filepath != final_filepath:
                if self.app:
                    self.app._add_log("pdf_manager_debug", "Renaming from temp to final location...")
                try:
                    shutil.move(temp_filepath, final_filepath)
                    if self.app:
                        self.app._add_log("pdf_manager_success", f"Successfully renamed to: {final_filepath}")
                    return final_filepath, "", download_duration
                except Exception as e:
                    # If move fails, keep the temporary file
                    warning_msg = f"Warning: Could not rename to final filename: {e}"
                    if self.app:
                        self.app._add_log("pdf_manager_warning", warning_msg)
                    return temp_filepath, warning_msg, download_duration
            else:
                if self.app:
                    self.app._add_log("pdf_manager_debug", "Temp and final paths are the same, no rename needed")

            return downloaded_path, "", download_duration

        except Exception as e:
            download_duration = time.time() - start_time if 'start_time' in locals() else 0.0
            error_msg = f"Error in PDF download with proper naming: {str(e)}"
            if self.app:
                import traceback
                self.app._add_log("pdf_manager_exception", f"Exception in download_pdf_from_url_with_proper_naming: {error_msg}")
                self.app._add_log("pdf_manager_traceback", f"Traceback: {traceback.format_exc()}")
            return "", error_msg, download_duration

    def _download_pdf_from_url(self, url: str, target_path: str) -> Tuple[str, str]:
        """Download PDF from URL to target path using HTTPClient."""
        try:
            if self.app:
                self.app._add_log("http_request_start", f"Starting HTTP request to: {url}")
            
            import time
            request_start = time.time()
            response = HTTPClient.get(url, timeout=60, stream=True)
            request_duration = time.time() - request_start
            
            if self.app:
                self.app._add_log("http_request_timing", f"HTTP request completed in {request_duration:.2f} seconds")
                self.app._add_log("http_response_debug", f"HTTP response status: {response.status_code}")
                self.app._add_log("http_response_debug", f"HTTP response headers: {dict(response.headers)}")

            # Check if content is actually a PDF
            content_type = response.headers.get("content-type", "").lower()
            if self.app:
                self.app._add_log("http_content_debug", f"Content-Type: {content_type}")
            
            if "pdf" not in content_type:
                if self.app:
                    self.app._add_log("http_content_debug", "Content-Type does not indicate PDF, checking content...")
                # Check first few bytes for PDF signature
                first_chunk = next(response.iter_content(chunk_size=1024), b"")
                if self.app:
                    self.app._add_log("http_content_debug", f"First chunk size: {len(first_chunk)} bytes")
                
                if not first_chunk.startswith(b"%PDF"):
                    # Provide more detailed error information
                    content_preview = first_chunk[:100].decode("utf-8", errors="ignore")
                    error_msg = f"URL does not point to a valid PDF file.\nContent-Type: {content_type}\nContent preview: {content_preview}..."
                    if self.app:
                        self.app._add_log("http_content_error", error_msg)
                    return "", error_msg
                else:
                    if self.app:
                        self.app._add_log("http_content_debug", "Content starts with PDF signature despite Content-Type")

            if self.app:
                self.app._add_log("file_write_start", f"Starting file write to: {target_path}")
            
            # Get content length for progress tracking
            content_length = response.headers.get('content-length')
            total_size = int(content_length) if content_length else None
            
            if self.app:
                if total_size:
                    self.app._add_log("download_progress", f"PDF size: {total_size:,} bytes ({total_size/1024/1024:.1f} MB)")
                else:
                    self.app._add_log("download_progress", "PDF size: Unknown (no Content-Length header)")
            
            # Download the file with progress tracking
            total_bytes = 0
            chunk_count = 0
            import time
            start_time = time.time()
            last_progress_log = 0
            
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)
                        chunk_count += 1
                        
                        # Log progress every 10% or every 50 chunks (whichever comes first)
                        if total_size:
                            progress_percent = (total_bytes / total_size) * 100
                            if progress_percent - last_progress_log >= 10:  # Every 10%
                                elapsed = time.time() - start_time
                                speed = total_bytes / elapsed if elapsed > 0 else 0
                                speed_mb = speed / 1024 / 1024
                                
                                if self.app:
                                    self.app._add_log("download_progress", f"Downloaded {progress_percent:.1f}% ({total_bytes:,}/{total_size:,} bytes) at {speed_mb:.1f} MB/s")
                                last_progress_log = progress_percent
                        elif chunk_count % 50 == 0:  # Every 50 chunks when size unknown
                            elapsed = time.time() - start_time
                            speed = total_bytes / elapsed if elapsed > 0 else 0
                            speed_mb = speed / 1024 / 1024
                            
                            if self.app:
                                self.app._add_log("download_progress", f"Downloaded {total_bytes:,} bytes ({chunk_count} chunks) at {speed_mb:.1f} MB/s")

            elapsed = time.time() - start_time
            avg_speed = total_bytes / elapsed if elapsed > 0 else 0
            avg_speed_mb = avg_speed / 1024 / 1024
            
            if self.app:
                self.app._add_log("file_write_success", f"Successfully downloaded {total_bytes:,} bytes to: {target_path}")
                self.app._add_log("download_stats", f"Total time: {elapsed:.1f}s, Average speed: {avg_speed_mb:.1f} MB/s")
            
            # Verify file was created and has content
            if os.path.exists(target_path):
                file_size = os.path.getsize(target_path)
                if self.app:
                    self.app._add_log("file_verify_debug", f"Downloaded file size: {file_size} bytes")
                if file_size == 0:
                    if self.app:
                        self.app._add_log("file_verify_error", "Downloaded file is empty")
                    return "", "Downloaded PDF file is empty"
            else:
                if self.app:
                    self.app._add_log("file_verify_error", f"Downloaded file was not created at: {target_path}")
                return "", "Downloaded file was not created"

            return target_path, ""

        except Exception as e:
            error_msg = f"Failed to download PDF from URL: {str(e)}"
            if self.app:
                import traceback
                self.app._add_log("http_download_exception", f"Exception in _download_pdf_from_url: {error_msg}")
                self.app._add_log("http_download_traceback", f"Traceback: {traceback.format_exc()}")
            return "", error_msg
