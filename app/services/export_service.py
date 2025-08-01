"""Export service - Business logic for exporting papers to various formats."""

import json
import re
import unicodedata
from typing import List

import bibtexparser
from bibtexparser.customization import string_to_latex

from ..db.models import Paper


class ExportService:
    """Service for exporting papers to various formats."""

    def export_to_bibtex(self, papers: List[Paper]) -> str:
        """Export papers to BibTeX format using bibtexparser v1."""
        # Create a new BibTeX database
        bib_database = bibtexparser.bibdatabase.BibDatabase()

        for paper in papers:
            # Create entry dictionary
            entry = {}

            # Generate BibTeX key
            entry["ID"] = self._generate_bibtex_key(paper)

            # Determine if this is a preprint
            is_preprint = self._is_preprint(paper)

            # Set entry type
            entry["ENTRYTYPE"] = (
                "article"
                if is_preprint or paper.paper_type == "journal"
                else "inproceedings"
            )

            # Add title with double braces to preserve case and LaTeX encoding
            entry["title"] = "{" + string_to_latex(paper.title) + "}"

            # Add authors with Unicode to LaTeX conversion
            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                latex_authors = [
                    string_to_latex(author.full_name) for author in ordered_authors
                ]
                entry["author"] = " and ".join(latex_authors)

            # Handle venue/journal based on type
            if is_preprint:
                # For preprints, always use journal = arXiv.org
                entry["journal"] = "arXiv.org"
            elif paper.venue_full:
                if paper.paper_type == "journal":
                    entry["journal"] = string_to_latex(paper.venue_full)
                else:
                    # For conference proceedings, prefer acronym if available
                    venue_name = (
                        paper.venue_acronym if paper.venue_acronym else paper.venue_full
                    )
                    entry["booktitle"] = string_to_latex(venue_name)

            # Add year
            if paper.year:
                entry["year"] = str(paper.year)

            # Add preprint-specific fields
            if is_preprint and paper.preprint_id:
                # Extract arXiv ID (remove "arXiv " prefix if present)
                arxiv_id = paper.preprint_id.replace("arXiv ", "").strip()
                entry["eprint"] = arxiv_id
                entry["eprinttype"] = "arxiv"

                # Add category if available
                if paper.category:
                    entry["eprintclass"] = paper.category

            # Add other fields
            if paper.volume:
                entry["volume"] = str(paper.volume)

            if paper.issue:
                entry["number"] = str(paper.issue)

            if paper.pages:
                # Convert single dash to double dash for BibTeX (LaTeX en-dash)
                pages_bibtex = (
                    paper.pages.replace("-", "--")
                    if "-" in paper.pages
                    else paper.pages
                )
                entry["pages"] = pages_bibtex

            bib_database.entries.append(entry)

        # Use bibtexparser writer with custom formatting
        writer = bibtexparser.bwriter.BibTexWriter()
        writer.indent = "  "  # Use 2 spaces for indentation
        writer.align_values = True  # Align values
        writer.order_entries_by = "ID"  # Order by citation key
        writer.add_trailing_comma = False  # No trailing commas

        return bibtexparser.dumps(bib_database, writer)

    def export_to_ieee(self, papers: List[Paper]) -> str:
        """Export papers to IEEE reference format."""
        references = []

        for i, paper in enumerate(papers, 1):
            # Start with reference number only if more than one paper
            if len(papers) > 1:
                ref = f"[{i}]    "
            else:
                ref = ""

            # Add authors
            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                # Format authors: First initials + Last name
                author_list = []
                for author in ordered_authors:
                    # Split name and format as "F. M. Lastname"
                    parts = author.full_name.strip().split()
                    if len(parts) >= 2:
                        # Last name is the last part
                        last_name = parts[-1]
                        # All other parts become initials
                        initials = ". ".join([part[0] for part in parts[:-1]]) + "."
                        author_list.append(f"{initials} {last_name}")
                    else:
                        author_list.append(author.full_name)

                # Join authors with commas and "and" before last
                if len(author_list) == 1:
                    authors_str = author_list[0]
                elif len(author_list) == 2:
                    authors_str = f"{author_list[0]} and {author_list[1]}"
                else:
                    authors_str = (
                        ", ".join(author_list[:-1]) + f", and {author_list[-1]}"
                    )

                ref += authors_str + ", "

            # Add title in quotes
            ref += f'"{paper.title}," '

            # Determine if preprint
            is_preprint = self._is_preprint(paper)

            if is_preprint:
                # For preprints: "arXiv.org, vol. category. date."
                ref += "arXiv.org"
                if paper.category:
                    ref += f", vol. {paper.category}"
                if paper.year:
                    # For arXiv, try to format as date (simplified to year for now)
                    ref += f". {paper.year}."
                else:
                    ref += "."
            elif paper.paper_type == "journal":
                # For journals: "Journal Name, vol. X, no. Y, pp. Z, Year."
                if paper.venue_full:
                    ref += f"{paper.venue_full}"
                if paper.volume:
                    ref += f", vol. {paper.volume}"
                if paper.issue:
                    ref += f", no. {paper.issue}"
                if paper.pages:
                    # Convert single dash to en-dash for IEEE format
                    pages_ieee = (
                        paper.pages.replace("-", "–")
                        if "-" in paper.pages
                        else paper.pages
                    )
                    ref += f", pp. {pages_ieee}"
                if paper.year:
                    ref += f", {paper.year}"
                ref += "."
            else:
                # For conferences: "in VENUE, Year, pp. pages."
                ref += "in "
                if paper.venue_acronym:
                    ref += paper.venue_acronym
                elif paper.venue_full:
                    ref += paper.venue_full
                else:
                    ref += "Conference"

                if paper.year:
                    ref += f", {paper.year}"
                if paper.pages:
                    # Convert single dash to en-dash for IEEE format
                    pages_ieee = (
                        paper.pages.replace("-", "–")
                        if "-" in paper.pages
                        else paper.pages
                    )
                    ref += f", pp. {pages_ieee}"
                ref += "."

            references.append(ref)

        return "\n".join(references)

    def _generate_bibtex_key(self, paper) -> str:
        """Generate BibTeX citation key in format: lastname+year+firstword."""
        # Get first author's last name
        ordered_authors = paper.get_ordered_authors()
        if ordered_authors:
            first_author_name = ordered_authors[0].full_name
            # Handle Unicode names and extract last name
            last_name = self._extract_last_name(first_author_name)
        else:
            last_name = "unknown"

        # Get year
        year = str(paper.year) if paper.year else "unknown"

        # Get first significant word from title
        first_word = self._extract_first_significant_word(paper.title)

        # Combine and normalize
        key = f"{last_name}{year}{first_word}".lower()

        # Remove non-alphanumeric characters except hyphens and underscores
        key = re.sub(r"[^a-z0-9_-]", "", key)

        return key

    def _extract_last_name(self, full_name: str) -> str:
        """Extract last name from full name, handling Unicode characters."""
        # Normalize Unicode characters
        normalized = unicodedata.normalize("NFD", full_name)

        # Remove accents/diacritics
        ascii_name = "".join(c for c in normalized if unicodedata.category(c) != "Mn")

        # Split and get last part
        parts = ascii_name.strip().split()
        if parts:
            return parts[-1]
        return "unknown"

    def _extract_first_significant_word(self, title: str) -> str:
        """Extract first significant word from title."""
        # Skip common articles and prepositions
        skip_words = {
            "a",
            "an",
            "the",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "is",
            "are",
            "was",
            "were",
        }

        words = title.lower().split()
        for word in words:
            # Clean the word
            clean_word = re.sub(r"[^a-z0-9]", "", word)
            if clean_word and clean_word not in skip_words and len(clean_word) > 2:
                return clean_word

        # If no significant word found, use first word
        if words:
            return re.sub(r"[^a-z0-9]", "", words[0].lower())

        return "untitled"

    def _is_preprint(self, paper) -> bool:
        """Determine if paper is a preprint."""
        # Check paper type
        if paper.paper_type and paper.paper_type.lower() in ["preprint", "arxiv"]:
            return True

        # Check if it has arXiv ID
        if paper.preprint_id and (
            "arxiv" in paper.preprint_id.lower()
            or re.match(r"^\d{4}\.\d{4,5}", paper.preprint_id)
        ):
            return True

        # Check venue
        if paper.venue_full and "arxiv" in paper.venue_full.lower():
            return True

        return False

    def export_to_markdown(self, papers: List[Paper]) -> str:
        """Export papers to Markdown format."""
        content = "# Paper List\n\n"

        for paper in papers:
            content += f"## {paper.title}\n\n"

            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                authors = ", ".join([author.full_name for author in ordered_authors])
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
        html = """<!DOCTYPE html>\n<html>\n<head>\n    <title>Paper List</title>\n    <style>\n        body { font-family: Arial, sans-serif; margin: 20px; }\n        .paper { margin-bottom: 30px; padding: 20px; border: 1px solid #ddd; }\n        .title { font-size: 18px; font-weight: bold; margin-bottom: 10px; }\n        .authors { font-style: italic; margin-bottom: 5px; }\n        .venue { color: #666; margin-bottom: 5px; }\n        .abstract { margin-top: 10px; }\n        .notes { margin-top: 10px; font-style: italic; }\n    </style>\n</head>\n<body>\n    <h1>Paper List</h1>\n"""

        for paper in papers:
            html += f'    <div class="paper">\n'
            html += f'        <div class="title">{paper.title}</div>\n'

            ordered_authors = paper.get_ordered_authors()
            if ordered_authors:
                authors = ", ".join([author.full_name for author in ordered_authors])
                html += f'        <div class="authors">{authors}</div>\n'

            if paper.venue_display and paper.year:
                html += f'        <div class="venue">{paper.venue_display}, {paper.year}</div>\n'

            if paper.abstract:
                html += f'        <div class="abstract"><strong>Abstract:</strong> {paper.abstract}</div>\n'

            if paper.notes:
                html += f'        <div class="notes"><strong>Notes:</strong> {paper.notes}</div>\n'

            html += "    </div>\n"

        html += """</body>\n</html>"""

        return html

    def export_to_json(self, papers: List[Paper]) -> str:
        """Export papers to JSON format."""
        paper_list = []

        for paper in papers:
            ordered_authors = paper.get_ordered_authors()
            paper_dict = {
                "title": paper.title,
                "authors": [author.full_name for author in ordered_authors],
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
