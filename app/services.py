"""
Service classes for PaperCLI business logic.
"""

import os
import re
import requests
import json
import subprocess
import webbrowser
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from fuzzywuzzy import fuzz

from .database import get_db_session
from .models import Paper, Author, Collection


class PaperService:
    """Service for managing papers."""
    
    def get_all_papers(self) -> List[Paper]:
        """Get all papers ordered by added date (newest first)."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload
            
            # Eagerly load relationships to avoid detached instance errors
            papers = session.query(Paper).options(
                joinedload(Paper.authors),
                joinedload(Paper.collections)
            ).order_by(Paper.added_date.desc()).all()
            
            # Force load all relationships while in session
            for paper in papers:
                _ = paper.authors  # Force load authors
                _ = paper.collections  # Force load collections
            
            # Expunge all objects to make them detached but accessible
            session.expunge_all()
            
            return papers
    
    def get_paper_by_id(self, paper_id: int) -> Optional[Paper]:
        """Get paper by ID."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload
            
            paper = session.query(Paper).options(
                joinedload(Paper.authors),
                joinedload(Paper.collections)
            ).filter(Paper.id == paper_id).first()
            
            if paper:
                # Force load relationships while in session
                _ = paper.authors
                _ = paper.collections
                
                # Expunge to make detached but accessible
                session.expunge_all()
            
            return paper
    
    def add_paper(self, paper_data: Dict[str, Any]) -> Paper:
        """Add a new paper."""
        with get_db_session() as session:
            paper = Paper(**paper_data)
            session.add(paper)
            session.commit()
            session.refresh(paper)
            return paper
    
    def update_paper(self, paper_id: int, paper_data: Dict[str, Any]) -> Optional[Paper]:
        """Update an existing paper."""
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if paper:
                for key, value in paper_data.items():
                    setattr(paper, key, value)
                paper.modified_date = datetime.utcnow()
                session.commit()
                session.refresh(paper)
            return paper
    
    def delete_paper(self, paper_id: int) -> bool:
        """Delete a paper."""
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if paper:
                session.delete(paper)
                session.commit()
                return True
            return False
    
    def delete_papers(self, paper_ids: List[int]) -> int:
        """Delete multiple papers. Returns count of deleted papers."""
        with get_db_session() as session:
            count = session.query(Paper).filter(Paper.id.in_(paper_ids)).delete()
            session.commit()
            return count
    
    def add_paper_from_metadata(self, paper_data: Dict[str, Any], authors: List[str], 
                               collections: List[str] = None) -> Paper:
        """Add paper with authors and collections."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload
            
            # Check for existing paper by arXiv ID, DOI, or title
            existing_paper = None
            if paper_data.get('arxiv_id'):
                existing_paper = session.query(Paper).filter(Paper.arxiv_id == paper_data['arxiv_id']).first()
            elif paper_data.get('doi'):
                existing_paper = session.query(Paper).filter(Paper.doi == paper_data['doi']).first()
            elif paper_data.get('title'):
                existing_paper = session.query(Paper).filter(Paper.title == paper_data['title']).first()
            
            if existing_paper:
                raise Exception(f"Paper already exists in database (ID: {existing_paper.id})")
            
            # Create paper
            paper = Paper()
            for key, value in paper_data.items():
                if hasattr(paper, key) and value is not None:
                    setattr(paper, key, value)
            
            session.add(paper)
            session.flush()  # Get the paper ID without committing
            
            # Add authors
            for author_name in authors:
                author = session.query(Author).filter(Author.full_name == author_name).first()
                if not author:
                    author = Author(full_name=author_name)
                    session.add(author)
                paper.authors.append(author)
            
            # Add collections
            if collections:
                for collection_name in collections:
                    collection = session.query(Collection).filter(Collection.name == collection_name).first()
                    if not collection:
                        collection = Collection(name=collection_name)
                        session.add(collection)
                        session.flush()  # Ensure collection has an ID
                    
                    # Double-check for existing association in the database
                    from sqlalchemy import text
                    existing_association = session.execute(
                        text("SELECT 1 FROM paper_collections WHERE paper_id = :paper_id AND collection_id = :collection_id"),
                        {"paper_id": paper.id, "collection_id": collection.id}
                    ).first()
                    
                    if not existing_association and collection not in paper.collections:
                        paper.collections.append(collection)
            
            session.commit()
            session.refresh(paper)
            
            # Create a new query with eager loading to get a properly attached instance
            paper_with_relationships = session.query(Paper).options(
                joinedload(Paper.authors),
                joinedload(Paper.collections)
            ).filter(Paper.id == paper.id).first()
            
            # Force load all relationships while still in session
            _ = paper_with_relationships.authors
            _ = paper_with_relationships.collections
            
            # Expunge to make detached but accessible
            session.expunge_all()
            
            return paper_with_relationships


class AuthorService:
    """Service for managing authors."""
    
    def get_or_create_author(self, full_name: str, **kwargs) -> Author:
        """Get existing author or create new one."""
        with get_db_session() as session:
            author = session.query(Author).filter(Author.full_name == full_name).first()
            if not author:
                author = Author(full_name=full_name, **kwargs)
                session.add(author)
                session.commit()
                session.refresh(author)
            return author
    
    def search_authors(self, query: str) -> List[Author]:
        """Search authors by name."""
        with get_db_session() as session:
            return session.query(Author).filter(
                Author.full_name.ilike(f'%{query}%')
            ).all()


class CollectionService:
    """Service for managing collections."""
    
    def get_all_collections(self) -> List[Collection]:
        """Get all collections."""
        with get_db_session() as session:
            return session.query(Collection).order_by(Collection.name).all()
    
    def get_or_create_collection(self, name: str, description: str = None) -> Collection:
        """Get existing collection or create new one."""
        with get_db_session() as session:
            collection = session.query(Collection).filter(Collection.name == name).first()
            if not collection:
                collection = Collection(name=name, description=description)
                session.add(collection)
                session.commit()
                session.refresh(collection)
            return collection
    
    def add_paper_to_collection(self, paper_id: int, collection_name: str) -> bool:
        """Add paper to collection."""
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if not paper:
                return False
            
            # Get or create collection within the same session
            collection = session.query(Collection).filter(Collection.name == collection_name).first()
            if not collection:
                collection = Collection(name=collection_name)
                session.add(collection)
            
            if collection not in paper.collections:
                paper.collections.append(collection)
                session.commit()
                return True
            return False


class SearchService:
    """Service for searching and filtering papers."""
    
    def search_papers(self, query: str, fields: List[str] = None) -> List[Paper]:
        """Search papers by query in specified fields with fuzzy matching."""
        if fields is None:
            fields = ['title', 'abstract', 'authors', 'venue']
        
        with get_db_session() as session:
            conditions = []
            
            if 'title' in fields:
                conditions.append(Paper.title.ilike(f'%{query}%'))
            if 'abstract' in fields:
                conditions.append(Paper.abstract.ilike(f'%{query}%'))
            if 'venue' in fields:
                conditions.append(or_(
                    Paper.venue_full.ilike(f'%{query}%'),
                    Paper.venue_acronym.ilike(f'%{query}%')
                ))
            if 'notes' in fields:
                conditions.append(Paper.notes.ilike(f'%{query}%'))
            
            # Search in authors requires join
            if 'authors' in fields:
                papers_by_author = session.query(Paper).join(Paper.authors).filter(
                    Author.full_name.ilike(f'%{query}%')
                ).all()
                # Add author search results
                paper_ids = [p.id for p in papers_by_author]
                if paper_ids:
                    conditions.append(Paper.id.in_(paper_ids))
            
            if conditions:
                from sqlalchemy.orm import joinedload
                papers = session.query(Paper).options(
                    joinedload(Paper.authors),
                    joinedload(Paper.collections)
                ).filter(or_(*conditions)).order_by(Paper.added_date.desc()).all()
                
                # Force load relationships
                for paper in papers:
                    _ = paper.authors
                    _ = paper.collections
                
                # Expunge to make detached but accessible
                session.expunge_all()
                return papers
            return []
    
    def fuzzy_search_papers(self, query: str, threshold: int = 60) -> List[Paper]:
        """Fuzzy search papers using edit distance."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload
            
            # Eagerly load all papers with relationships
            all_papers = session.query(Paper).options(
                joinedload(Paper.authors),
                joinedload(Paper.collections)
            ).all()
            
            scored_papers = []
            
            for paper in all_papers:
                # Force load relationships while in session
                _ = paper.authors
                _ = paper.collections
                
                # Calculate fuzzy match scores
                title_score = fuzz.partial_ratio(query.lower(), paper.title.lower())
                author_score = max([fuzz.partial_ratio(query.lower(), author.full_name.lower()) 
                                  for author in paper.authors] or [0])
                venue_score = max([
                    fuzz.partial_ratio(query.lower(), paper.venue_full.lower()) if paper.venue_full else 0,
                    fuzz.partial_ratio(query.lower(), paper.venue_acronym.lower()) if paper.venue_acronym else 0
                ])
                
                # Use the highest score
                max_score = max(title_score, author_score, venue_score)
                
                if max_score >= threshold:
                    scored_papers.append((paper, max_score))
            
            # Sort by score (highest first)
            scored_papers.sort(key=lambda x: x[1], reverse=True)
            
            # Expunge to make detached but accessible
            session.expunge_all()
            return [paper for paper, score in scored_papers]
    
    def filter_papers(self, filters: Dict[str, Any]) -> List[Paper]:
        """Filter papers by various criteria."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload
            
            query = session.query(Paper).options(
                joinedload(Paper.authors),
                joinedload(Paper.collections)
            )
            
            if 'year' in filters:
                query = query.filter(Paper.year == filters['year'])
            
            if 'year_range' in filters:
                start, end = filters['year_range']
                query = query.filter(and_(Paper.year >= start, Paper.year <= end))
            
            if 'paper_type' in filters:
                query = query.filter(Paper.paper_type == filters['paper_type'])
            
            if 'venue' in filters:
                query = query.filter(or_(
                    Paper.venue_full.ilike(f'%{filters["venue"]}%'),
                    Paper.venue_acronym.ilike(f'%{filters["venue"]}%')
                ))
            
            if 'collection' in filters:
                query = query.join(Paper.collections).filter(
                    Collection.name == filters['collection']
                )
            
            if 'author' in filters:
                query = query.join(Paper.authors).filter(
                    Author.full_name.ilike(f'%{filters["author"]}%')
                )
            
            papers = query.order_by(Paper.added_date.desc()).all()
            
            # Force load relationships while in session
            for paper in papers:
                _ = paper.authors
                _ = paper.collections
            
            # Expunge to make detached but accessible
            session.expunge_all()
            return papers


class MetadataExtractor:
    """Service for extracting metadata from various sources."""
    
    def extract_from_arxiv(self, arxiv_id: str) -> Dict[str, Any]:
        """Extract metadata from arXiv."""
        import xml.etree.ElementTree as ET
        
        # Clean arXiv ID
        arxiv_id = re.sub(r'arxiv[:\s]*', '', arxiv_id, flags=re.IGNORECASE)
        arxiv_id = re.sub(r'[^\d\.]', '', arxiv_id)
        
        try:
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse XML response
            root = ET.fromstring(response.content)
            
            # Define namespace
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            # Find the entry
            entry = root.find('.//atom:entry', ns)
            if entry is None:
                raise Exception("Paper not found on arXiv")
            
            # Extract title
            title_elem = entry.find('atom:title', ns)
            title = title_elem.text.strip() if title_elem is not None else "Unknown Title"
            
            # Extract abstract
            summary_elem = entry.find('atom:summary', ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else ""
            
            # Extract authors
            authors = []
            for author in entry.findall('atom:author', ns):
                name_elem = author.find('atom:name', ns)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())
            
            # Extract publication date
            published_elem = entry.find('atom:published', ns)
            year = None
            if published_elem is not None:
                published_date = published_elem.text
                year_match = re.search(r'(\d{4})', published_date)
                if year_match:
                    year = int(year_match.group(1))
            
            # Extract DOI if available
            doi = None
            doi_elem = entry.find('atom:id', ns)
            if doi_elem is not None:
                doi_match = re.search(r'doi:(.+)', doi_elem.text)
                if doi_match:
                    doi = doi_match.group(1)
            
            return {
                'title': title,
                'abstract': abstract,
                'authors': authors,
                'year': year,
                'arxiv_id': arxiv_id,
                'doi': doi,
                'paper_type': 'preprint',
                'venue_full': 'arXiv',
                'venue_acronym': 'arXiv'
            }
            
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch arXiv metadata: {e}")
        except ET.ParseError as e:
            raise Exception(f"Failed to parse arXiv response: {e}")
    
    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Extract metadata from PDF file."""
        try:
            import PyPDF2
            
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # Extract metadata
                metadata = pdf_reader.metadata
                
                # Extract title from metadata or first page
                title = metadata.get('/Title', 'Unknown Title') if metadata else 'Unknown Title'
                
                # Extract author from metadata
                author = metadata.get('/Author', '') if metadata else ''
                authors = [author] if author else []
                
                # Extract text from first page for additional info
                if pdf_reader.pages:
                    first_page = pdf_reader.pages[0]
                    text = first_page.extract_text()
                    
                    # Try to extract year from text
                    year_match = re.search(r'(19|20)\d{2}', text)
                    year = int(year_match.group()) if year_match else None
                else:
                    year = None
                
                return {
                    'title': title,
                    'authors': authors,
                    'year': year,
                    'pdf_path': pdf_path,
                    'paper_type': 'unknown'
                }
                
        except Exception as e:
            raise Exception(f"Failed to extract PDF metadata: {e}")
    
    def extract_from_dblp(self, dblp_url: str) -> Dict[str, Any]:
        """Extract metadata from DBLP URL."""
        try:
            # Add headers to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(dblp_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            content = response.text
            
            # Extract title (try multiple patterns)
            title = "Unknown Title"
            title_patterns = [
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^<]+?)\s*-\s*dblp</title>',
                r'<span class="title"[^>]*>([^<]+)</span>',
                r'<h2[^>]*>([^<]+)</h2>'
            ]
            
            for pattern in title_patterns:
                title_match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).strip()
                    # Clean up common DBLP title formatting
                    title = re.sub(r'\s+', ' ', title)
                    title = title.replace('\n', ' ').strip()
                    break
            
            # Extract authors (simplified)
            authors = []
            author_pattern = r'<span[^>]*class="[^"]*author[^"]*"[^>]*>([^<]+)</span>'
            author_matches = re.findall(author_pattern, content, re.IGNORECASE)
            if author_matches:
                authors = [author.strip() for author in author_matches[:10]]  # Limit to 10 authors
            
            # Extract year
            year = None
            year_match = re.search(r'(19|20)\d{2}', content)
            if year_match:
                year = int(year_match.group())
            
            # Extract venue (conference/journal name)
            venue_full = ""
            venue_patterns = [
                r'<span[^>]*class="[^"]*venue[^"]*"[^>]*>([^<]+)</span>',
                r'<em>([^<]+)</em>',
                r'In:\s*([^,\n]+)'
            ]
            
            for pattern in venue_patterns:
                venue_match = re.search(pattern, content, re.IGNORECASE)
                if venue_match:
                    venue_full = venue_match.group(1).strip()
                    break
            
            # Determine paper type (very basic heuristic)
            paper_type = "conference"
            if any(word in venue_full.lower() for word in ["journal", "trans", "acm", "ieee"]):
                paper_type = "journal"
            elif any(word in venue_full.lower() for word in ["workshop", "wip"]):
                paper_type = "workshop"
            
            return {
                'title': title,
                'authors': authors,
                'year': year,
                'venue_full': venue_full,
                'venue_acronym': venue_full[:20] if venue_full else "",
                'paper_type': paper_type,
                'dblp_url': dblp_url
            }
            
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch DBLP metadata: {e}")
    
    def extract_from_google_scholar(self, gs_url: str) -> Dict[str, Any]:
        """Extract metadata from Google Scholar URL."""
        # Note: Google Scholar blocks automated requests
        # This is a placeholder implementation
        raise Exception("Google Scholar metadata extraction not implemented due to anti-bot measures")


