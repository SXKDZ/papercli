from typing import Any, Dict, List

from fuzzywuzzy import fuzz
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from ng.db.database import get_db_session
from ng.db.models import Author, Collection, Paper, PaperAuthor


class SearchService:
    """Service for searching and filtering papers."""

    def __init__(self, app=None):
        self.app = app

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
                    .join(Paper.paper_authors)
                    .join(PaperAuthor.author)
                    .filter(Author.full_name.ilike(f"%{query}%"))
                    .all()
                )
                # Add author search results
                paper_ids = [p.id for p in papers_by_author]
                if paper_ids:
                    conditions.append(Paper.id.in_(paper_ids))

            if conditions:
                papers = (
                    session.query(Paper)
                    .options(
                        joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                        joinedload(Paper.collections),
                    )
                    .filter(or_(*conditions))
                    .order_by(Paper.added_date.desc())
                    .all()
                )

                # Force load relationships
                for paper in papers:
                    _ = paper.paper_authors
                    _ = paper.collections

                # Expunge to make detached but accessible
                session.expunge_all()
                if self.app:
                    self.app._add_log(
                        "search_query",
                        f"Search '{query}' in fields {fields} → {len(papers)} result(s)",
                    )
                return papers
            return []

    def fuzzy_search_papers(self, query: str, threshold: int = 60) -> List[Paper]:
        """Fuzzy search papers using edit distance."""
        with get_db_session() as session:
            # Eagerly load all papers with relationships
            all_papers = (
                session.query(Paper)
                .options(
                    joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                    joinedload(Paper.collections),
                )
                .all()
            )

            scored_papers = []

            for paper in all_papers:
                # Force load relationships while in session
                _ = paper.paper_authors
                _ = paper.collections

                # Calculate fuzzy match scores
                title_score = fuzz.partial_ratio(query.lower(), paper.title.lower())
                ordered_authors = paper.get_ordered_authors()
                author_score = max(
                    [
                        fuzz.partial_ratio(query.lower(), author.full_name.lower())
                        for author in ordered_authors
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
            results = [paper for paper, score in scored_papers]
            if self.app:
                self.app._add_log(
                    "search_fuzzy",
                    f"Fuzzy search '{query}' (threshold={threshold}) → {len(results)} result(s)",
                )
            return results

    def filter_papers(self, filters: Dict[str, Any]) -> List[Paper]:
        """Filter papers by various criteria."""
        with get_db_session() as session:
            query = session.query(Paper).options(
                joinedload(Paper.paper_authors).joinedload(PaperAuthor.author),
                joinedload(Paper.collections),
            )

            if "all" in filters:
                search_term = filters["all"]
                query = query.filter(
                    or_(
                        Paper.title.ilike(f"%{search_term}%"),
                        Paper.abstract.ilike(f"%{search_term}%"),
                        Paper.venue_full.ilike(f"%{search_term}%"),
                        Paper.venue_acronym.ilike(f"%{search_term}%"),
                        Paper.paper_authors.any(
                            Author.full_name.ilike(f"%{search_term}%")
                        ),
                    )
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
                query = (
                    query.join(Paper.paper_authors)
                    .join(PaperAuthor.author)
                    .filter(Author.full_name.ilike(f'%{filters["author"]}%'))
                )

            papers = query.order_by(Paper.added_date.desc()).all()

            # Force load relationships while in session
            for paper in papers:
                _ = paper.paper_authors
                _ = paper.collections

            # Expunge to make detached but accessible
            session.expunge_all()
            if self.app:
                self.app._add_log(
                    "search_filter",
                    f"Applied filters {filters} → {len(papers)} result(s)",
                )
            return papers
