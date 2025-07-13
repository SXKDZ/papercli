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
from datetime import datetime
from sqlalchemy import or_, and_
from fuzzywuzzy import fuzz
from titlecase import titlecase

from .database import get_db_session
from .models import Paper, Author, Collection


def fix_broken_lines(text: str) -> str:
    """Fix broken lines in text - join lines that are not proper sentence endings."""
    if not text:
        return text
    # Join lines unless next line starts with capital letter
    text = re.sub(r'\n(?![A-Z])', ' ', text)
    # Normalize multiple spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


class PaperService:
    """Service for managing papers."""

    def get_all_papers(self) -> List[Paper]:
        """Get all papers ordered by added date (newest first)."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload

            # Eagerly load relationships to avoid detached instance errors
            papers = (
                session.query(Paper)
                .options(joinedload(Paper.authors), joinedload(Paper.collections))
                .order_by(Paper.added_date.desc())
                .all()
            )

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

            paper = (
                session.query(Paper)
                .options(joinedload(Paper.authors), joinedload(Paper.collections))
                .filter(Paper.id == paper_id)
                .first()
            )

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

    def update_paper(
        self, paper_id: int, paper_data: Dict[str, Any]
    ) -> tuple[Optional[Paper], str]:
        """Update an existing paper.
        
        Returns:
            tuple[Optional[Paper], str]: (updated_paper, error_message)
            If successful: (paper, "")
            If error: (None, error_message) or (paper, pdf_error_message)
        """
        with get_db_session() as session:
            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if not paper:
                return None, f"Paper with ID {paper_id} not found"
            
            pdf_error = ""
            
            try:
                # Handle PDF path processing if present
                if "pdf_path" in paper_data and paper_data["pdf_path"]:
                    pdf_manager = PDFManager()
                    
                    # Create paper data for filename generation
                    current_paper_data = {
                        'title': paper_data.get('title', paper.title),
                        'authors': [author.full_name for author in paper.authors] if paper.authors else [],
                        'year': paper_data.get('year', paper.year)
                    }
                    
                    new_pdf_path, error = pdf_manager.process_pdf_path(
                        paper_data["pdf_path"], 
                        current_paper_data, 
                        paper.pdf_path
                    )
                    
                    if error:
                        pdf_error = f"PDF processing failed: {error}"
                        # Remove pdf_path from update data to prevent invalid path from being saved
                        paper_data.pop("pdf_path")
                    else:
                        paper_data["pdf_path"] = new_pdf_path

                # Handle relationships by merging the detached objects from the dialog
                # into the current session. This avoids primary key conflicts.
                if "authors" in paper_data:
                    authors = paper_data.pop("authors")
                    paper.authors = [session.merge(author) for author in authors]

                if "collections" in paper_data:
                    collections = paper_data.pop("collections")
                    paper.collections = [
                        session.merge(collection) for collection in collections
                    ]

                # Update remaining attributes
                for key, value in paper_data.items():
                    if hasattr(paper, key):
                        setattr(paper, key, value)

                paper.modified_date = datetime.utcnow()
                session.commit()
                session.refresh(paper)

                # Expunge to follow the detached object pattern used elsewhere in the app
                session.expunge(paper)
                
                return paper, pdf_error
                
            except Exception as e:
                session.rollback()
                return None, f"Failed to update paper: {str(e)}"

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
            papers_to_delete = (
                session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
            )
            if not papers_to_delete:
                return 0

            for paper in papers_to_delete:
                if paper.pdf_path and os.path.exists(paper.pdf_path):
                    try:
                        os.remove(paper.pdf_path)
                    except Exception:
                        # Log this error, but don't prevent db deletion
                        pass
                session.delete(paper)

            session.commit()
            return len(papers_to_delete)

    def add_paper_from_metadata(
        self,
        paper_data: Dict[str, Any],
        authors: List[str],
        collections: List[str] = None,
    ) -> Paper:
        """Add paper with authors and collections."""
        with get_db_session() as session:
            from sqlalchemy.orm import joinedload

            # Check for existing paper by preprint ID, DOI, or title
            existing_paper = None
            if paper_data.get("preprint_id"):
                existing_paper = (
                    session.query(Paper)
                    .filter(Paper.preprint_id == paper_data["preprint_id"])
                    .first()
                )
            elif paper_data.get("doi"):
                existing_paper = (
                    session.query(Paper).filter(Paper.doi == paper_data["doi"]).first()
                )
            elif paper_data.get("title"):
                existing_paper = (
                    session.query(Paper)
                    .filter(Paper.title == paper_data["title"])
                    .first()
                )

            if existing_paper:
                raise Exception(
                    f"Paper already exists in database (ID: {existing_paper.id})"
                )

            # Create paper
            paper = Paper()
            for key, value in paper_data.items():
                if hasattr(paper, key) and value is not None:
                    setattr(paper, key, value)

            session.add(paper)
            session.flush()  # Get the paper ID without committing

            # Add authors
            for author_name in authors:
                author = (
                    session.query(Author)
                    .filter(Author.full_name == author_name)
                    .first()
                )
                if not author:
                    author = Author(full_name=author_name)
                    session.add(author)
                paper.authors.append(author)

            # Add collections
            if collections:
                for collection_name in collections:
                    collection = (
                        session.query(Collection)
                        .filter(Collection.name == collection_name)
                        .first()
                    )
                    if not collection:
                        collection = Collection(name=collection_name)
                        session.add(collection)
                        session.flush()  # Ensure collection has an ID

                    # Double-check for existing association in the database
                    from sqlalchemy import text

                    existing_association = session.execute(
                        text(
                            "SELECT 1 FROM paper_collections WHERE paper_id = :paper_id AND collection_id = :collection_id"
                        ),
                        {"paper_id": paper.id, "collection_id": collection.id},
                    ).first()

                    if not existing_association and collection not in paper.collections:
                        paper.collections.append(collection)

            session.commit()
            session.refresh(paper)

            # Create a new query with eager loading to get a properly attached instance
            paper_with_relationships = (
                session.query(Paper)
                .options(joinedload(Paper.authors), joinedload(Paper.collections))
                .filter(Paper.id == paper.id)
                .first()
            )

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
            authors = (
                session.query(Author).filter(Author.full_name.ilike(f"%{query}%")).all()
            )
            # Force load all attributes and expunge to make detached
            for author in authors:
                _ = author.full_name  # Ensure name is loaded
            session.expunge_all()
            return authors


class CollectionService:
    """Service for managing collections."""

    def get_all_collections(self) -> List[Collection]:
        """Get all collections with their papers loaded."""
        with get_db_session() as session:
            collections = session.query(Collection).order_by(Collection.name).all()
            # Force load all attributes and relationships
            for collection in collections:
                _ = collection.name  # Ensure name is loaded
                _ = collection.description  # Ensure description is loaded
                _ = collection.papers  # Force load papers relationship
                # Also force load paper details to prevent lazy loading issues
                for paper in collection.papers:
                    _ = paper.title
                    _ = paper.authors  # Force load authors too
            session.expunge_all()
            return collections

    def get_or_create_collection(
        self, name: str, description: str = None
    ) -> Collection:
        """Get existing collection or create new one."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter(Collection.name == name).first()
            )
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
            collection = (
                session.query(Collection)
                .filter(Collection.name == collection_name)
                .first()
            )
            if not collection:
                collection = Collection(name=collection_name)
                session.add(collection)
                session.flush()  # Ensure new collection has an ID before use

            if collection not in paper.collections:
                paper.collections.append(collection)
                session.commit()
                return True
            else:
                return False

    def add_papers_to_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> int:
        """Add multiple papers to a collection.

        Returns the number of papers successfully added.
        """
        with get_db_session() as session:
            # Get or create the collection
            collection = (
                session.query(Collection)
                .filter(Collection.name == collection_name)
                .first()
            )
            if not collection:
                collection = Collection(name=collection_name)
                session.add(collection)
                session.flush()  # Ensure collection has an ID before proceeding

            # Get papers to be added
            papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()

            added_count = 0
            for paper in papers:
                if collection not in paper.collections:
                    paper.collections.append(collection)
                    added_count += 1

            if added_count > 0:
                session.commit()

            return added_count

    def remove_papers_from_collection(
        self, paper_ids: List[int], collection_name: str
    ) -> tuple[int, list[str]]:
        """Remove multiple papers from a collection.

        Returns a tuple of (removed_count, errors).
        """
        with get_db_session() as session:
            collection = (
                session.query(Collection)
                .filter(Collection.name == collection_name)
                .first()
            )
            if not collection:
                return 0, [f"Collection '{collection_name}' not found."]

            papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()

            removed_count = 0
            errors = []

            for paper in papers:
                if collection in paper.collections:
                    paper.collections.remove(collection)
                    removed_count += 1
                else:
                    errors.append(
                        f"Paper '{paper.title[:30]}...' does not belong to the collection: {collection_name}"
                    )

            if removed_count > 0:
                session.commit()

            return removed_count, errors

    def update_collection_name(self, old_name: str, new_name: str) -> bool:
        """Update collection name."""
        with get_db_session() as session:
            collection = (
                session.query(Collection).filter(Collection.name == old_name).first()
            )
            if not collection:
                return False

            # Check if new name already exists
            existing = (
                session.query(Collection).filter(Collection.name == new_name).first()
            )
            if existing and existing.id != collection.id:
                return False

            collection.name = new_name
            session.commit()
            return True

    def remove_paper_from_collection(self, paper_id: int, collection_name: str) -> bool:
        """Remove a single paper from collection."""
        with get_db_session() as session:
            collection = (
                session.query(Collection)
                .filter(Collection.name == collection_name)
                .first()
            )
            if not collection:
                return False

            paper = session.query(Paper).filter(Paper.id == paper_id).first()
            if not paper:
                return False

            if collection in paper.collections:
                paper.collections.remove(collection)
                session.commit()
                return True
            return False

    def create_collection(self, name: str, description: str = None) -> Collection:
        """Create a new collection."""
        with get_db_session() as session:
            # Check if collection already exists
            existing = session.query(Collection).filter(Collection.name == name).first()
            if existing:
                return None

            collection = Collection(name=name, description=description)
            session.add(collection)
            session.commit()
            session.refresh(collection)

            # Force load attributes before expunging
            _ = collection.name
            _ = collection.description
            _ = collection.papers
            session.expunge(collection)
            return collection


