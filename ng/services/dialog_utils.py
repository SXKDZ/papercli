"""
Dialog utility functions used across multiple dialog components.
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ng.services.pdf import PDFManager


class DialogUtilsService:
    """Service for common dialog utilities and operations."""

    @staticmethod
    def get_paper_fields(paper) -> Dict[str, Any]:
        """
        Extract common paper fields in a consistent format.
        Used by chat.py and detail.py.

        Args:
            paper: Paper object with various attributes

        Returns:
            Dictionary with standardized field names and values
        """
        return {
            "title": getattr(paper, "title", "Unknown Title"),
            "authors": getattr(paper, "author_names", "Unknown Authors"),
            "venue": getattr(paper, "venue_full", "Unknown Venue"),
            "year": getattr(paper, "year", "Unknown Year"),
            "abstract": getattr(paper, "abstract", "") or "",
            "notes": (getattr(paper, "notes", "") or "").strip(),
            "pdf_path": getattr(paper, "pdf_path", ""),
        }

    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """
        Mask API key for display in dialogs.
        Used by config.py.

        Args:
            api_key: The API key to mask

        Returns:
            Masked API key string
        """
        if not api_key:
            return ""
        if len(api_key) <= 12:
            return "****"
        return api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]

    @staticmethod
    def unmask_api_key(masked_key: str, original_key: str) -> str:
        """
        Unmask API key if it hasn't been changed.
        Used by config.py.

        Args:
            masked_key: The potentially masked key from input
            original_key: The original unmasked key

        Returns:
            The actual key value to use
        """
        if not masked_key or masked_key == "****":
            return ""
        if "*" not in masked_key:
            return masked_key  # New key entered
        # If it's still masked, return original
        return original_key

    @staticmethod
    def generate_filename_from_paper(paper, extension: str = ".md") -> str:
        """
        Generate a filename from paper data with timestamp.
        Used by chat.py for chat filename generation.

        Args:
            paper: Paper object or dict with paper data
            extension: File extension to use

        Returns:
            Generated filename with timestamp
        """
        pdf_manager = PDFManager()
        fields = DialogUtilsService.get_paper_fields(paper)

        # Parse authors string into list
        authors_list = []
        if fields["authors"] and fields["authors"] != "Unknown Authors":
            authors_list = [name.strip() for name in fields["authors"].split(",")]

        # Create paper data dict for filename generation
        paper_data = {
            "title": fields["title"],
            "authors": authors_list,
            "year": fields["year"] if fields["year"] != "Unknown Year" else None,
        }

        pdf_filename = pdf_manager._generate_pdf_filename(paper_data, "")
        # Remove the hash part and add timestamp
        base_filename = pdf_filename.rsplit("_", 1)[0]  # Remove hash
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base_filename}_{timestamp}{extension}"

    @staticmethod
    def get_data_directory() -> Path:
        """
        Get the papercli data directory path.
        Used by multiple dialogs for file operations.

        Returns:
            Path to the data directory
        """
        data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
        if data_dir_env:
            data_dir = Path(data_dir_env).expanduser().resolve()
        else:
            data_dir = Path.home() / ".papercli"

        return data_dir

    @staticmethod
    def create_safe_filename(filename: str, directory: Path) -> Path:
        """
        Create a safe filename that doesn't conflict with existing files.
        Used by chat.py and potentially other dialogs for file saving.

        Args:
            filename: Base filename to use
            directory: Directory where file will be saved

        Returns:
            Path object with a unique filename
        """
        directory.mkdir(exist_ok=True, parents=True)

        filepath = directory / filename

        # Handle filename conflicts
        counter = 1
        base_name = filepath.stem
        extension = filepath.suffix
        final_filepath = filepath

        while final_filepath.exists():
            final_filename = f"{base_name}_{counter:02d}{extension}"
            final_filepath = directory / final_filename
            counter += 1

        return final_filepath

    @staticmethod
    def validate_numeric_input(
        value: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        input_type: str = "float",
    ) -> tuple[bool, str, Optional[float]]:
        """
        Validate numeric input with optional range checking.
        Used by config.py and edit.py for numeric field validation.

        Args:
            value: String value to validate
            min_val: Minimum allowed value (optional)
            max_val: Maximum allowed value (optional)
            input_type: "int" or "float" for type conversion

        Returns:
            Tuple of (is_valid, error_message, converted_value)
        """
        if not value.strip():
            return False, "Value cannot be empty", None

        try:
            if input_type == "int":
                converted = int(value)
            else:
                converted = float(value)

            if min_val is not None and converted < min_val:
                return False, f"Value must be at least {min_val}", None

            if max_val is not None and converted > max_val:
                return False, f"Value must be at most {max_val}", None

            return True, "", converted

        except ValueError:
            return False, f"Invalid {input_type} value", None

    @staticmethod
    def is_double_click(
        item_id: str, last_click_times: Dict[str, float], threshold: float = 0.5
    ) -> bool:
        """
        Check if a click constitutes a double-click.
        Used by collect.py for edit mode detection.

        Args:
            item_id: Unique identifier for the clicked item
            last_click_times: Dictionary storing last click times
            threshold: Time threshold for double-click detection

        Returns:
            True if this is a double-click
        """
        current_time = time.time()
        last_time = last_click_times.get(item_id, 0.0)
        is_double = (current_time - last_time) < threshold
        last_click_times[item_id] = current_time
        return is_double
