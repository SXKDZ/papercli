"""Sync service for managing local and remote database synchronization."""

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..db.database import get_db_session
from ..db.models import Author, Collection, Paper


class SyncConflict:
    """Represents a sync conflict between local and remote data."""
    
    def __init__(self, conflict_type: str, item_id: str, local_data: Dict, remote_data: Dict):
        self.conflict_type = conflict_type  # 'paper', 'collection', 'pdf'
        self.item_id = item_id
        self.local_data = local_data
        self.remote_data = remote_data
        self.differences = self._calculate_differences()
        
    def _calculate_differences(self) -> Dict[str, Dict]:
        """Calculate specific differences between local and remote data."""
        differences = {}
        
        all_keys = set(self.local_data.keys()) | set(self.remote_data.keys())
        for key in all_keys:
            local_val = self.local_data.get(key)
            remote_val = self.remote_data.get(key)
            
            if local_val != remote_val:
                differences[key] = {
                    'local': local_val,
                    'remote': remote_val
                }
                
        return differences


class SyncResult:
    """Represents the result of a sync operation."""
    
    def __init__(self):
        self.conflicts: List[SyncConflict] = []
        self.changes_applied: Dict[str, int] = {
            'papers_added': 0,
            'papers_updated': 0,
            'collections_added': 0,
            'collections_updated': 0,
            'pdfs_copied': 0,
            'pdfs_updated': 0
        }
        self.detailed_changes: Dict[str, List[str]] = {
            'papers_added': [],
            'papers_updated': [],
            'collections_added': [],
            'collections_updated': []
        }
        self.errors: List[str] = []
        self.cancelled = False
        
    def has_conflicts(self) -> bool:
        """Check if there are any conflicts."""
        return len(self.conflicts) > 0
        
    def get_summary(self) -> str:
        """Get a human-readable summary of sync results."""
        if self.cancelled:
            return "Sync operation was cancelled by user"
            
        if self.has_conflicts():
            return f"Sync completed with {len(self.conflicts)} conflicts that need resolution"
            
        total_changes = sum(self.changes_applied.values())
        if total_changes == 0:
            return "No changes to sync - local and remote are already in sync"
            
        summary_parts = []
        if self.changes_applied['papers_added'] > 0:
            summary_parts.append(f"{self.changes_applied['papers_added']} papers added")
        if self.changes_applied['papers_updated'] > 0:
            summary_parts.append(f"{self.changes_applied['papers_updated']} papers updated")
        if self.changes_applied['collections_added'] > 0:
            summary_parts.append(f"{self.changes_applied['collections_added']} collections added")
        if self.changes_applied['collections_updated'] > 0:
            summary_parts.append(f"{self.changes_applied['collections_updated']} collections updated")
        if self.changes_applied['pdfs_copied'] > 0:
            summary_parts.append(f"{self.changes_applied['pdfs_copied']} PDFs copied")
            
        return f"Sync completed: {', '.join(summary_parts)}"