class SearchService:
    """Service for searching and filtering papers."""

    def search_papers(self, query: str, fields: List[str] = None) -> List[Paper]:
        """Search papers by query in specified fields with fuzzy matching."""
        if fields is None:
            fields = ["title", "abstract", "authors", "venue"]

        with get_db_session() as session:
            conditions = []

            if "title" in fields:
                conditions.append(Paper.title.ilike(f"%{query}%"))
            if "abstract" in fields:
                conditions.append(Paper.abstract.ilike(f"%{query}%"))
            if "venue" in fields:
                conditions.append(
                    or_(
                        Paper.venue_full.ilike(f"%{query}%"),
                        Paper.venue_acronym.ilike(f"%{query}%"),
                    )
                )
            if "notes" in fields:
                conditions.append(Paper.notes.ilike(f"%{query}%"))

            # Search in authors requires join
            if "authors" in fields:
                papers_by_author = (
                    session.query(Paper)
                    .join(Paper.authors)
                    .filter(Author.full_name.ilike(f"%{query}%"))
                    .all()
                )
                # Add author search results
                paper_ids = [p.id for p in papers_by_author]
                if paper_ids:
                    conditions.append(Paper.id.in_(paper_ids))

            if conditions:
                from sqlalchemy.orm import joinedload

                papers = (
                    session.query(Paper)
                    .options(joinedload(Paper.authors), joinedload(Paper.collections))
                    .filter(or_(*conditions))
                    .order_by(Paper.added_date.desc())
                    .all()
                )

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
            all_papers = (
                session.query(Paper)
                .options(joinedload(Paper.authors), joinedload(Paper.collections))
                .all()
            )

            scored_papers = []

            for paper in all_papers:
                # Force load relationships while in session
                _ = paper.authors
                _ = paper.collections

                # Calculate fuzzy match scores
                title_score = fuzz.partial_ratio(query.lower(), paper.title.lower())
                author_score = max(
                    [
                        fuzz.partial_ratio(query.lower(), author.full_name.lower())
                        for author in paper.authors
                    ]
                    or [0]
                )
                venue_score = max(
                    [
                        (
                            fuzz.partial_ratio(query.lower(), paper.venue_full.lower())
                            if paper.venue_full
                            else 0
                        ),
                        (
                            fuzz.partial_ratio(
                                query.lower(), paper.venue_acronym.lower()
                            )
                            if paper.venue_acronym
                            else 0
                        ),
                    ]
                )

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
                joinedload(Paper.authors), joinedload(Paper.collections)
            )

            if "year" in filters:
                query = query.filter(Paper.year == filters["year"])

            if "year_range" in filters:
                start, end = filters["year_range"]
                query = query.filter(and_(Paper.year >= start, Paper.year <= end))

            if "paper_type" in filters:
                query = query.filter(Paper.paper_type == filters["paper_type"])

            if "venue" in filters:
                query = query.filter(
                    or_(
                        Paper.venue_full.ilike(f'%{filters["venue"]}%'),
                        Paper.venue_acronym.ilike(f'%{filters["venue"]}%'),
                    )
                )

            if "collection" in filters:
                query = query.join(Paper.collections).filter(
                    Collection.name == filters["collection"]
                )

            if "author" in filters:
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
        arxiv_id = re.sub(r"arxiv[:\s]*", "", arxiv_id, flags=re.IGNORECASE)
        arxiv_id = re.sub(r"[^\d\.]", "", arxiv_id)

        try:
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Parse XML response
            root = ET.fromstring(response.content)

            # Define namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            # Find the entry
            entry = root.find(".//atom:entry", ns)
            if entry is None:
                raise Exception("Paper not found on arXiv")

            # Extract title
            title_elem = entry.find("atom:title", ns)
            title = (
                title_elem.text.strip() if title_elem is not None else "Unknown Title"
            )
            # Fix broken lines and apply titlecase to arXiv titles
            title = fix_broken_lines(title)
            title = titlecase(title)

            # Extract abstract
            summary_elem = entry.find("atom:summary", ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else ""
            # Fix broken lines in abstract
            abstract = fix_broken_lines(abstract)

            # Extract authors
            authors = []
            for author in entry.findall("atom:author", ns):
                name_elem = author.find("atom:name", ns)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())

            # Extract publication date
            published_elem = entry.find("atom:published", ns)
            year = None
            if published_elem is not None:
                published_date = published_elem.text
                year_match = re.search(r"(\d{4})", published_date)
                if year_match:
                    year = int(year_match.group(1))
            
            # Extract arXiv category
            category = None
            category_elem = entry.find("atom:category", ns)
            if category_elem is not None:
                category = category_elem.get("term")

            # Extract DOI if available
            doi = None
            doi_elem = entry.find("atom:id", ns)
            if doi_elem is not None:
                doi_match = re.search(r"doi:(.+)", doi_elem.text)
                if doi_match:
                    doi = doi_match.group(1)

            return {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "preprint_id": f"arXiv {arxiv_id}",  # Store as "arXiv 2505.15134"
                "category": category,
                "doi": doi,
                "paper_type": "preprint",
                "venue_full": "arXiv",
                "venue_acronym": None,  # No acronym for arXiv papers
            }

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch arXiv metadata: {e}")
        except ET.ParseError as e:
            raise Exception(f"Failed to parse arXiv response: {e}")

    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Extract metadata from PDF file."""
        try:
            import PyPDF2

            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                # Extract metadata
                metadata = pdf_reader.metadata

                # Extract title from metadata or first page
                title = (
                    metadata.get("/Title", "Unknown Title")
                    if metadata
                    else "Unknown Title"
                )
                # Fix broken lines and apply titlecase to PDF titles
                title = fix_broken_lines(title)
                title = titlecase(title)

                # Extract author from metadata
                author = metadata.get("/Author", "") if metadata else ""
                authors = [author] if author else []

                # Extract text from first page for additional info
                if pdf_reader.pages:
                    first_page = pdf_reader.pages[0]
                    text = first_page.extract_text()

                    # Try to extract year from text
                    year_match = re.search(r"(19|20)\d{2}", text)
                    year = int(year_match.group()) if year_match else None
                else:
                    year = None

                return {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "pdf_path": pdf_path,
                    "paper_type": "unknown",
                }

        except Exception as e:
            raise Exception(f"Failed to extract PDF metadata: {e}")

    def extract_from_dblp(self, dblp_url: str) -> Dict[str, Any]:
        """Extract metadata from DBLP URL using BibTeX endpoint and LLM processing."""
        try:
            import bibtexparser
            
            # Convert DBLP HTML URL to BibTeX URL
            bib_url = self._convert_dblp_url_to_bib(dblp_url)
            
            # Fetch BibTeX data
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(bib_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            bibtex_content = response.text.strip()
            if not bibtex_content:
                raise Exception("Empty BibTeX response")
            
            # Parse BibTeX using bibtexparser
            parser = bibtexparser.bparser.BibTexParser(common_strings=True)
            bib_database = bibtexparser.loads(bibtex_content, parser=parser)
            
            if not bib_database.entries:
                raise Exception("No entries found in BibTeX data")
            
            entry = bib_database.entries[0]  # Take the first entry
            
            # Get venue field based on entry type
            venue_field = ""
            paper_type = "conference"
            if 'booktitle' in entry:
                venue_field = entry['booktitle']
                paper_type = "conference"
            elif 'journal' in entry:
                venue_field = entry['journal']
                paper_type = "journal"
            
            # Extract venue names using LLM
            venue_info = self._extract_venue_with_llm(venue_field)
            
            # Parse authors
            authors = []
            if 'author' in entry:
                # Split by 'and' and clean up, handling multiline authors
                author_text = re.sub(r'\s+', ' ', entry['author'])  # Normalize whitespace
                for author in author_text.split(' and '):
                    author = author.strip()
                    if author:
                        authors.append(author)
            
            # Extract year
            year = None
            if 'year' in entry:
                try:
                    year = int(entry['year'])
                except ValueError:
                    pass
            
            # Extract and clean title
            title = entry.get('title', 'Unknown Title')
            title = fix_broken_lines(title)  # Fix any line breaks in title
            title = titlecase(title)  # Apply title case

            # Extract and clean abstract if present (though DBLP usually doesn't have abstracts)
            abstract = ""
            if 'abstract' in entry:
                abstract = fix_broken_lines(entry['abstract'])

            # Build result
            result = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "year": year,
                "venue_full": venue_info.get('venue_full', venue_field),
                "venue_acronym": venue_info.get('venue_acronym', ''),
                "paper_type": paper_type,
                "url": entry.get('url', dblp_url),  # Use BibTeX URL if available, fallback to DBLP URL
                "pages": entry.get('pages'),
                "doi": entry.get('doi'),
                "volume": entry.get('volume'),
                "issue": entry.get('number'),
            }
            
            return result

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch DBLP metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process DBLP metadata: {e}")

    def _convert_dblp_url_to_bib(self, dblp_url: str) -> str:
        """Convert DBLP HTML URL to BibTeX URL."""
        # Handle both .html and regular DBLP URLs
        if '.html' in dblp_url:
            # Remove .html and any query parameters, then add .bib
            base_url = dblp_url.split('.html')[0]
            bib_url = f"{base_url}.bib?param=1"
        else:
            # Direct DBLP record URL
            bib_url = f"{dblp_url}.bib?param=1"
        
        return bib_url

    def _extract_venue_with_llm(self, venue_field: str) -> Dict[str, str]:
        """Extract venue name and acronym using LLM."""
        if not venue_field:
            return {'venue_full': '', 'venue_acronym': ''}
        
        # Initialize chat service if not available
        if not hasattr(self, '_chat_service'):
            self._chat_service = ChatService()
        
        if not self._chat_service.openai_client:
            # Fallback without LLM
            return {
                'venue_full': venue_field,
                'venue_acronym': self._extract_acronym_fallback(venue_field)
            }
        
        try:
            prompt = f"""Given this conference/journal venue field from a DBLP BibTeX entry: "{venue_field}"

