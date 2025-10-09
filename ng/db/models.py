"""
Database models for PaperCLI using SQLAlchemy ORM.
"""

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


# Association object for many-to-many relationship between papers and authors with ordering
class PaperAuthor(Base):
    """Association object for paper-author relationship with ordering."""

    __tablename__ = "paper_authors"

    paper_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )  # Author order position

    # Relationships to actual objects
    paper: Mapped["Paper"] = relationship("Paper", back_populates="paper_authors")
    author: Mapped["Author"] = relationship("Author", back_populates="paper_authors")


# Association table for many-to-many relationship between papers and collections
paper_collections = Table(
    "paper_collections",
    Base.metadata,
    Column("paper_id", Integer, ForeignKey("papers.id"), primary_key=True),
    Column("collection_id", Integer, ForeignKey("collections.id"), primary_key=True),
)


class Author(Base):
    """Author model."""

    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    affiliation: Mapped[Optional[str]] = mapped_column(String(255))

    # Relationships
    paper_authors: Mapped[List["PaperAuthor"]] = relationship(
        "PaperAuthor", back_populates="author"
    )
    papers: Mapped[List["Paper"]] = relationship(
        "Paper", secondary="paper_authors", back_populates="authors", viewonly=True
    )

    def __repr__(self):
        return f"<Author(full_name='{self.full_name}')>"


class Collection(Base):
    """Collection model for organizing papers."""

    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_modified: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # Relationships
    papers: Mapped[List["Paper"]] = relationship(
        "Paper", secondary=paper_collections, back_populates="collections"
    )

    def __repr__(self):
        return f"<Collection(name='{self.name}')>"


class Paper(Base):
    """Paper model."""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
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
    preprint_id: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # e.g., "arXiv 2505.15134"
    category: Mapped[Optional[str]] = mapped_column(String(50))  # e.g., "cs.LG"
    url: Mapped[Optional[str]] = mapped_column(String(500))  # General URL field

    # File information
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    html_snapshot_path: Mapped[Optional[str]] = mapped_column(String(500))

    # User notes
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Metadata
    added_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    modified_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    # Relationships
    paper_authors: Mapped[List[PaperAuthor]] = relationship(
        "PaperAuthor",
        back_populates="paper",
        order_by="PaperAuthor.position",
        cascade="all, delete-orphan",
    )
    authors: Mapped[List[Author]] = relationship(
        "Author", secondary="paper_authors", back_populates="papers", viewonly=True
    )
    collections: Mapped[List[Collection]] = relationship(
        "Collection", secondary=paper_collections, back_populates="papers"
    )

    def __repr__(self):
        return f"<Paper(title='{self.title[:50]}...', year={self.year})>"

    @property
    def author_names(self) -> str:
        """Return formatted author names in correct order."""
        # Get authors in order using the paper_authors relationship
        ordered_authors = [
            pa.author for pa in sorted(self.paper_authors, key=lambda x: x.position)
        ]
        return ", ".join([author.full_name for author in ordered_authors])

    def get_ordered_authors(self) -> List["Author"]:
        """Get authors in their correct order."""
        return [
            pa.author for pa in sorted(self.paper_authors, key=lambda x: x.position)
        ]

    @property
    def venue_display(self) -> str:
        """Return formatted venue display."""
        if self.venue_acronym and self.venue_full:
            return f"{self.venue_full} ({self.venue_acronym})"
        return self.venue_full or self.venue_acronym or "Unknown"
