"""Common utility functions for the services package."""

import re

from titlecase import titlecase
from typing import Optional


def fix_broken_lines(text: str) -> str:
    """Fix broken lines in text - join lines that are not proper sentence endings."""
    if not text:
        return text
    text = re.sub(r"\n(?![A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compare_extracted_metadata_with_paper(extracted_data, paper, paper_service=None):
    """
    Compare extracted PDF metadata with current paper data and return list of changes.

    Args:
        extracted_data: Dictionary of extracted metadata from PDF
        paper: Paper object or paper data dict
        paper_service: Optional PaperService to fetch fresh paper data

    Returns:
        List of change strings in format "field_name: 'old_value' → 'new_value'"
    """
    if paper_service and hasattr(paper, "id"):
        fresh_paper = paper_service.get_paper_by_id(paper.id)
        if fresh_paper:
            paper = fresh_paper

    field_mapping = {
        "title": "title",
        "authors": "author_names",
        "abstract": "abstract",
        "year": "year",
        "venue_full": "venue_full",
        "venue_acronym": "venue_acronym",
        "doi": "doi",
        "url": "url",
        "category": "category",
    }

    changes = []

    for extracted_field, paper_field in field_mapping.items():
        if extracted_field in extracted_data and extracted_data[extracted_field]:
            value = extracted_data[extracted_field]

            if extracted_field == "authors" and isinstance(value, list):
                value = ", ".join(value)
            elif extracted_field == "year" and isinstance(value, int):
                value = str(value)

            if paper_field == "author_names":
                current_value = ""
                try:
                    if (
                        hasattr(paper, "paper_authors")
                        and paper.paper_authors is not None
                    ):
                        # Paper model object - use paper_authors to avoid lazy loading issues
                        current_value = (
                            ", ".join(
                                [
                                    paper_author.author.full_name
                                    for paper_author in paper.paper_authors
                                ]
                            )
                            if paper.paper_authors
                            else ""
                        )
                    elif hasattr(paper, "authors") and paper.authors is not None:
                        # Paper model object with authors relationship
                        current_value = (
                            ", ".join([author.full_name for author in paper.authors])
                            if paper.authors
                            else ""
                        )
                    elif hasattr(paper, "get"):
                        # Paper data dict (from edit dialog)
                        authors = paper.get("authors", [])
                        if isinstance(authors, list):
                            # Try both 'full_name' and 'name' attributes for compatibility
                            current_value = ", ".join(
                                [
                                    getattr(a, "full_name", getattr(a, "name", str(a)))
                                    for a in authors
                                ]
                            )
                        else:
                            current_value = str(authors) if authors else ""
                except (AttributeError, Exception) as e:
                    # If we can't access the authors due to session issues, skip this comparison
                    if hasattr(paper, "title"):
                        paper_title = getattr(paper, "title", "Unknown")
                    else:
                        paper_title = str(paper)[:50]
                    print(
                        f"[Session Error] Could not access authors for paper '{paper_title}': {e}"
                    )
                    current_value = ""
            else:
                if hasattr(paper, paper_field):
                    current_value = getattr(paper, paper_field, "") or ""
                else:
                    current_value = paper.get(paper_field, "") or ""

                if current_value is None:
                    current_value = ""
                else:
                    current_value = str(current_value)

            if str(value) != str(current_value):
                changes.append(f"{paper_field}: '{current_value}' → '{value}'")

    return changes


def normalize_author_names(author_list):
    """Normalize author names from various formats.

    Handles formats like:
    - "Lastname, Firstname Middle, Lastname2, Firstname2" (comma-separated pairs)
    - "Lastname, Firstname M., Lastname2, Firstname2 K." (with middle initials)
    - ["Name1", "Name2"] (already split list)
    - "Name1 and Name2" (BibTeX format)

    Returns:
        List of normalized "Firstname Middle Lastname" strings
    """
    if not author_list:
        return []

    if isinstance(author_list, str):
        author_text = author_list.strip()
        author_text = re.sub(r"\s+", " ", author_text)

        parts = [part.strip() for part in author_text.split(",")]

        if len(parts) >= 2 and len(parts) % 2 == 0:
            looks_like_lastname_firstname = True

            for i in range(0, len(parts), 2):
                if i + 1 < len(parts):
                    potential_lastname = parts[i].strip()
                    potential_firstname = parts[i + 1].strip()

                    lastname_words = potential_lastname.split()
                    firstname_words = potential_firstname.split()

                    if len(lastname_words) > 2 or len(firstname_words) == 0:
                        looks_like_lastname_firstname = False
                        break

            if looks_like_lastname_firstname:
                normalized_authors = []
                for i in range(0, len(parts), 2):
                    if i + 1 < len(parts):
                        lastname = parts[i].strip()
                        firstname_middle = parts[i + 1].strip()
                        if lastname and firstname_middle:
                            normalized_authors.append(f"{firstname_middle} {lastname}")

                if normalized_authors:
                    return normalized_authors

        if " and " in author_text:
            authors = []
            for author in author_text.split(" and "):
                author = author.strip()
                if author:
                    if "," in author:
                        parts = [p.strip() for p in author.split(",", 1)]
                        if len(parts) == 2:
                            lastname, firstname = parts
                            author = f"{firstname} {lastname}"
                    authors.append(author)
            return authors
        else:
            if author_text:
                if "," in author_text:
                    parts = [p.strip() for p in author_text.split(",", 1)]
                    if len(parts) == 2:
                        lastname, firstname = parts
                        return [f"{firstname} {lastname}"]
                return [author_text]
            return []

    elif isinstance(author_list, list):
        return [str(author).strip() for author in author_list if str(author).strip()]

    return []


def normalize_paper_data(paper_data: dict) -> dict:
    """Normalize paper data for database storage.

    Applies various normalizations:
    - Title: Fixes broken lines and converts to proper title case
    - Pages: Converts double dashes (--) and en-dashes (–) to single dashes (-)
    - Abstract: Fixes broken lines and formatting
    - Authors: Normalizes author names to consistent format

    Args:
        paper_data: Dictionary containing paper fields

    Returns:
        Normalized paper data dictionary
    """
    normalized_data = paper_data.copy()

    if normalized_data.get("title"):
        normalized_data["title"] = fix_broken_lines(normalized_data["title"])
        normalized_data["title"] = titlecase(normalized_data["title"])

    if normalized_data.get("pages"):
        normalized_data["pages"] = (
            normalized_data["pages"].replace("--", "-").replace("–", "-")
        )

    if normalized_data.get("abstract"):
        normalized_data["abstract"] = fix_broken_lines(normalized_data["abstract"])

    if normalized_data.get("authors"):
        normalized_data["authors"] = normalize_author_names(normalized_data["authors"])

    return normalized_data


def format_count(count: int, singular: str, plural: Optional[str] = None, include_number: bool = True) -> str:
    """Return a properly pluralized count string.

    Examples:
        format_count(1, "paper") -> "1 paper"
        format_count(2, "paper") -> "2 papers"
        format_count(1, "collection") -> "1 collection"
        format_count(3, "collection", "collections") -> "3 collections"

    Args:
        count: The numeric count.
        singular: The singular form of the noun (e.g., "paper").
        plural: Optional explicit plural form. If omitted, appends "s" to singular.
        include_number: If False, returns just the unit word properly pluralized.

    Returns:
        The formatted count string.
    """
    unit = singular if count == 1 else (plural if plural else f"{singular}s")
    return f"{count} {unit}" if include_number else unit