class ExportService:
    """Service for exporting papers to various formats."""
    
    def export_to_bibtex(self, papers: List[Paper]) -> str:
        """Export papers to BibTeX format."""
        entries = []
        
        for paper in papers:
            # Generate BibTeX key
            first_author = paper.authors[0].full_name.split()[-1] if paper.authors else "Unknown"
            year = paper.year or "Unknown"
            key = f"{first_author}{year}"
            
            # Determine entry type
            entry_type = "article" if paper.paper_type == "journal" else "inproceedings"
            
            entry = f"@{entry_type}{{{key},\n"
            entry += f"  title = {{{paper.title}}},\n"
            
            if paper.authors:
                authors = " and ".join([author.full_name for author in paper.authors])
                entry += f"  author = {{{authors}}},\n"
            
            if paper.venue_full:
                if paper.paper_type == "journal":
                    entry += f"  journal = {{{paper.venue_full}}},\n"
                else:
                    entry += f"  booktitle = {{{paper.venue_full}}},\n"
            
            if paper.year:
                entry += f"  year = {{{paper.year}}},\n"
            
            if paper.pages:
                entry += f"  pages = {{{paper.pages}}},\n"
            
            if paper.doi:
                entry += f"  doi = {{{paper.doi}}},\n"
            
            entry += "}\n"
            entries.append(entry)
        
        return "\n".join(entries)
    
    def export_to_markdown(self, papers: List[Paper]) -> str:
        """Export papers to Markdown format."""
        content = "# Paper List\n\n"
        
        for paper in papers:
            content += f"## {paper.title}\n\n"
            
            if paper.authors:
                authors = ", ".join([author.full_name for author in paper.authors])
                content += f"**Authors:** {authors}\n\n"
            
            if paper.venue_display:
                content += f"**Venue:** {paper.venue_display}\n\n"
            
            if paper.year:
                content += f"**Year:** {paper.year}\n\n"
            
            if paper.abstract:
                content += f"**Abstract:** {paper.abstract}\n\n"
            
            if paper.notes:
                content += f"**Notes:** {paper.notes}\n\n"
            
            content += "---\n\n"
        
        return content
    
    def export_to_html(self, papers: List[Paper]) -> str:
        """Export papers to HTML format."""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>Paper List</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .paper { margin-bottom: 30px; padding: 20px; border: 1px solid #ddd; }
        .title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }
        .authors { font-style: italic; margin-bottom: 5px; }
        .venue { color: #666; margin-bottom: 5px; }
        .abstract { margin-top: 10px; }
        .notes { margin-top: 10px; font-style: italic; }
    </style>
</head>
<body>
    <h1>Paper List</h1>
"""
        
        for paper in papers:
            html += f'    <div class="paper">\n'
            html += f'        <div class="title">{paper.title}</div>\n'
            
            if paper.authors:
                authors = ", ".join([author.full_name for author in paper.authors])
                html += f'        <div class="authors">{authors}</div>\n'
            
            if paper.venue_display and paper.year:
                html += f'        <div class="venue">{paper.venue_display}, {paper.year}</div>\n'
            
            if paper.abstract:
                html += f'        <div class="abstract"><strong>Abstract:</strong> {paper.abstract}</div>\n'
            
            if paper.notes:
                html += f'        <div class="notes"><strong>Notes:</strong> {paper.notes}</div>\n'
            
            html += '    </div>\n'
        
        html += """</body>
</html>"""
        
        return html
    
    def export_to_json(self, papers: List[Paper]) -> str:
        """Export papers to JSON format."""
        paper_list = []
        
        for paper in papers:
            paper_dict = {
                'title': paper.title,
                'authors': [author.full_name for author in paper.authors],
                'year': paper.year,
                'venue_full': paper.venue_full,
                'venue_acronym': paper.venue_acronym,
                'paper_type': paper.paper_type,
                'abstract': paper.abstract,
                'notes': paper.notes,
                'doi': paper.doi,
                'arxiv_id': paper.arxiv_id,
                'dblp_url': paper.dblp_url,
                'collections': [collection.name for collection in paper.collections],
                'added_date': paper.added_date.isoformat() if paper.added_date else None,
                'modified_date': paper.modified_date.isoformat() if paper.modified_date else None,
                'pdf_path': paper.pdf_path
            }
            paper_list.append(paper_dict)
        
        return json.dumps(paper_list, indent=2)


class ChatService:
    """Service for LLM integration and chat functionality."""
    
    def __init__(self):
        self.openai_client = None
        self._initialize_openai()
    
    def _initialize_openai(self):
        """Initialize OpenAI client."""
        try:
            import openai
            api_key = os.getenv('OPENAI_API_KEY')
            if api_key:
                self.openai_client = openai.OpenAI(api_key=api_key)
            else:
                print("Warning: OPENAI_API_KEY not set. Chat functionality will be limited.")
        except ImportError:
            print("Warning: OpenAI package not found. Chat functionality will be limited.")
    
    def chat_about_papers(self, papers: List[Paper], user_query: str) -> str:
        """Chat with LLM about selected papers."""
        if not self.openai_client:
            return "Error: OpenAI client not initialized. Please set OPENAI_API_KEY environment variable."
        
        try:
            # Create context from papers
            context = self._create_paper_context(papers)
            
            # Create prompt
            prompt = f"""You are a research assistant helping with academic papers. 
            
Here are the papers we're discussing:

{context}

User question: {user_query}

Please provide a helpful response based on the papers provided."""
            
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful research assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Error communicating with OpenAI: {str(e)}"
    
    def _create_paper_context(self, papers: List[Paper]) -> str:
        """Create context string from papers."""
        context_parts = []
        
        for i, paper in enumerate(papers, 1):
            context = f"Paper {i}: {paper.title}\n"
            context += f"Authors: {paper.author_names}\n"
            context += f"Year: {paper.year}\n"
            context += f"Venue: {paper.venue_display}\n"
            
            if paper.abstract:
                abstract = paper.abstract[:300] + "..." if len(paper.abstract) > 300 else paper.abstract
                context += f"Abstract: {abstract}\n"
            
            if paper.notes:
                context += f"Notes: {paper.notes}\n"
            
            context_parts.append(context)
        
        return "\n".join(context_parts)
    
    def open_chat_interface(self, papers: List[Paper]):
        """Open chat interface in browser."""
        try:
            # Create a simple HTML page for chat
            html_content = self._create_chat_html(papers)
            
            # Save to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                f.write(html_content)
                temp_path = f.name
            
            # Open in browser
            webbrowser.open(f'file://{temp_path}')
            
            return temp_path
            
        except Exception as e:
            return f"Error opening chat interface: {str(e)}"
    
    def _create_chat_html(self, papers: List[Paper]) -> str:
        """Create HTML for chat interface."""
        context = self._create_paper_context(papers)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>PaperCLI Chat Interface</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .papers {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .chat-area {{ border: 1px solid #ddd; padding: 20px; border-radius: 8px; }}
        .instructions {{ background: #e8f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>PaperCLI Chat Interface</h1>
    
    <div class="instructions">
        <h3>Instructions:</h3>
        <p>Copy the paper information below and paste it into your preferred AI chat interface (ChatGPT, Claude, etc.)</p>
        <p>You can also drag and drop PDF files into the chat interface if available.</p>
    </div>
    
    <div class="papers">
        <h3>Paper Information:</h3>
        <pre>{context}</pre>
    </div>
    
    <div class="chat-area">
        <h3>Chat Interface:</h3>
        <p>Use this space to formulate your questions about the papers above.</p>
        <p>Examples:</p>
        <ul>
            <li>What are the main contributions of these papers?</li>
            <li>How do these papers relate to each other?</li>
            <li>What are the key findings and implications?</li>
            <li>What are the limitations mentioned in these papers?</li>
        </ul>
    </div>
</body>
</html>"""
        
        return html


class SystemService:
    """Service for system integrations."""
    
    def open_pdf(self, pdf_path: str) -> tuple[bool, str]:
        """Open PDF file in system default viewer. Returns (success, error_message)."""
        try:
            if not os.path.exists(pdf_path):
                return False, f"PDF file not found: {pdf_path}"
            
            # Cross-platform PDF opening
            if os.name == 'nt':  # Windows
                os.startfile(pdf_path)
            elif os.name == 'posix':  # macOS and Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    result = subprocess.run(['open', pdf_path], capture_output=True, text=True)
                    if result.returncode != 0:
                        return False, f"Failed to open PDF: {result.stderr}"
                else:  # Linux
                    # Check if xdg-open is available
                    try:
                        result = subprocess.run(['which', 'xdg-open'], capture_output=True, text=True)
                        if result.returncode != 0:
                            return False, "xdg-open not found. Please install xdg-utils or set a PDF viewer."
                        
                        result = subprocess.run(['xdg-open', pdf_path], capture_output=True, text=True)
                        if result.returncode != 0:
                            return False, f"Failed to open PDF: {result.stderr}"
                    except FileNotFoundError:
                        return False, "xdg-open not found. Please install xdg-utils or set a PDF viewer."
            
            return True, ""
            
        except Exception as e:
            return False, f"Error opening PDF: {str(e)}"
    
    def open_file_explorer(self, file_path: str) -> bool:
        """Open file explorer pointing to the file."""
        try:
            if not os.path.exists(file_path):
                return False
            
            # Cross-platform file explorer opening
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', file_path])
            elif os.name == 'posix':  # macOS and Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    subprocess.run(['open', '-R', file_path])
                else:  # Linux
                    # Open parent directory
                    parent_dir = os.path.dirname(file_path)
                    subprocess.run(['xdg-open', parent_dir])
            
            return True
            
        except Exception as e:
            # Return False and let the caller handle the error message
            return False
    
    def copy_to_clipboard(self, text: str) -> bool:
        """Copy text to system clipboard."""
        try:
            # Try using pyperclip if available
            try:
                import pyperclip
                pyperclip.copy(text)
                return True
            except ImportError:
                pass
            
            # Fallback to system commands
            if os.name == 'nt':  # Windows
                subprocess.run(['clip'], input=text.encode(), check=True)
            elif os.name == 'posix':  # macOS and Linux
                if os.uname().sysname == 'Darwin':  # macOS
                    subprocess.run(['pbcopy'], input=text.encode(), check=True)
                else:  # Linux
                    subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
            
            return True
            
        except Exception as e:
            # Return False and let the caller handle the error message
            return False
    
    def download_arxiv_pdf(self, arxiv_id: str, download_dir: str) -> Optional[str]:
        """Download PDF from arXiv."""
        try:
            # Clean arXiv ID
            arxiv_id = re.sub(r'arxiv[:\s]*', '', arxiv_id, flags=re.IGNORECASE)
            arxiv_id = re.sub(r'[^\d\.]', '', arxiv_id)
            
            # Create download directory
            os.makedirs(download_dir, exist_ok=True)
            
            # Download PDF
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            response = requests.get(pdf_url, timeout=60)
            response.raise_for_status()
            
            # Save to file
            filename = f"arxiv_{arxiv_id}.pdf"
            filepath = os.path.join(download_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return filepath
            
        except Exception as e:
            # Return None and let the caller handle the error message
            return None