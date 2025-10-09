"""Handlers for tracking and formatting paper field changes."""

from typing import Any, Dict, List

from ng.services.formatting import (
    format_authors_list,
    format_collections_list,
    format_field_change,
)


def extract_original_fields(paper) -> Dict[str, Any]:
    """Extract original simple fields from a paper object."""
    simple_fields = [
        "title",
        "year",
        "pages",
        "volume",
        "issue",
        "doi",
        "url",
        "arxiv_id",
        "dblp_id",
        "venue_full",
        "venue_acronym",
        "abstract",
        "notes",
        "paper_type",
        "pdf_path",
    ]

    return {key: getattr(paper, key, None) for key in simple_fields}


def extract_original_authors(paper) -> List[str]:
    """Extract original author names from a paper object."""
    try:
        return [pa.author.full_name for pa in (paper.paper_authors or [])]
    except Exception:
        return []


def extract_original_collections(paper) -> List[str]:
    """Extract original collection names from a paper object."""
    try:
        return [c.name for c in (paper.collections or [])]
    except Exception:
        return []


def compare_simple_fields(original_fields: Dict[str, Any], updated_paper) -> List[str]:
    """Compare simple fields and return list of change descriptions."""
    changes = []

    for key, old_value in original_fields.items():
        new_value = getattr(updated_paper, key, None)
        if str(old_value) != str(new_value):
            change_description = format_field_change(key, old_value, new_value)
            changes.append(change_description)

    return changes


def compare_authors(original_authors: List[str], updated_paper) -> List[str]:
    """Compare authors and return list of change descriptions."""
    changes = []

    try:
        updated_authors = [
            pa.author.full_name for pa in (updated_paper.paper_authors or [])
        ]
    except Exception:
        updated_authors = original_authors

    if original_authors != updated_authors:
        old_authors_str = format_authors_list(original_authors)
        new_authors_str = format_authors_list(updated_authors)
        changes.append(f"authors: '{old_authors_str}' → '{new_authors_str}'")

    return changes


def compare_collections(original_collections: List[str], updated_paper) -> List[str]:
    """Compare collections and return list of change descriptions."""
    changes = []

    updated_collections = [c.name for c in (updated_paper.collections or [])]
    if original_collections != updated_collections:
        old_collections_str = format_collections_list(original_collections)
        new_collections_str = format_collections_list(updated_collections)
        changes.append(
            f"collections: '{old_collections_str}' → '{new_collections_str}'"
        )

    return changes


def build_complete_change_log(
    original_fields: Dict[str, Any],
    original_authors: List[str],
    original_collections: List[str],
    updated_paper,
) -> List[str]:
    """Build a complete change log for a paper update."""
    all_changes = []

    # Compare simple fields
    all_changes.extend(compare_simple_fields(original_fields, updated_paper))

    # Compare authors
    all_changes.extend(compare_authors(original_authors, updated_paper))

    # Compare collections
    all_changes.extend(compare_collections(original_collections, updated_paper))

    return all_changes


def format_change_log_details(paper_id: int, changes: List[str]) -> str:
    """Format change log details for logging."""
    if not changes:
        return ""
    return f"Paper ID {paper_id}: " + "; ".join(changes)
