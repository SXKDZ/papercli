"""
Services package - Direct imports from modular service files.

This package provides access to all business logic services organized
into focused, single-responsibility modules.
"""

from .add_paper_service import AddPaperService
from .author_service import AuthorService, CollectionService
from .background_service import BackgroundOperationService
from .chat_service import ChatService
from .database_service import DatabaseHealthService
from .db_utils import AuthorQueries, CollectionQueries, DatabaseHelper, PaperQueries
from .export_service import ExportService

# Import all utility classes
from .http_utils import HTTPClient
from .llm_service import LLMSummaryService, PDFMetadataExtractionService
from .metadata_service import MetadataExtractor

# Import all service classes
from .paper_service import PaperService
from .pdf_service import PDFManager
from .search_service import SearchService
from .system_service import SystemService
from .utils import (
    compare_extracted_metadata_with_paper,
    fix_broken_lines,
    normalize_author_names,
    normalize_paper_data,
)

# List all available exports
__all__ = [
    # Utilities
    "HTTPClient",
    "DatabaseHelper",
    "PaperQueries",
    "AuthorQueries",
    "CollectionQueries",
    # Core Services
    "PaperService",
    "AuthorService",
    "CollectionService",
    "SearchService",
    "ExportService",
    "ChatService",
    "SystemService",
    "PDFManager",
    "DatabaseHealthService",
    "LLMSummaryService",
    "PDFMetadataExtractionService",
    "BackgroundOperationService",
    "MetadataExtractor",
    "AddPaperService",
    # Utility functions
    "fix_broken_lines",
    "compare_extracted_metadata_with_paper",
    "normalize_author_names",
    "normalize_paper_data",
]
