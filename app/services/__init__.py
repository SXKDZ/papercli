"""
Services package - Direct imports from modular service files.

This package provides access to all business logic services organized
into focused, single-responsibility modules.
"""

from .add_paper import AddPaperService
from .author import AuthorService, CollectionService
from .background import BackgroundOperationService
from .chat import ChatService
from .database import DatabaseHealthService
from .db_utils import AuthorQueries, CollectionQueries, DatabaseHelper, PaperQueries
from .export import ExportService

# Import all utility classes
from .http_utils import HTTPClient
from .llm import LLMSummaryService, PDFMetadataExtractionService
from .metadata import MetadataExtractor

# Import all service classes
from .paper import PaperService
from .pdf import PDFManager
from .search import SearchService
from .sync import SyncConflict, SyncResult, SyncService
from .system import SystemService
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
    "SyncService",
    "SyncConflict",
    "SyncResult",
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