Please extract:
1. venue_full: The full venue name in the format "International Conference on XXX" (ignore "The", "First", "Second", etc.)
2. venue_acronym: The short acronym (e.g., ICML, NIPS, ICLR)

Respond in this exact JSON format:
{{"venue_full": "...", "venue_acronym": "..."}}"""

            response = self._chat_service.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts venue information from academic paper titles."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.1,
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Clean up markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith('```'):
                response_text = response_text[3:]   # Remove ```
            if response_text.endswith('```'):
                response_text = response_text[:-3]  # Remove trailing ```
            response_text = response_text.strip()
            
            # Try to parse JSON response
            try:
                venue_info = json.loads(response_text)
                return {
                    'venue_full': venue_info.get('venue_full', venue_field),
                    'venue_acronym': venue_info.get('venue_acronym', '')
                }
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                return {
                    'venue_full': venue_field,
                    'venue_acronym': self._extract_acronym_fallback(venue_field)
                }
        
        except Exception as e:
            # Fallback on any error
            return {
                'venue_full': venue_field,
                'venue_acronym': self._extract_acronym_fallback(venue_field)
            }

    def _extract_acronym_fallback(self, venue_field: str) -> str:
        """Fallback method to extract acronym without LLM."""
        if not venue_field:
            return ""
        
        # Common conference acronyms
        acronym_map = {
            'international conference on machine learning': 'ICML',
            'neural information processing systems': 'NeurIPS',
            'international conference on learning representations': 'ICLR',
            'ieee conference on computer vision and pattern recognition': 'CVPR',
            'international conference on computer vision': 'ICCV',
            'european conference on computer vision': 'ECCV',
            'conference on empirical methods in natural language processing': 'EMNLP',
            'annual meeting of the association for computational linguistics': 'ACL',
            'international joint conference on artificial intelligence': 'IJCAI',
            'aaai conference on artificial intelligence': 'AAAI',
        }
        
        venue_lower = venue_field.lower()
        for full_name, acronym in acronym_map.items():
            if full_name in venue_lower:
                return acronym
        
        # Extract first letters of significant words
        words = re.findall(r'\b[A-Z][a-z]*', venue_field)
        if words:
            return ''.join(word[0].upper() for word in words[:4])
        
        return ""

    def extract_from_openreview(self, openreview_id: str) -> Dict[str, Any]:
        """Extract metadata from OpenReview paper ID."""
        try:
            # Clean OpenReview ID - extract just the ID part
            if openreview_id.startswith('https://openreview.net/forum?id='):
                openreview_id = openreview_id.split('id=')[1]
            elif openreview_id.startswith('https://openreview.net/pdf?id='):
                openreview_id = openreview_id.split('id=')[1]
            
            # Remove any additional parameters
            openreview_id = openreview_id.split('&')[0].split('#')[0]
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # Try newer API v2 format first
            api_url_v2 = f"https://api2.openreview.net/notes?forum={openreview_id}&limit=1000&details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags"
            
            try:
                response = requests.get(api_url_v2, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                if data.get('notes') and len(data['notes']) > 0:
                    return self._parse_openreview_v2_response(data, openreview_id)
            except (requests.RequestException, KeyError):
                pass  # Fall back to older API format
            
            # Try older API format if v2 fails
            api_url_v1 = f"https://api.openreview.net/notes?forum={openreview_id}&trash=true&details=replyCount%2Cwritable%2Crevisions%2Coriginal%2Coverwriting%2Cinvitation%2Ctags&limit=1000&offset=0"
            
            response = requests.get(api_url_v1, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('notes') or len(data['notes']) == 0:
                raise Exception("Paper not found on OpenReview")
            
            return self._parse_openreview_v1_response(data, openreview_id)
            
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch OpenReview metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process OpenReview metadata: {e}")
    
    def _parse_openreview_v2_response(self, data: Dict[str, Any], openreview_id: str) -> Dict[str, Any]:
        """Parse OpenReview API v2 response."""
        # Find the main submission note (where id equals forum)
        note = None
        for n in data['notes']:
            if n.get('id') == n.get('forum'):
                note = n
                break
        
        if not note:
            # Fallback to first note if main submission not found
            note = data['notes'][0]
            
        content = note.get('content', {})
        
        # Extract title
        title = content.get('title', {}).get('value', 'Unknown Title')
        title = fix_broken_lines(title)
        title = titlecase(title)
        
        # Extract abstract
        abstract = content.get('abstract', {}).get('value', '')
        if abstract:
            abstract = fix_broken_lines(abstract)
        
        # Extract authors
        authors = []
        authors_data = content.get('authors', {}).get('value', [])
        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]
        
        # Extract venue information using LLM
        venue_info = content.get('venue', {}).get('value', '')
        venue_data = self._extract_venue_with_llm(venue_info)
        
        # Extract year from venue or other sources
        year = None
        if venue_info:
            year_match = re.search(r'(\d{4})', venue_info)
            if year_match:
                year = int(year_match.group(1))
        
        return {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "venue_full": venue_data.get('venue_full', venue_info),
            "venue_acronym": venue_data.get('venue_acronym', ''),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }
    
    def _parse_openreview_v1_response(self, data: Dict[str, Any], openreview_id: str) -> Dict[str, Any]:
        """Parse OpenReview API v1 response."""
        # Find the main submission note (where id equals forum)
        note = None
        for n in data['notes']:
            if n.get('id') == n.get('forum'):
                note = n
                break
        
        if not note:
            # Fallback to first note if main submission not found
            note = data['notes'][0]
            
        content = note.get('content', {})
        
        # Extract title (v1 format may have direct string values)
        title = content.get('title', 'Unknown Title')
        if isinstance(title, dict):
            title = title.get('value', 'Unknown Title')
        title = fix_broken_lines(title)
        title = titlecase(title)
        
        # Extract abstract
        abstract = content.get('abstract', '')
        if isinstance(abstract, dict):
            abstract = abstract.get('value', '')
        if abstract:
            abstract = fix_broken_lines(abstract)
        
        # Extract authors
        authors = []
        authors_data = content.get('authors', [])
        if isinstance(authors_data, dict):
            authors_data = authors_data.get('value', [])
        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]
        
        # Extract venue information using LLM
        venue_info = content.get('venue', '')
        if isinstance(venue_info, dict):
            venue_info = venue_info.get('value', '')
        venue_data = self._extract_venue_with_llm(venue_info)
        
        # Extract year from venue or other sources
        year = None
        if venue_info:
            year_match = re.search(r'(\d{4})', venue_info)
            if year_match:
                year = int(year_match.group(1))
        
        return {
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "year": year,
            "venue_full": venue_data.get('venue_full', venue_info),
            "venue_acronym": venue_data.get('venue_acronym', ''),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }

    def extract_from_google_scholar(self, gs_url: str) -> Dict[str, Any]:
        """Extract metadata from Google Scholar URL."""
        # Note: Google Scholar blocks automated requests
        # This is a placeholder implementation
        raise Exception(
            "Google Scholar metadata extraction not implemented due to anti-bot measures"
        )


class ExportService:
    """Service for exporting papers to various formats."""

    def export_to_bibtex(self, papers: List[Paper]) -> str:
        """Export papers to BibTeX format."""
        entries = []

        for paper in papers:
            # Generate BibTeX key
            first_author = (
                paper.authors[0].full_name.split()[-1] if paper.authors else "Unknown"
            )
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

            html += "    </div>\n"

        html += """</body>
