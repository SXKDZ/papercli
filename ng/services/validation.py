from __future__ import annotations

import os
import re
from typing import Iterable, Tuple


def validate_arxiv_id(arxiv_id: str) -> Tuple[bool, str]:
    """
    Validate arXiv ID format.

    Args:
        arxiv_id: The arXiv ID to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not arxiv_id or not arxiv_id.strip():
        return False, "arXiv ID cannot be empty"

    # Clean the ID first using existing logic from MetadataExtractor
    clean_id = re.sub(r"arxiv[:\s]*", "", arxiv_id.strip(), flags=re.IGNORECASE)
    clean_id = re.sub(r"[^\d\.v]", "", clean_id)

    if not clean_id:
        return (
            False,
            "Invalid arXiv ID format. Expected format: 2307.10635 or arXiv:2307.10635",
        )

    # Check for valid arXiv ID patterns
    # Old format: astro-ph/0506001 or New format: 2307.10635v1
    old_format = re.match(r"^[a-z-]+/\d{7}(v\d+)?$", clean_id)
    new_format = re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", clean_id)

    if not (old_format or new_format):
        return (
            False,
            "Invalid arXiv ID format. Expected format: 2307.10635 or astro-ph/0506001",
        )

    return True, ""


def validate_dblp_url(dblp_url: str) -> Tuple[bool, str]:
    """
    Validate DBLP URL format.

    Args:
        dblp_url: The DBLP URL to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not dblp_url or not dblp_url.strip():
        return False, "DBLP URL cannot be empty"

    url = dblp_url.strip()

    # Check if it's a valid DBLP URL
    dblp_patterns = [
        r"^https?://dblp\.org/",
        r"^https?://dblp\.uni-trier\.de/",
        r"^dblp\.org/",
        r"^dblp\.uni-trier\.de/",
    ]

    if not any(re.match(pattern, url, re.IGNORECASE) for pattern in dblp_patterns):
        return False, "Invalid DBLP URL. Expected format: https://dblp.org/rec/..."

    return True, ""


def validate_openreview_id(openreview_id: str) -> Tuple[bool, str]:
    """
    Validate OpenReview ID format.

    Args:
        openreview_id: The OpenReview ID to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not openreview_id or not openreview_id.strip():
        return False, "OpenReview ID cannot be empty"

    clean_id = openreview_id.strip()

    # OpenReview IDs are typically alphanumeric strings like: bq1JEgioLr, H1eA7ME5tm
    # They can contain letters and numbers, usually 8-12 characters
    if not re.match(r"^[A-Za-z0-9_-]{6,20}$", clean_id):
        return False, "Invalid OpenReview ID format. Expected format: bq1JEgioLr"

    return True, ""


def validate_doi(doi: str) -> Tuple[bool, str]:
    """
    Validate DOI format.

    Args:
        doi: The DOI to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not doi or not doi.strip():
        return False, "DOI cannot be empty"

    clean_doi = doi.strip()

    # Remove doi: prefix if present
    clean_doi = re.sub(r"^doi:\s*", "", clean_doi, flags=re.IGNORECASE)

    # DOI format: 10.xxxx/yyyy where xxxx is registrant code and yyyy is suffix
    doi_pattern = r"^10\.\d+/.+$"

    if not re.match(doi_pattern, clean_doi):
        return False, "Invalid DOI format. Expected format: 10.1000/example"

    return True, ""


def validate_website_url(url: str) -> Tuple[bool, str]:
    """
    Validate website URL format.

    Args:
        url: The website URL to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not url or not url.strip():
        return False, "Website URL cannot be empty"

    clean_url = url.strip()

    # Check if it's a valid URL format
    url_pattern = r"^https?://[^\s]+"

    if not re.match(url_pattern, clean_url, re.IGNORECASE):
        return False, "Invalid URL format. Expected format: https://example.com/article"

    # Check for common invalid patterns
    if len(clean_url) < 10:
        return False, "URL is too short to be valid"

    if not any(
        tld in clean_url.lower()
        for tld in [".com", ".org", ".net", ".edu", ".gov", ".io", ".ai", ".co"]
    ):
        return False, "URL must contain a valid top-level domain"

    return True, ""


def validate_pdf_path(pdf_path: str) -> Tuple[bool, str]:
    """
    Validate PDF file path.

    Args:
        pdf_path: The PDF file path to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not pdf_path or not pdf_path.strip():
        return False, "PDF path cannot be empty"

    return _validate_existing_file(pdf_path.strip(), (".pdf",), "PDF")


def validate_bib_path(bib_path: str) -> Tuple[bool, str]:
    """
    Validate BibTeX file path.

    Args:
        bib_path: The BibTeX file path to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not bib_path or not bib_path.strip():
        return False, "BibTeX file path cannot be empty"

    return _validate_existing_file(bib_path.strip(), (".bib", ".bibtex"), "BibTeX")


def validate_ris_path(ris_path: str) -> Tuple[bool, str]:
    """
    Validate RIS file path.

    Args:
        ris_path: The RIS file path to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not ris_path or not ris_path.strip():
        return False, "RIS file path cannot be empty"

    return _validate_existing_file(ris_path.strip(), (".ris", ".txt"), "RIS")


def validate_manual_title(title: str) -> Tuple[bool, str]:
    """
    Validate manual paper title.

    Args:
        title: The paper title to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    # Manual title can be empty (will use default), but if provided should be reasonable
    if title is None:
        return True, ""

    title = title.strip()

    # If empty, that's fine for manual entry
    if not title:
        return True, ""

    # If provided, should be at least 3 characters and not too long
    if len(title) < 3:
        return False, "Title should be at least 3 characters long"

    if len(title) > 500:
        return False, "Title is too long (max 500 characters)"

    return True, ""


def _validate_existing_file(
    path: str, allowed_exts: Iterable[str], label: str
) -> Tuple[bool, str]:
    """Shared helper to validate an existing file with allowed extensions."""
    if not path or not path.strip():
        return False, f"{label} file path cannot be empty"

    original = path.strip()
    absolute_path = os.path.abspath(os.path.expanduser(original))

    if not os.path.exists(absolute_path):
        return False, f"{label} file not found: {original}"
    if not os.path.isfile(absolute_path):
        return False, f"Path is not a file: {original}"
    if allowed_exts and not any(
        absolute_path.lower().endswith(ext) for ext in allowed_exts
    ):
        return False, f"File is not a {label} file: {original}"

    return True, ""


def validate_input(source: str, path_id: str) -> Tuple[bool, str]:
    """
    Validate input based on source type.

    Args:
        source: The paper source type
        path_id: The input to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    source = source.lower().strip()

    if source == "arxiv":
        return validate_arxiv_id(path_id)
    elif source == "dblp":
        return validate_dblp_url(path_id)
    elif source == "openreview":
        return validate_openreview_id(path_id)
    elif source == "doi":
        return validate_doi(path_id)
    elif source == "website":
        return validate_website_url(path_id)
    elif source == "pdf":
        return validate_pdf_path(path_id)
    elif source == "bib":
        return validate_bib_path(path_id)
    elif source == "ris":
        return validate_ris_path(path_id)
    elif source == "manual":
        return validate_manual_title(path_id)
    else:
        return False, f"Unknown source type: {source}"
