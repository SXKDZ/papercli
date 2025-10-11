"""Convenience imports for services package.

Ordered to avoid circular imports during module initialization.
"""

# Level 1: Core utilities with no dependencies
from . import http_utils
from .utils import fix_broken_lines, normalize_paper_data

# Level 2: Formatting utilities (no dependencies)
from .formatting import (
    format_file_size,
    format_authors_list,
    format_title_by_words,
    format_field_change,
    format_collections_list,
    format_download_speed,
)

# Level 3: Independent modules
from . import validation
from . import prompts
from . import llm_utils

# Level 4: Metadata services (exposed early for aggregator use)
from .metadata import MetadataExtractor

# Level 5: PDF services (depends on formatting, http_utils, may reference metadata types)
from .pdf import (
    PDFManager,
    PDFService,
    PDFDownloadHandler,
    PDFExtractionHandler,
    PDFDownloadTaskFactory,
)

# Level 6: Database services (depends on formatting, pdf)
from .database import DatabaseHealthService

# Level 7: Background and infrastructure services
from .background import BackgroundOperationService
from .collection import CollectionService
from .search import SearchService
from . import export
from . import theme
from . import dialog_utils
from . import paper_tracker

# Level 8: Sync services
from .sync import SyncOperation, SyncConflict, SyncResult, SyncService

# Level 8.5: Auto-sync (depends on SyncService)
from .auto_sync import AutoSyncService

# Level 9: Higher-level services (depend on services above)
from .paper import PaperService
from .system import SystemService
from .chat import ChatService
from .llm import LLMSummaryService
from .add_paper import AddPaperService
from .webpage import WebpageSnapshotService

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
    # Formatting utilities
    "format_file_size",
    "format_authors_list",
    "format_title_by_words",
    "format_field_change",
    "format_collections_list",
    "format_download_speed",
    # PDF services
    "PDFDownloadHandler",
    "PDFExtractionHandler",
    "PDFDownloadTaskFactory",
    # Webpage services
    "WebpageSnapshotService",
    # Modules
    "paper_tracker",
    "prompts",
    "llm_utils",
]