</html>"""

        return html

    def export_to_json(self, papers: List[Paper]) -> str:
        """Export papers to JSON format."""
        paper_list = []

        for paper in papers:
            paper_dict = {
                "title": paper.title,
                "authors": [author.full_name for author in paper.authors],
                "year": paper.year,
                "venue_full": paper.venue_full,
                "venue_acronym": paper.venue_acronym,
                "paper_type": paper.paper_type,
                "abstract": paper.abstract,
                "notes": paper.notes,
                "doi": paper.doi,
                "preprint_id": paper.preprint_id,
                "category": paper.category,
                "url": paper.url,
                "collections": [collection.name for collection in paper.collections],
                "added_date": (
                    paper.added_date.isoformat() if paper.added_date else None
                ),
                "modified_date": (
                    paper.modified_date.isoformat() if paper.modified_date else None
                ),
                "pdf_path": paper.pdf_path,
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

            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.openai_client = openai.OpenAI(api_key=api_key)
            else:
                print(
                    "Warning: OPENAI_API_KEY not set. Chat functionality will be limited."
                )
        except ImportError:
            print(
                "Warning: OpenAI package not found. Chat functionality will be limited."
            )

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
                    {
                        "role": "system",
                        "content": "You are a helpful research assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.7,
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
                abstract = (
                    paper.abstract[:300] + "..."
                    if len(paper.abstract) > 300
                    else paper.abstract
                )
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

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False
            ) as f:
                f.write(html_content)
                temp_path = f.name

            # Open in browser
            webbrowser.open(f"file://{temp_path}")

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
            if os.name == "nt":  # Windows
                os.startfile(pdf_path)
            elif os.name == "posix":  # macOS and Linux
                if os.uname().sysname == "Darwin":  # macOS
                    result = subprocess.run(
                        ["open", pdf_path], capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        return False, f"Failed to open PDF: {result.stderr}"
                else:  # Linux
                    # Check if xdg-open is available
                    try:
                        result = subprocess.run(
                            ["which", "xdg-open"], capture_output=True, text=True
                        )
                        if result.returncode != 0:
                            return (
                                False,
                                "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                            )

                        result = subprocess.run(
                            ["xdg-open", pdf_path], capture_output=True, text=True
                        )
                        if result.returncode != 0:
                            return False, f"Failed to open PDF: {result.stderr}"
                    except FileNotFoundError:
                        return (
                            False,
                            "xdg-open not found. Please install xdg-utils or set a PDF viewer.",
                        )

            return True, ""

        except Exception as e:
            return False, f"Error opening PDF: {str(e)}"

    def open_file_explorer(self, file_path: str) -> bool:
        """Open file explorer pointing to the file."""
        try:
            if not os.path.exists(file_path):
                return False

            # Cross-platform file explorer opening
            if os.name == "nt":  # Windows
                subprocess.run(["explorer", "/select,", file_path])
            elif os.name == "posix":  # macOS and Linux
                if os.uname().sysname == "Darwin":  # macOS
                    subprocess.run(["open", "-R", file_path])
                else:  # Linux
                    # Open parent directory
                    parent_dir = os.path.dirname(file_path)
                    subprocess.run(["xdg-open", parent_dir])

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
            if os.name == "nt":  # Windows
                subprocess.run(["clip"], input=text.encode(), check=True)
            elif os.name == "posix":  # macOS and Linux
                if os.uname().sysname == "Darwin":  # macOS
                    subprocess.run(["pbcopy"], input=text.encode(), check=True)
                else:  # Linux
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode(),
                        check=True,
                    )

            return True

        except Exception as e:
            # Return False and let the caller handle the error message
            return False

    def download_pdf(self, source: str, identifier: str, download_dir: str, paper_data: Dict[str, Any] = None) -> Optional[str]:
        """Download PDF from various sources (arXiv, OpenReview, etc.)."""
        try:
            # Create download directory
            os.makedirs(download_dir, exist_ok=True)

            # Generate URL based on source
            if source == "arxiv":
                # Clean arXiv ID
                clean_id = re.sub(r"arxiv[:\s]*", "", identifier, flags=re.IGNORECASE)
                clean_id = re.sub(r"[^\d\.]", "", clean_id)
                pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
            elif source == "openreview":
                pdf_url = f"https://openreview.net/pdf?id={identifier}"
            else:
                raise ValueError(f"Unsupported source: {source}")

            # Use PDFManager to handle everything
            pdf_manager = PDFManager()
            filename = pdf_manager._generate_pdf_filename(paper_data, pdf_url)
            filepath = os.path.join(download_dir, filename)
            
            pdf_path, error_msg = pdf_manager._download_pdf_from_url(pdf_url, filepath)
            
            if error_msg:
                return None
                
            return pdf_path

        except Exception as e:
            return None


class PDFManager:
    """Service for managing PDF files with smart naming and handling."""

    def __init__(self):
        self.pdf_dir = None
        self._setup_pdf_directory()

    def _setup_pdf_directory(self):
        """Setup PDF directory path."""
        from .database import get_db_manager
        db_manager = get_db_manager()
        self.pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")
        os.makedirs(self.pdf_dir, exist_ok=True)

    def _generate_pdf_filename(self, paper_data: Dict[str, Any], pdf_path: str) -> str:
        """Generate a smart filename for the PDF based on paper metadata."""
        import hashlib
        import secrets

        # Extract first author last name
        authors = paper_data.get('authors', [])
        if authors and isinstance(authors[0], str):
            first_author = authors[0]
            # Extract last name (assume last word is surname)
            author_lastname = first_author.split()[-1].lower()
            # Remove non-alphanumeric characters
            author_lastname = re.sub(r'[^\w]', '', author_lastname)
        else:
            author_lastname = "unknown"

        # Extract year
        year = paper_data.get('year', 'nodate')

        # Extract first significant word from title
        title = paper_data.get('title', 'untitled')
        # Split into words and find first significant word (length > 3, not common words)
        common_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'man', 'run', 'say', 'she', 'too', 'use'}
        words = re.findall(r'\b[a-zA-Z]+\b', title.lower())
        first_word = "untitled"
        for word in words:
            if len(word) > 3 and word not in common_words:
                first_word = word
                break

        # Generate short hash from file content or path
        try:
            if os.path.exists(pdf_path):
                # Hash from file content
                with open(pdf_path, 'rb') as f:
                    content = f.read(8192)  # Read first 8KB for hash
                    file_hash = hashlib.md5(content).hexdigest()[:6]
            else:
                # Hash from URL or path string
                file_hash = hashlib.md5(pdf_path.encode()).hexdigest()[:6]
        except Exception:
            # Fallback to random hash
            file_hash = secrets.token_hex(3)

        # Combine all parts
        filename = f"{author_lastname}{year}{first_word}_{file_hash}.pdf"
        
        # Ensure filename is filesystem-safe
        filename = re.sub(r'[^\w\-_.]', '', filename)
        
        return filename

    def process_pdf_path(self, pdf_input: str, paper_data: Dict[str, Any], old_pdf_path: str = None) -> tuple[str, str]:
        """
        Process PDF input (local file, URL, or invalid) and return the final path.
        
        Returns:
            tuple[str, str]: (final_pdf_path, error_message)
            If successful: (path, "")
            If error: ("", error_message)
        """
        if not pdf_input or not pdf_input.strip():
            return "", "PDF path cannot be empty"

        pdf_input = pdf_input.strip()

        # Determine input type
        is_url = pdf_input.startswith(('http://', 'https://'))
        is_local_file = os.path.exists(pdf_input) and os.path.isfile(pdf_input)

        if not is_url and not is_local_file:
            return "", f"Invalid PDF input: '{pdf_input}' is neither a valid file path nor a URL"

        try:
            # Generate target filename
            target_filename = self._generate_pdf_filename(paper_data, pdf_input)
            target_path = os.path.join(self.pdf_dir, target_filename)

            # Clean up old PDF if it exists and is different from target
            if old_pdf_path and os.path.exists(old_pdf_path) and old_pdf_path != target_path:
                try:
                    os.remove(old_pdf_path)
                except Exception:
                    pass  # Don't fail if cleanup fails

            if is_local_file:
                # Copy local file to PDF directory
                import shutil
                shutil.copy2(pdf_input, target_path)
                return target_path, ""

            elif is_url:
                # Download URL to PDF directory
                return self._download_pdf_from_url(pdf_input, target_path)

        except Exception as e:
            return "", f"Error processing PDF: {str(e)}"

    def _download_pdf_from_url(self, url: str, target_path: str) -> tuple[str, str]:
        """Download PDF from URL to target path."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            response.raise_for_status()

            # Check if content is actually a PDF
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' not in content_type:
                # Check first few bytes for PDF signature
                first_chunk = next(response.iter_content(chunk_size=1024), b'')
                if not first_chunk.startswith(b'%PDF'):
                    return "", "URL does not point to a valid PDF file"

            # Download the file
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            return target_path, ""

        except requests.RequestException as e:
            return "", f"Failed to download PDF from URL: {str(e)}"
        except Exception as e:
            return "", f"Error saving PDF file: {str(e)}"


