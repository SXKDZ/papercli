"""Shared formatting utilities for PaperCLI."""

from typing import Any, Dict, List


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


def format_paper_title_preview(title: str, max_length: int = 120) -> str:
    """Format paper title for preview display with truncation."""
    if not title:
        return ""
    if len(title) <= max_length:
        return title
    return title[:max_length] + "..."


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


def format_download_summary(file_path: str, file_size: int, duration: float) -> str:
    """Create a comprehensive download summary string."""
    size_str = format_file_size(file_size)
    speed_str = format_download_speed(file_size / duration) if duration > 0 else "N/A"
    return f"{size_str} in {duration:.1f}s ({speed_str})"
