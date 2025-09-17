"""Convenience imports for services package.

Ordered to avoid circular imports during module initialization.
"""

# Core utilities with no dependencies
from . import http_utils
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
from .auto_sync import AutoSyncService
from . import validation
from .collection import CollectionService
from .search import SearchService
from . import export
from . import theme

# Sync services (after DB services are available)
from .sync import SyncOperation, SyncConflict, SyncResult, SyncService
from . import dialog_utils

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
from . import paper_tracker

__all__ = [
    "AddPaperService",
    "BackgroundOperationService",
    "AutoSyncService",
    "ChatService",
    "CollectionService",
    "DatabaseHealthService",
    "dialog_utils",
    "export",
    "http_utils",
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
    "theme",
    "validation",
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
    "paper_tracker",
]