class SyncService:
    """Service for managing synchronization between local and remote databases."""
    
    def __init__(self, local_data_dir: str, remote_data_dir: str, progress_callback=None):
        self.local_data_dir = Path(local_data_dir)
        self.remote_data_dir = Path(remote_data_dir)
        self.local_db_path = self.local_data_dir / "papers.db"
        self.remote_db_path = self.remote_data_dir / "papers.db"
        self.local_pdf_dir = self.local_data_dir / "pdfs"
        self.remote_pdf_dir = self.remote_data_dir / "pdfs"
        self.progress_callback = progress_callback
        
    def sync(self, conflict_resolver=None) -> SyncResult:
        """Perform a complete sync operation."""
        result = SyncResult()
        
        try:
            # Progress tracking - define all steps
            total_steps = 7
            current_step = 0
            
            def update_progress(message: str):
                nonlocal current_step
                current_step += 1
                if self.progress_callback:
                    percentage = int((current_step / total_steps) * 100)
                    self.progress_callback(percentage, message)
            
            update_progress("Creating remote directory...")
            # Ensure remote directory exists
            self.remote_data_dir.mkdir(parents=True, exist_ok=True)
            self.remote_pdf_dir.mkdir(parents=True, exist_ok=True)
            
            update_progress("Checking remote database...")
            # If remote database doesn't exist, create it from local
            if not self.remote_db_path.exists():
                update_progress("Creating initial remote database...")
                shutil.copy2(self.local_db_path, self.remote_db_path)
                result.changes_applied['papers_added'] = self._count_papers(self.local_db_path)
                result.changes_applied['collections_added'] = self._count_collections(self.local_db_path)
                update_progress("Copying PDFs to remote...")
                self._sync_pdfs_to_remote(result)
                update_progress("Initial sync completed")
                return result
            
            update_progress("Detecting conflicts...")
            # Detect conflicts
            conflicts = self._detect_conflicts()
            
            if conflicts:
                result.conflicts = conflicts
                update_progress(f"Found {len(conflicts)} conflicts...")
                
                # If conflict resolver is provided, try to resolve conflicts
                if conflict_resolver:
                    update_progress("Showing conflict resolution dialog...")
                    resolved_conflicts = conflict_resolver(conflicts)
                    if resolved_conflicts is None:  # User cancelled
                        result.cancelled = True
                        return result
                    
                    update_progress("Applying conflict resolutions...")
                    # Apply resolved conflicts
                    self._apply_conflict_resolutions(resolved_conflicts, result)
                else:
                    # No resolver provided, just return conflicts
                    return result
            else:
                update_progress("No conflicts detected...")
            
            update_progress("Synchronizing papers...")
            # Perform sync operations
            self._sync_papers(result)
            
            update_progress("Synchronizing collections...")
            self._sync_collections(result)
            
            update_progress("Synchronizing PDF files...")
            self._sync_pdfs_bidirectional(result)
            
            update_progress("Sync completed successfully")
            
        except Exception as e:
            result.errors.append(f"Sync failed: {str(e)}")
            if self.progress_callback:
                self.progress_callback(100, f"Sync failed: {str(e)}")
            
        return result
    
    def _detect_conflicts(self) -> List[SyncConflict]:
        """Detect conflicts between local and remote databases."""
        conflicts = []
        
        # Get papers from both databases
        local_papers = self._get_papers_dict(self.local_db_path)
        remote_papers = self._get_papers_dict(self.remote_db_path)
        
        # Check for paper conflicts (same ID, different data)
        for paper_id in set(local_papers.keys()) & set(remote_papers.keys()):
            local_paper = local_papers[paper_id]
            remote_paper = remote_papers[paper_id]
            
            # Compare relevant fields
            if self._papers_differ(local_paper, remote_paper):
                conflict = SyncConflict('paper', paper_id, local_paper, remote_paper)
                conflicts.append(conflict)
        
        # Check for PDF conflicts
        pdf_conflicts = self._detect_pdf_conflicts()
        conflicts.extend(pdf_conflicts)
        
        return conflicts
    
    def _papers_differ(self, local_paper: Dict, remote_paper: Dict) -> bool:
        """Check if two paper records differ in significant ways."""
        # Fields to compare (excluding timestamps which may differ naturally)
        compare_fields = ['title', 'abstract', 'venue_full', 'venue_short', 'paper_type', 
                         'publication_year', 'doi', 'arxiv_id', 'url', 'pdf_path']
        
        for field in compare_fields:
            if local_paper.get(field) != remote_paper.get(field):
                return True
                
        return False
    
    def _detect_pdf_conflicts(self) -> List[SyncConflict]:
        """Detect PDF file conflicts."""
        conflicts = []
        
        if not (self.local_pdf_dir.exists() and self.remote_pdf_dir.exists()):
            return conflicts
            
        local_pdfs = {f.name: self._get_file_info(f) for f in self.local_pdf_dir.glob("*.pdf")}
        remote_pdfs = {filename: self._get_file_info(self.remote_pdf_dir / filename) 
                      for filename in local_pdfs.keys() if (self.remote_pdf_dir / filename).exists()}
        
        for filename in set(local_pdfs.keys()) & set(remote_pdfs.keys()):
            local_info = local_pdfs[filename]
            remote_info = remote_pdfs[filename]
            
            # Compare file hash and size
            if (local_info['hash'] != remote_info['hash'] or 
                local_info['size'] != remote_info['size']):
                
                conflict = SyncConflict('pdf', filename, local_info, remote_info)
                conflicts.append(conflict)
                
        return conflicts
    
    def _get_file_info(self, file_path: Path) -> Dict:
        """Get file information including hash, size, and modification time."""
        if not file_path.exists():
            return {}
            
        stat = file_path.stat()
        
        # Calculate MD5 hash
        with open(file_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
            
        return {
            'hash': file_hash,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'path': str(file_path)
        }
    
    def _get_papers_dict(self, db_path: Path) -> Dict[int, Dict]:
        """Get papers from database as a dictionary."""
        papers = {}
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT p.*, GROUP_CONCAT(a.full_name) as authors
                FROM papers p
                LEFT JOIN paper_authors pa ON p.id = pa.paper_id
                LEFT JOIN authors a ON pa.author_id = a.id
                GROUP BY p.id
            """)
            
            for row in cursor.fetchall():
                papers[row['id']] = dict(row)
                
        finally:
            conn.close()
            
        return papers
    
    def _count_papers(self, db_path: Path) -> int:
        """Count papers in database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM papers")
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def _count_collections(self, db_path: Path) -> int:
        """Count collections in database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM collections")
            return cursor.fetchone()[0]
        finally:
            conn.close()
    
    def _sync_papers(self, result: SyncResult):
        """Sync papers between local and remote databases."""
        local_papers = self._get_papers_dict(self.local_db_path)
        remote_papers = self._get_papers_dict(self.remote_db_path)
        
        # Papers only in local (need to add to remote)
        local_only = set(local_papers.keys()) - set(remote_papers.keys())
        for paper_id in local_only:
            paper_data = local_papers[paper_id]
            self._copy_paper_to_remote(paper_data)
            result.changes_applied['papers_added'] += 1
            result.detailed_changes['papers_added'].append(f"'{paper_data.get('title', 'Unknown Title')}'")
        
        # Papers only in remote (need to add to local)
        remote_only = set(remote_papers.keys()) - set(local_papers.keys())
        for paper_id in remote_only:
            paper_data = remote_papers[paper_id]
            self._copy_paper_to_local(paper_data)
            result.changes_applied['papers_added'] += 1
            result.detailed_changes['papers_added'].append(f"'{paper_data.get('title', 'Unknown Title')}' (from remote)")
    
    def _sync_collections(self, result: SyncResult):
        """Sync collections between local and remote databases."""
        local_collections = self._get_collections_dict(self.local_db_path)
        remote_collections = self._get_collections_dict(self.remote_db_path)
        
        # Collections only in local (need to add to remote)
        local_only = set(local_collections.keys()) - set(remote_collections.keys())
        for collection_id in local_only:
            collection_data = local_collections[collection_id]
            self._copy_collection_to_remote(collection_data)
            result.changes_applied['collections_added'] += 1
            result.detailed_changes['collections_added'].append(f"'{collection_data.get('name', 'Unknown Collection')}'")
        
        # Collections only in remote (need to add to local)
        remote_only = set(remote_collections.keys()) - set(local_collections.keys())
        for collection_id in remote_only:
            collection_data = remote_collections[collection_id]
            self._copy_collection_to_local(collection_data)
            result.changes_applied['collections_added'] += 1
            result.detailed_changes['collections_added'].append(f"'{collection_data.get('name', 'Unknown Collection')}' (from remote)")
    
    def _sync_pdfs_to_remote(self, result: SyncResult):
        """Copy PDFs from local to remote."""
        if not self.local_pdf_dir.exists():
            return
            
        for pdf_file in self.local_pdf_dir.glob("*.pdf"):
            remote_pdf = self.remote_pdf_dir / pdf_file.name
            if not remote_pdf.exists():
                shutil.copy2(pdf_file, remote_pdf)
                result.changes_applied['pdfs_copied'] += 1
    
    def _sync_pdfs_bidirectional(self, result: SyncResult):
        """Sync PDFs in both directions."""
        # Copy missing PDFs from local to remote
        if self.local_pdf_dir.exists():
            for pdf_file in self.local_pdf_dir.glob("*.pdf"):
                remote_pdf = self.remote_pdf_dir / pdf_file.name
                if not remote_pdf.exists():
                    shutil.copy2(pdf_file, remote_pdf)
                    result.changes_applied['pdfs_copied'] += 1
        
        # Copy missing PDFs from remote to local
        if self.remote_pdf_dir.exists():
            self.local_pdf_dir.mkdir(exist_ok=True)
            for pdf_file in self.remote_pdf_dir.glob("*.pdf"):
                local_pdf = self.local_pdf_dir / pdf_file.name
                if not local_pdf.exists():
                    shutil.copy2(pdf_file, local_pdf)
                    result.changes_applied['pdfs_copied'] += 1
    
    def _get_collections_dict(self, db_path: Path) -> Dict[int, Dict]:
        """Get collections from database as a dictionary."""
        collections = {}
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM collections")
            for row in cursor.fetchall():
                collections[row['id']] = dict(row)
        finally:
            conn.close()
            
        return collections

    def _copy_paper_to_remote(self, paper_data: Dict):
        """Copy a paper from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()
        
        try:
            # Prepare paper data with required datetime fields
            paper_dict = dict(paper_data)
            if 'added_date' not in paper_dict or not paper_dict['added_date']:
                paper_dict['added_date'] = datetime.now().isoformat()
            if 'modified_date' not in paper_dict or not paper_dict['modified_date']:
                paper_dict['modified_date'] = datetime.now().isoformat()
                
            # Insert paper (excluding id and authors, filtering None values)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if field not in ['id', 'authors'] and value is not None:
                    filtered_fields.append(field)
                    filtered_values.append(value)
            
            placeholders = ', '.join(['?'] * len(filtered_fields))
            field_names = ', '.join(filtered_fields)
            
            cursor.execute(f"INSERT INTO papers ({field_names}) VALUES ({placeholders})", filtered_values)
            new_paper_id = cursor.lastrowid
            
            # Handle authors if present
            if 'authors' in paper_data and paper_data['authors']:
                author_names = paper_data['authors'].split(',') if paper_data['authors'] else []
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        # Insert or get author
                        cursor.execute("INSERT OR IGNORE INTO authors (full_name) VALUES (?)", (author_name,))
                        cursor.execute("SELECT id FROM authors WHERE full_name = ?", (author_name,))
                        author_id = cursor.fetchone()[0]
                        
                        # Link paper and author
                        cursor.execute("INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)", 
                                     (new_paper_id, author_id, i))
            
            conn.commit()
        finally:
            conn.close()

    def _copy_paper_to_local(self, paper_data: Dict):
        """Copy a paper from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        
        try:
            # Prepare paper data with required datetime fields
            paper_dict = dict(paper_data)
            if 'added_date' not in paper_dict or not paper_dict['added_date']:
                paper_dict['added_date'] = datetime.now().isoformat()
            if 'modified_date' not in paper_dict or not paper_dict['modified_date']:
                paper_dict['modified_date'] = datetime.now().isoformat()
                
            # Insert paper (excluding id and authors, filtering None values)
            filtered_fields = []
            filtered_values = []
            for field, value in paper_dict.items():
                if field not in ['id', 'authors'] and value is not None:
                    filtered_fields.append(field)
                    filtered_values.append(value)
            
            placeholders = ', '.join(['?'] * len(filtered_fields))
            field_names = ', '.join(filtered_fields)
            
            cursor.execute(f"INSERT INTO papers ({field_names}) VALUES ({placeholders})", filtered_values)
            new_paper_id = cursor.lastrowid
            
            # Handle authors if present
            if 'authors' in paper_data and paper_data['authors']:
                author_names = paper_data['authors'].split(',') if paper_data['authors'] else []
                for i, author_name in enumerate(author_names):
                    author_name = author_name.strip()
                    if author_name:
                        # Insert or get author
                        cursor.execute("INSERT OR IGNORE INTO authors (full_name) VALUES (?)", (author_name,))
                        cursor.execute("SELECT id FROM authors WHERE full_name = ?", (author_name,))
                        author_id = cursor.fetchone()[0]
                        
                        # Link paper and author
                        cursor.execute("INSERT INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)", 
                                     (new_paper_id, author_id, i))
            
            conn.commit()
        finally:
            conn.close()

    def _copy_collection_to_remote(self, collection_data: Dict):
        """Copy a collection from local to remote database."""
        conn = sqlite3.connect(self.remote_db_path)
        cursor = conn.cursor()
        
        try:
            # Include created_at field or use current timestamp
            created_at = collection_data.get('created_at') or datetime.now().isoformat()
            cursor.execute("INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?)", 
                         (collection_data['name'], collection_data.get('description', ''), created_at))
            conn.commit()
        finally:
            conn.close()

    def _copy_collection_to_local(self, collection_data: Dict):
        """Copy a collection from remote to local database."""
        conn = sqlite3.connect(self.local_db_path)
        cursor = conn.cursor()
        
        try:
            # Include created_at field or use current timestamp
            created_at = collection_data.get('created_at') or datetime.now().isoformat()
            cursor.execute("INSERT INTO collections (name, description, created_at) VALUES (?, ?, ?)", 
                         (collection_data['name'], collection_data.get('description', ''), created_at))
            conn.commit()
        finally:
            conn.close()

    def _apply_conflict_resolutions(self, resolved_conflicts: Dict, result: SyncResult):
        """Apply user's conflict resolutions."""
        for conflict_id, resolution in resolved_conflicts.items():
            # Resolution can be 'local', 'remote', or 'merge'
            # This is a simplified implementation
            if resolution == 'local':
                # Keep local version
                pass
            elif resolution == 'remote':
                # Use remote version
                pass
            elif resolution == 'merge':
                # Attempt to merge changes
                pass