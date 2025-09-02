"""Convenience imports for services package.

Ordered to avoid circular imports during module initialization.
"""

# Core utilities with no dependencies
from .http_utils import HTTPClient
from .utils import fix_broken_lines, normalize_paper_data

# DB related
from .database import DatabaseHealthService

# Minimal-dependency services
from .pdf import (
    PDFManager,
    PDFService,
    PDFDownloadHandler,
    PDFExtractionHandler,
    PDFDownloadTaskFactory,
)
from .background import BackgroundOperationService
from .validation import ValidationService
from .author import AuthorService
from .collection import CollectionService
from .search import SearchService
from .export import ExportService
from .theme import ThemeService

# Sync services (after DB services are available)
from .sync import SyncOperation, SyncConflict, SyncResult, SyncService
from .dialog_utils import DialogUtilsService

# Services that depend on the above
from .metadata import MetadataExtractor
from .paper import PaperService
from .system import SystemService
from .chat import ChatService
from .llm import LLMSummaryService
from .add_paper import AddPaperService
from .formatting import (
    format_file_size,
    format_authors_list,
    format_title_by_words,
    format_field_change,
    format_collections_list,
    format_download_speed,
)
from .paper_tracker import PaperChangeTracker

__all__ = [
    "AddPaperService",
    "AuthorService",
    "BackgroundOperationService",
    "ChatService",
    "CollectionService",
    "DatabaseHealthService",
    "DialogUtilsService",
    "ExportService",
    "HTTPClient",
    "LLMSummaryService",
    "MetadataExtractor",
    "PaperService",
    "PDFManager",
    "SearchService",
    "fix_broken_lines",
    "normalize_paper_data",
    "SyncOperation",
    "SyncConflict",
    "SyncResult",
    "SyncService",
    "SystemService",
    "ThemeService",
    "ValidationService",
    "PDFService",
    # New utility services
    "format_file_size",
    "format_authors_list",
    "format_title_by_words",
    "format_field_change",
    "format_collections_list",
    "format_download_speed",
    "PDFDownloadHandler",
    "PDFExtractionHandler",
    "PDFDownloadTaskFactory",
    "PaperChangeTracker",
]