class DatabaseHealthService:
    """Service for diagnosing and fixing database health issues."""

    def __init__(self):
        self.issues_found = []
        self.fixes_applied = []

    def run_full_diagnostic(self) -> Dict[str, Any]:
        """Run comprehensive database and system diagnostics."""
        self.issues_found = []
        self.fixes_applied = []

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "database_checks": self._check_database_health(),
            "orphaned_records": self._check_orphaned_records(),
            "orphaned_pdfs": self._check_orphaned_pdfs(),
            "system_checks": self._check_system_health(),
            "terminal_checks": self._check_terminal_setup(),
            "issues_found": self.issues_found,
            "fixes_applied": self.fixes_applied,
            "recommendations": [],
        }

        # Add recommendations based on findings
        report["recommendations"] = self._generate_recommendations(report)

        return report

    def _check_database_health(self) -> Dict[str, Any]:
        """Check database integrity and structure."""
        checks = {
            "database_exists": False,
            "tables_exist": False,
            "table_counts": {},
            "foreign_key_constraints": True,
            "database_size": 0,
        }

        try:
            with get_db_session() as session:
                # Check if database file exists
                from .database import get_db_manager

                db_manager = get_db_manager()
                db_path = db_manager.db_path
                checks["database_exists"] = os.path.exists(db_path)

                if checks["database_exists"]:
                    checks["database_size"] = os.path.getsize(db_path)

                # Check if tables exist and get counts
                try:
                    checks["table_counts"]["papers"] = session.query(Paper).count()
                    checks["table_counts"]["authors"] = session.query(Author).count()
                    checks["table_counts"]["collections"] = session.query(
                        Collection
                    ).count()
                    checks["tables_exist"] = True
                except Exception as e:
                    self.issues_found.append(f"Database tables missing or corrupt: {e}")
                    checks["tables_exist"] = False

                # Check foreign key constraints
                try:
                    from sqlalchemy import text

                    result = session.execute(
                        text("PRAGMA foreign_key_check")
                    ).fetchall()
                    if result:
                        checks["foreign_key_constraints"] = False
                        self.issues_found.append(
                            f"Foreign key constraint violations found: {len(result)} issues"
                        )
                except Exception as e:
                    self.issues_found.append(f"Could not check foreign keys: {e}")

        except Exception as e:
            self.issues_found.append(f"Database connection failed: {e}")

        return checks

    def _check_orphaned_records(self) -> Dict[str, Any]:
        """Check for orphaned records in association tables."""
        orphaned = {"paper_collections": [], "paper_authors": [], "summary": {}}

        try:
            with get_db_session() as session:
                from sqlalchemy import text

                # Check orphaned paper_collections
                orphaned_pc = session.execute(
                    text(
                        """
                    SELECT pc.paper_id, pc.collection_id 
                    FROM paper_collections pc
                    LEFT JOIN papers p ON pc.paper_id = p.id
                    LEFT JOIN collections c ON pc.collection_id = c.id
                    WHERE p.id IS NULL OR c.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_collections"] = [
                    (row[0], row[1]) for row in orphaned_pc
                ]
                orphaned["summary"]["orphaned_paper_collections"] = len(orphaned_pc)

                # Check orphaned paper_authors
                orphaned_pa = session.execute(
                    text(
                        """
                    SELECT pa.paper_id, pa.author_id 
                    FROM paper_authors pa
                    LEFT JOIN papers p ON pa.paper_id = p.id
                    LEFT JOIN authors a ON pa.author_id = a.id
                    WHERE p.id IS NULL OR a.id IS NULL
                """
                    )
                ).fetchall()

                orphaned["paper_authors"] = [(row[0], row[1]) for row in orphaned_pa]
                orphaned["summary"]["orphaned_paper_authors"] = len(orphaned_pa)

                if orphaned_pc:
                    self.issues_found.append(
                        f"Found {len(orphaned_pc)} orphaned paper-collection associations"
                    )
                if orphaned_pa:
                    self.issues_found.append(
                        f"Found {len(orphaned_pa)} orphaned paper-author associations"
                    )

        except Exception as e:
            self.issues_found.append(f"Could not check orphaned records: {e}")

        return orphaned

    def _check_system_health(self) -> Dict[str, Any]:
        """Check system and environment health."""
        checks = {
            "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            "dependencies": {},
            "disk_space": {},
            "permissions": {},
        }

        # Check required dependencies
        required_deps = ["sqlalchemy", "prompt_toolkit", "requests", "rich"]
        for dep in required_deps:
            try:
                __import__(dep)
                checks["dependencies"][dep] = "✓ Available"
            except ImportError:
                checks["dependencies"][dep] = "✗ Missing"
                self.issues_found.append(f"Missing required dependency: {dep}")

        # Check disk space
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            if os.path.exists(papercli_dir):
                statvfs = os.statvfs(papercli_dir)
                free_space = statvfs.f_frsize * statvfs.f_bavail
                checks["disk_space"]["free_bytes"] = free_space
                checks["disk_space"]["free_mb"] = free_space // (1024 * 1024)

                if free_space < 100 * 1024 * 1024:  # Less than 100MB
                    self.issues_found.append(
                        "Low disk space: less than 100MB available"
                    )
        except Exception:
            checks["disk_space"]["error"] = "Could not check disk space"

        # Check directory permissions
        try:
            papercli_dir = os.path.expanduser("~/.papercli")
            checks["permissions"]["papercli_dir_writable"] = os.access(
                papercli_dir, os.W_OK
            )
            if not checks["permissions"]["papercli_dir_writable"]:
                self.issues_found.append("PaperCLI directory is not writable")
        except Exception:
            checks["permissions"]["error"] = "Could not check permissions"

        return checks

    def _check_terminal_setup(self) -> Dict[str, Any]:
        """Check terminal capabilities and setup."""
        checks = {
            "terminal_type": os.environ.get("TERM", "unknown"),
            "colorterm": os.environ.get("COLORTERM", "not_set"),
            "terminal_size": {},
            "unicode_support": False,
            "color_support": False,
        }

        # Check terminal size
        try:
            import shutil

            size = shutil.get_terminal_size()
            checks["terminal_size"]["columns"] = size.columns
            checks["terminal_size"]["lines"] = size.lines

            if size.columns < 80:
                self.issues_found.append(
                    "Terminal width is less than 80 columns (current: {})".format(
                        size.columns
                    )
                )
            if size.lines < 24:
                self.issues_found.append(
                    "Terminal height is less than 24 lines (current: {})".format(
                        size.lines
                    )
                )
        except Exception:
            checks["terminal_size"]["error"] = "Could not determine terminal size"

        # Check Unicode support
        try:
            test_chars = "📄✓✗⚠"
            test_chars.encode("utf-8")
            checks["unicode_support"] = True
        except UnicodeEncodeError:
            checks["unicode_support"] = False
            self.issues_found.append("Terminal may not support Unicode characters")

        # Check color support
        if "color" in checks["terminal_type"].lower() or checks["colorterm"]:
            checks["color_support"] = True
        else:
            checks["color_support"] = False
            self.issues_found.append("Terminal may not support colors")

        return checks

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on diagnostic results."""
        recommendations = []

        # Database recommendations
        if not report["database_checks"]["tables_exist"]:
            recommendations.append("Run database migration to create missing tables")

        if (
            report["orphaned_records"]["summary"].get("orphaned_paper_collections", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned paper-collection associations")

        if report["orphaned_records"]["summary"].get("orphaned_paper_authors", 0) > 0:
            recommendations.append("Clean up orphaned paper-author associations")

        if (
            report.get("orphaned_pdfs", {})
            .get("summary", {})
            .get("orphaned_pdf_files", 0)
            > 0
        ):
            recommendations.append("Clean up orphaned PDF files")

        # System recommendations
        missing_deps = [
            dep
            for dep, status in report["system_checks"]["dependencies"].items()
            if "Missing" in status
        ]
        if missing_deps:
            recommendations.append(
                f"Install missing dependencies: {', '.join(missing_deps)}"
            )

        # Terminal recommendations
        if not report["terminal_checks"]["unicode_support"]:
            recommendations.append("Configure terminal to support UTF-8/Unicode")

        if not report["terminal_checks"]["color_support"]:
            recommendations.append("Enable color support in terminal")

        return recommendations

    def _check_orphaned_pdfs(self) -> Dict[str, Any]:
        """Check for orphaned PDF files in the PDF directory."""
        orphaned = {"files": [], "summary": {}}

        try:
            with get_db_session() as session:
                from .database import get_db_manager

                db_manager = get_db_manager()
                pdf_dir = os.path.join(os.path.dirname(db_manager.db_path), "pdfs")

                if not os.path.exists(pdf_dir):
                    return orphaned

                all_pdfs_in_db = {
                    p.pdf_path
                    for p in session.query(Paper)
                    .filter(Paper.pdf_path.isnot(None))
                    .all()
                }

                disk_pdfs = {
                    os.path.join(pdf_dir, f)
                    for f in os.listdir(pdf_dir)
                    if f.endswith(".pdf")
                }

                orphaned_files = list(disk_pdfs - all_pdfs_in_db)

                orphaned["files"] = orphaned_files
                orphaned["summary"]["orphaned_pdf_files"] = len(orphaned_files)

                if orphaned_files:
                    self.issues_found.append(
                        f"Found {len(orphaned_files)} orphaned PDF files"
                    )
        except Exception as e:
            self.issues_found.append(f"Could not check for orphaned PDFs: {e}")

        return orphaned

    def clean_orphaned_pdfs(self) -> Dict[str, int]:
        """Clean up orphaned PDF files."""
        cleaned = {"pdf_files": 0}

        try:
            report = self._check_orphaned_pdfs()
            orphaned_files = report.get("files", [])

            for f in orphaned_files:
                try:
                    os.remove(f)
                    cleaned["pdf_files"] += 1
                except Exception:
                    pass  # ignore errors on individual file deletions

            if cleaned["pdf_files"] > 0:
                self.fixes_applied.append(
                    f"Cleaned {cleaned['pdf_files']} orphaned PDF files"
                )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned PDFs: {e}")

        return cleaned

    def clean_orphaned_records(self) -> Dict[str, int]:
        """Clean up orphaned records in the database."""
        cleaned = {"paper_collections": 0, "paper_authors": 0}

        try:
            with get_db_session() as session:
                from sqlalchemy import text

                # Clean orphaned paper_collections
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_collections 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR collection_id NOT IN (SELECT id FROM collections)
                """
                    )
                )
                cleaned["paper_collections"] = result.rowcount

                # Clean orphaned paper_authors
                result = session.execute(
                    text(
                        """
                    DELETE FROM paper_authors 
                    WHERE paper_id NOT IN (SELECT id FROM papers) 
                    OR author_id NOT IN (SELECT id FROM authors)
                """
                    )
                )
                cleaned["paper_authors"] = result.rowcount

                session.commit()

                if cleaned["paper_collections"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_collections']} orphaned paper-collection associations"
                    )
                if cleaned["paper_authors"] > 0:
                    self.fixes_applied.append(
                        f"Cleaned {cleaned['paper_authors']} orphaned paper-author associations"
                    )

        except Exception as e:
            raise Exception(f"Failed to clean orphaned records: {e}")

        return cleaned
