"""
Validators for prompt-toolkit input.
"""

import re
from pathlib import Path

from prompt_toolkit.validation import ValidationError, Validator


class FilePathValidator(Validator):
    """Validator for file paths."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="File path cannot be empty")

        path = Path(text)
        if not path.exists():
            raise ValidationError(message="File does not exist")

        if not path.is_file():
            raise ValidationError(message="Path is not a file")

        if path.suffix.lower() != ".pdf":
            raise ValidationError(message="File must be a PDF")


class ArxivValidator(Validator):
    """Validator for arXiv identifiers."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="arXiv ID cannot be empty")

        # Clean and validate arXiv ID format
        arxiv_id = re.sub(r"arxiv[:\s]*", "", text, flags=re.IGNORECASE)
        arxiv_id = re.sub(r"[^0-9\.]", "", arxiv_id)

        if not re.match(r"\d{4}\.\d{4,5}", arxiv_id):
            raise ValidationError(
                message="Invalid arXiv ID format (should be YYYY.NNNNN)"
            )


class URLValidator(Validator):
    """Validator for URLs."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="URL cannot be empty")

        if not text.startswith(("http://", "https://")):
            raise ValidationError(message="URL must start with http:// or https://")


class YearValidator(Validator):
    """Validator for publication years."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            return  # Year is optional

        try:
            year = int(text)
            if year < 1900 or year > 2030:
                raise ValidationError(message="Year must be between 1900 and 2030")
        except ValueError:
            raise ValidationError(message="Year must be a number")
