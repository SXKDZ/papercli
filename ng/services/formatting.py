"""Shared formatting utilities for PaperCLI."""

# Shared display constants
from typing import Any, List

TITLE_PREVIEW_WORDS = 10
TITLE_PREVIEW_CHARS = 50


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def format_authors_list(authors: List[str]) -> str:
    """Format a list of author names into a readable string."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    elif len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    else:
        return f"{', '.join(authors[:-1])}, and {authors[-1]}"


def format_title_by_words(title: str, max_words: int = TITLE_PREVIEW_WORDS) -> str:
    """Format a title by limiting to a maximum number of words.

    Keeps whole words and appends an ellipsis when truncated.
    """
    if not title:
        return ""
    words = str(title).split()
    if len(words) <= max_words:
        return title
    return " ".join(words[:max_words]) + "..."


def format_field_change(
    field_name: str, old_value: Any, new_value: Any, max_preview_length: int = 120
) -> str:
    """Format a field change for logging/display purposes."""
    old_preview = str(old_value) if old_value is not None else ""
    new_preview = str(new_value) if new_value is not None else ""

    if (
        field_name == "notes"
        or len(old_preview) > max_preview_length
        or len(new_preview) > max_preview_length
    ):
        if len(old_preview) > max_preview_length:
            old_preview = old_preview[:max_preview_length] + "..."
        if len(new_preview) > max_preview_length:
            new_preview = new_preview[:max_preview_length] + "..."

    return f"{field_name}: '{old_preview}' → '{new_preview}'"


def format_collections_list(collections: List[str]) -> str:
    """Format a list of collection names into a readable string."""
    if not collections:
        return "None"
    return ", ".join(collections)


def format_download_speed(bytes_per_second: float) -> str:
    """Format download speed in MB/s."""
    if bytes_per_second <= 0:
        return "0.0 MB/s"
    mb_per_second = bytes_per_second / (1024 * 1024)
    return f"{mb_per_second:.1f} MB/s"
