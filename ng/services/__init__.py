# Import basic utilities and services with no dependencies first
from .http_utils import HTTPClient
from .utils import fix_broken_lines, normalize_paper_data, format_count

# Import database related services
from .database import DatabaseHealthService
from .db_utils import DatabaseHelper, PaperQueries, AuthorQueries, CollectionQueries

# Import services with minimal dependencies
from .pdf import PDFManager, PDFService
from .background import BackgroundOperationService
from .validation import ValidationService
from .author import AuthorService
from .collection import CollectionService
from .search import SearchService
from .export import ExportService
from .theme import ThemeService

# Import sync services (after DatabaseHealthService is available)
from .sync import SyncOperation, SyncConflict, SyncResult, SyncService

# Import auto_sync after sync services
from .auto_sync import trigger_auto_sync

# Import metadata and paper services (these may have dependencies on above services)
from .metadata import MetadataExtractor
from .paper import PaperService
from .system import SystemService

# Import services that depend on other services
from .chat import ChatService
from .llm import LLMSummaryService
from .add_paper import AddPaperService

__all__ = [
    "AddPaperService",
    "AuthorService",
    "trigger_auto_sync",
    "BackgroundOperationService",
    "ChatService",
    "CollectionService",
    "DatabaseHealthService",
    "DatabaseHelper",
    "PaperQueries",
    "AuthorQueries",
    "CollectionQueries",
    "ExportService",
    "HTTPClient",
    "format_count",
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
]
