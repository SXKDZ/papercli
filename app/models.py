"""
Database models for PaperCLI using SQLAlchemy ORM.
"""

from datetime import datetime
from typing import List, Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column


Base = declarative_base()


# Association table for many-to-many relationship between papers and authors
paper_authors = Table(
    'paper_authors',
    Base.metadata,
    Column('paper_id', Integer, ForeignKey('papers.id'), primary_key=True),
    Column('author_id', Integer, ForeignKey('authors.id'), primary_key=True)
)

# Association table for many-to-many relationship between papers and collections
paper_collections = Table(
    'paper_collections',
    Base.metadata,
    Column('paper_id', Integer, ForeignKey('papers.id'), primary_key=True),
    Column('collection_id', Integer, ForeignKey('collections.id'), primary_key=True)
)


class Author(Base):
    """Author model."""
    __tablename__ = 'authors'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    affiliation: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Relationships
    papers: Mapped[List["Paper"]] = relationship(
        "Paper", secondary=paper_authors, back_populates="authors"
    )
    
    def __repr__(self):
        return f"<Author(full_name='{self.full_name}')>"


class Collection(Base):
    """Collection model for organizing papers."""
    __tablename__ = 'collections'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    papers: Mapped[List["Paper"]] = relationship(
        "Paper", secondary=paper_collections, back_populates="collections"
    )
    
    def __repr__(self):
        return f"<Collection(name='{self.name}')>"


class Paper(Base):
    """Paper model."""
    __tablename__ = 'papers'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    
    # Venue information
    venue_full: Mapped[Optional[str]] = mapped_column(String(255))
    venue_acronym: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Publication details
    year: Mapped[Optional[int]] = mapped_column(Integer)
    volume: Mapped[Optional[str]] = mapped_column(String(20))
    issue: Mapped[Optional[str]] = mapped_column(String(20))
    pages: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Paper type (preprint, website, journal, conference, etc.)
    paper_type: Mapped[Optional[str]] = mapped_column(String(50))
    
    # External identifiers
    doi: Mapped[Optional[str]] = mapped_column(String(255))
    arxiv_id: Mapped[Optional[str]] = mapped_column(String(50))
    dblp_url: Mapped[Optional[str]] = mapped_column(String(500))
    google_scholar_url: Mapped[Optional[str]] = mapped_column(String(500))
    
    # File information
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    
    # User notes
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    # Metadata
    added_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    modified_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    authors: Mapped[List[Author]] = relationship(
        "Author", secondary=paper_authors, back_populates="papers"
    )
    collections: Mapped[List[Collection]] = relationship(
        "Collection", secondary=paper_collections, back_populates="papers"
    )
    
    def __repr__(self):
        return f"<Paper(title='{self.title[:50]}...', year={self.year})>"
    
    @property
    def author_names(self) -> str:
        """Return formatted author names."""
        return ", ".join([author.full_name for author in self.authors])
    
    @property
    def venue_display(self) -> str:
        """Return formatted venue display."""
        if self.venue_acronym and self.venue_full:
            return f"{self.venue_acronym} ({self.venue_full})"
        return self.venue_full or self.venue_acronym or "Unknown"
    
    @property
    def collection_names(self) -> str:
        """Return formatted collection names."""
        return ", ".join([collection.name for collection in self.collections])