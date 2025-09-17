from __future__ import annotations

import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, Dict, List

import bibtexparser
import PyPDF2
import requests
import rispy
from openai import OpenAI
from titlecase import titlecase

from ng.services import http_utils, llm_utils, prompts
from ng.services.utils import fix_broken_lines, normalize_paper_data

if TYPE_CHECKING:
    from ng.services.pdf import PDFManager


def _truncate_for_logging(content: str, max_chars: int = 300) -> tuple[str, str]:
    """
    Truncate content for logging with consistent format.

    Returns:
        tuple: (truncated_content, length_info)
    """
    if len(content) > max_chars:
        return content[:max_chars] + "...", f"({len(content)} chars)"
    return content, f"({len(content)} chars)"


class MetadataExtractor:
    """Service for extracting metadata from various sources."""

    def __init__(self, pdf_manager: PDFManager, app):
        self.app = app
        self.pdf_manager = pdf_manager

    def extract_from_arxiv(self, arxiv_id: str) -> Dict[str, Any]:
        """Extract metadata from arXiv."""
        arxiv_id = re.sub(r"arxiv[:\s]*", "", arxiv_id, flags=re.IGNORECASE)
        arxiv_id = re.sub(
            r"[^\d\.v]", "", arxiv_id
        )  # Allow digits, dots, and 'v' for versions

        try:
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            response = http_utils.get(url, timeout=30)

            root = ET.fromstring(response.content)

            ns = {"atom": "http://www.w3.org/2005/Atom"}

            entry = root.find(".//atom:entry", ns)
            if entry is None:
                raise Exception("Paper not found on arXiv")

            title_elem = entry.find("atom:title", ns)
            title = (
                title_elem.text.strip() if title_elem is not None else "Unknown Title"
            )
            title = fix_broken_lines(title)
            title = titlecase(title)

            summary_elem = entry.find("atom:summary", ns)
            abstract = summary_elem.text.strip() if summary_elem is not None else ""
            abstract = fix_broken_lines(abstract)

            authors = []
            for author in entry.findall("atom:author", ns):
                name_elem = author.find("atom:name", ns)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())

            published_elem = entry.find("atom:published", ns)
            year = None
            if published_elem is not None:
                published_date = published_elem.text
                year_match = re.search(r"(\d{4})", published_date)
                if year_match:
                    year = int(year_match.group(1))

            category = None
            category_elem = entry.find("atom:category", ns)
            if category_elem is not None:
                category = category_elem.get("term")

            doi = None
            doi_elem = entry.find("atom:id", ns)
            if doi_elem is not None:
                doi_match = re.search(r"doi:(.+)", doi_elem.text)
                if doi_match:
                    doi = doi_match.group(1)

            return {
                "title": title,
                "abstract": abstract,
                "authors": (
                    " and ".join(authors) if authors else ""
                ),  # Convert to string format for consistency
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

    def extract_from_dblp(self, dblp_url: str) -> Dict[str, Any]:
        """Extract metadata from DBLP URL using BibTeX endpoint with LLM venue enhancement."""
        try:
            # Convert DBLP HTML URL to BibTeX URL
            bib_url = self._convert_dblp_url_to_bib(dblp_url)

            response = http_utils.get(bib_url, timeout=30)

            bibtex_content = response.text.strip()
            if not bibtex_content:
                raise Exception("Empty BibTeX response")

            # Write to temporary file and use existing BibTeX extraction
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".bib", delete=False, encoding="utf-8"
            ) as tmp_file:
                tmp_file.write(bibtex_content)
                tmp_file_path = tmp_file.name

            try:
                # Use existing BibTeX extraction logic
                papers_metadata = self.extract_from_bibtex(tmp_file_path)
                if not papers_metadata:
                    raise Exception("No metadata extracted from BibTeX")

                # Take the first entry
                metadata = papers_metadata[0]

                # Enhance with LLM venue extraction if venue field exists
                venue_field = metadata.get("venue_full", "")
                if venue_field:
                    venue_info = self._extract_venue_with_llm(venue_field)
                    metadata["venue_full"] = venue_info.get("venue_full", venue_field)
                    metadata["venue_acronym"] = venue_info.get("venue_acronym", "")

                # Ensure we have the DBLP URL
                if not metadata.get("url"):
                    metadata["url"] = dblp_url

                return metadata

            finally:
                try:
                    os.unlink(tmp_file_path)
                except OSError:
                    pass

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch DBLP metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process DBLP metadata: {e}")

    def _convert_dblp_url_to_bib(self, dblp_url: str) -> str:
        """Convert DBLP HTML URL to BibTeX URL."""
        # Handle both .html and regular DBLP URLs
        if ".html" in dblp_url:
            # Remove .html and any query parameters, then add .bib
            base_url = dblp_url.split(".html")[0]
            bib_url = f"{base_url}.bib?param=1"
        else:
            # Direct DBLP record URL
            bib_url = f"{dblp_url}.bib?param=1"

        return bib_url

    def _extract_venue_with_llm(self, venue_field: str) -> Dict[str, str]:
        """Extract venue name and acronym using LLM."""
        if not venue_field:
            return {"venue_full": "", "venue_acronym": ""}

        # Initialize chat service if not available
        client = OpenAI()
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        try:
            prompt = prompts.venue_extraction_prompt(venue_field)

            # Log the LLM request
            self.app._add_log(
                "llm_venue_request",
                f"Requesting venue extraction for: {venue_field}",
            )
            truncated_prompt, length_info = _truncate_for_logging(prompt, 300)
            self.app._add_log(
                "llm_venue_prompt",
                f"Prompt sent to {model_name} {length_info}:\n{truncated_prompt}",
            )

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.venue_extraction_system_message(),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=200,
                temperature=0.1,
            )

            response_text = response.choices[0].message.content.strip()

            # Log the LLM response
            self.app._add_log(
                "llm_venue_response",
                f"{model_name} response received ({len(response_text)} chars)",
            )
            truncated_content, length_info = _truncate_for_logging(response_text, 300)
            self.app._add_log(
                "llm_venue_content",
                f"Raw response {length_info}:\n{truncated_content}",
            )

            # Clean up markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            response_text = response_text.strip()

            # Try to parse JSON response
            try:
                venue_info = json.loads(response_text)
                return {
                    "venue_full": venue_info.get("venue_full", venue_field),
                    "venue_acronym": venue_info.get("venue_acronym", ""),
                }
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                return {
                    "venue_full": venue_field,
                    "venue_acronym": self._extract_acronym_fallback(venue_field),
                }

        except Exception as e:
            # Fallback on any error
            return {
                "venue_full": venue_field,
                "venue_acronym": self._extract_acronym_fallback(venue_field),
            }

    def _extract_acronym_fallback(self, venue_field: str) -> str:
        """Fallback method to extract acronym without LLM."""
        if not venue_field:
            return ""

        # Common conference acronyms
        acronym_map = {
            "international conference on machine learning": "ICML",
            "neural information processing systems": "NeurIPS",
            "international conference on learning representations": "ICLR",
            "ieee conference on computer vision and pattern recognition": "CVPR",
            "international conference on computer vision": "ICCV",
            "european conference on computer vision": "ECCV",
            "conference on empirical methods in natural language processing": "EMNLP",
            "annual meeting of the association for computational linguistics": "ACL",
            "international joint conference on artificial intelligence": "IJCAI",
            "aaai conference on artificial intelligence": "AAAI",
        }

        venue_lower = venue_field.lower()
        for full_name, acronym in acronym_map.items():
            if full_name in venue_lower:
                return acronym

        # Extract first letters of significant words
        words = re.findall(r"\b[A-Z][a-z]*", venue_field)
        if words:
            return "".join(word[0].upper() for word in words[:4])

        return ""

    def extract_from_openreview(self, openreview_id: str) -> Dict[str, Any]:
        """Extract metadata from OpenReview paper ID."""
        try:
            # Clean OpenReview ID - extract just the ID part
            if openreview_id.startswith("https://openreview.net/forum?id="):
                openreview_id = openreview_id.split("id=")[1]
            elif openreview_id.startswith("https://openreview.net/pdf?id="):
                openreview_id = openreview_id.split("id=")[1]

            # Remove any additional parameters
            openreview_id = openreview_id.split("&")[0].split("#")[0]

            # Try newer API v2 format first
            api_url_v2 = f"https://api2.openreview.net/notes?forum={openreview_id}&limit=1000&details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags"

            try:
                response = http_utils.get(api_url_v2, timeout=30)
                data = response.json()

                if data.get("notes") and len(data["notes"]) > 0:
                    return self._parse_openreview_v2_response(data, openreview_id)
            except (requests.RequestException, KeyError):
                pass  # Fall back to older API format

            # Try older API format if v2 fails
            api_url_v1 = f"https://api.openreview.net/notes?forum={openreview_id}&trash=true&details=replyCount%2Cwritable%2Crevisions%2Coriginal%2Coverwriting%2Cinvitation%2Ctags&limit=1000&offset=0"

            response = http_utils.get(api_url_v1, timeout=30)
            data = response.json()

            if not data.get("notes") or len(data["notes"]) == 0:
                raise Exception("Paper not found on OpenReview")

            return self._parse_openreview_v1_response(data, openreview_id)

        except requests.RequestException as e:
            raise Exception(f"Failed to fetch OpenReview metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to process OpenReview metadata: {e}")

    def _parse_openreview_v2_response(
        self,
        data: Dict[str, Any],
        openreview_id: str,
    ) -> Dict[str, Any]:
        """Parse OpenReview API v2 response."""
        note = None
        for n in data["notes"]:
            if n.get("id") == n.get("forum"):
                note = n
                break

        if not note:
            # Fallback to first note if main submission not found
            note = data["notes"][0]

        content = note.get("content", {})

        title = content.get("title", {}).get("value", "Unknown Title")
        title = fix_broken_lines(title)
        title = titlecase(title)

        abstract = content.get("abstract", {}).get("value", "")
        if abstract:
            abstract = fix_broken_lines(abstract)

        authors = []
        authors_data = content.get("authors", {}).get("value", [])

        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]
        else:
            # Fallback: try to extract authors from _bibtex field
            bibtex_content = content.get("_bibtex", {}).get("value", "")
            if bibtex_content:
                authors = self._extract_authors_from_bibtex(bibtex_content)

        venue_info = content.get("venue", {}).get("value", "")
        venue_data = self._extract_venue_with_llm(venue_info)

        # Extract year from venue or other sources
        year = None
        if venue_info:
            year_match = re.search(r"(\d{4})", venue_info)
            if year_match:
                year = int(year_match.group(1))

        return {
            "title": title,
            "abstract": abstract,
            "authors": (
                " and ".join(authors) if authors else ""
            ),  # Convert to string format for consistency
            "year": year,
            "venue_full": venue_data.get("venue_full", venue_info),
            "venue_acronym": venue_data.get("venue_acronym", ""),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }

    def _extract_authors_from_bibtex(self, bibtex_content: str) -> List[str]:
        """Extract authors from BibTeX content."""
        try:
            # Look for author field in bibtex
            author_match = re.search(
                r"author\s*=\s*\{([^}]+)\}", bibtex_content, re.IGNORECASE
            )
            if not author_match:
                return []

            author_string = author_match.group(1).strip()

            # Skip if it's just "Anonymous" (common in workshop submissions)
            if author_string.lower() in ["anonymous", "anon"]:
                return []

            # Split by " and " (standard BibTeX format)
            if " and " in author_string:
                authors = [author.strip() for author in author_string.split(" and ")]
            else:
                # Single author
                authors = [author_string]

            # Filter out empty authors
            authors = [author for author in authors if author.strip()]

            return authors

        except Exception:
            # Silently fail if bibtex parsing fails
            return []

    def _parse_openreview_v1_response(
        self,
        data: Dict[str, Any],
        openreview_id: str,
    ) -> Dict[str, Any]:
        """Parse OpenReview API v1 response."""
        note = None
        for n in data["notes"]:
            if n.get("id") == n.get("forum"):
                note = n
                break

        if not note:
            # Fallback to first note if main submission not found
            note = data["notes"][0]

        content = note.get("content", {})

        title = content.get("title", "Unknown Title")
        if isinstance(title, dict):
            title = title.get("value", "Unknown Title")
        title = fix_broken_lines(title)
        title = titlecase(title)

        # Extract abstract
        abstract = content.get("abstract", "")
        if isinstance(abstract, dict):
            abstract = abstract.get("value", "")
        if abstract:
            abstract = fix_broken_lines(abstract)

        authors = []
        authors_data = content.get("authors", [])

        if isinstance(authors_data, dict):
            authors_data = authors_data.get("value", [])

        if authors_data:
            authors = [author.strip() for author in authors_data if author.strip()]
        else:
            # Fallback: try to extract authors from _bibtex field
            bibtex_content = content.get("_bibtex", "")
            if isinstance(bibtex_content, dict):
                bibtex_content = bibtex_content.get("value", "")

            if bibtex_content:
                authors = self._extract_authors_from_bibtex(bibtex_content)

        venue_info = content.get("venue", "")
        if isinstance(venue_info, dict):
            venue_info = venue_info.get("value", "")
        venue_data = self._extract_venue_with_llm(venue_info)

        year = None
        if venue_info:
            year_match = re.search(r"(\d{4})", venue_info)
            if year_match:
                year = int(year_match.group(1))

        return {
            "title": title,
            "abstract": abstract,
            "authors": (
                " and ".join(authors) if authors else ""
            ),  # Convert to string format for consistency
            "year": year,
            "venue_full": venue_data.get("venue_full", venue_info),
            "venue_acronym": venue_data.get("venue_acronym", ""),
            "paper_type": "conference",
            "url": f"https://openreview.net/forum?id={openreview_id}",
            "category": None,
            "pdf_path": None,
        }

    def extract_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Extract metadata from PDF file using LLM analysis of first two pages."""
        if not self.pdf_manager:
            raise RuntimeError("PDFManager not set for MetadataExtractor.")

        try:
            pdf_path = self.pdf_manager.get_absolute_path(pdf_path)

            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if len(pdf_reader.pages) == 0:
                    raise Exception("PDF file is empty")

                # Extract text from first 1-2 pages
                pages_to_extract = min(2, len(pdf_reader.pages))
                text_content = ""

                for i in range(pages_to_extract):
                    page = pdf_reader.pages[i]
                    text_content += page.extract_text() + "\n\n"

                if not text_content.strip():
                    raise Exception("Could not extract text from PDF")

            client = OpenAI()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

            prompt = prompts.metadata_extraction_prompt(text_content)

            # Log the LLM request
            self.app._add_log(
                "llm_metadata_request",
                f"Requesting metadata extraction for PDF: {pdf_path}",
            )
            truncated_prompt, length_info = _truncate_for_logging(prompt, 300)
            self.app._add_log(
                "llm_metadata_prompt",
                f"Prompt sent to {model_name} {length_info}:\n{truncated_prompt}",
            )

            # Build parameters using centralized utility (force temperature=0 for extraction)
            params = llm_utils.get_model_parameters(model_name, temperature=0)
            params["messages"] = [
                {
                    "role": "system",
                    "content": prompts.metadata_system_message(),
                },
                {"role": "user", "content": prompt},
            ]

            response = client.chat.completions.create(**params)

            response_content = response.choices[0].message.content.strip()

            # Log the LLM response
            self.app._add_log(
                "llm_metadata_response",
                f"{model_name} response received ({len(response_content)} chars)",
            )
            truncated_content, length_info = _truncate_for_logging(
                response_content, 300
            )
            self.app._add_log(
                "llm_metadata_content",
                f"Raw response {length_info}:\n{truncated_content}",
            )

            if response_content.startswith("```json"):
                response_content = response_content[7:]
            if response_content.startswith("```"):
                response_content = response_content[3:]
            if response_content.endswith("```"):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            if not response_content:
                raise Exception("Empty response from LLM")

            try:
                metadata = json.loads(response_content)
            except json.JSONDecodeError as e:
                # Fallback: create basic metadata from extracted text
                self.app._add_log(
                    "pdf_extraction_warning",
                    f"LLM JSON parsing failed: {e}. Response: {response_content[:500]}...",
                )

                # Extract basic info from text using regex as fallback
                title_match = re.search(
                    r"^(.+?)(?:\n|$)", text_content.strip(), re.MULTILINE
                )
                title = title_match.group(1).strip() if title_match else "Unknown Title"

                # Basic year extraction
                year_match = re.search(r"\b(19|20)\d{2}\b", text_content)
                year = int(year_match.group()) if year_match else None

                metadata = {
                    "title": title,
                    "authors": [],
                    "abstract": "",
                    "year": year,
                    "venue_full": "",
                    "venue_acronym": "",
                    "paper_type": "conference",
                    "doi": "",
                    "url": "",
                    "category": "",
                }

            if not metadata.get("authors"):
                metadata["authors"] = ""

            metadata = normalize_paper_data(metadata)

            return metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from PDF: {e}")

    def generate_paper_summary(self, pdf_path: str) -> str:
        """Generate an academic summary of the paper using LLM analysis of the full text."""
        if not self.pdf_manager:
            raise RuntimeError("PDFManager not set for MetadataExtractor.")

        try:
            pdf_path = self.pdf_manager.get_absolute_path(pdf_path)

            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if len(pdf_reader.pages) == 0:
                    return ""

                # Extract text from first N pages to stay within token limits (configurable)
                max_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
                pages_to_extract = min(max_pages, len(pdf_reader.pages))
                full_text = ""

                for i in range(pages_to_extract):
                    page = pdf_reader.pages[i]
                    full_text += page.extract_text() + "\n\n"

                if not full_text.strip():
                    return ""

            client = OpenAI()
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

            prompt = prompts.summary_academic_summary(full_text)

            # Log the LLM request
            self.app._add_log(
                "llm_summarization_request",
                f"Requesting paper summary for PDF: {pdf_path}",
            )
            truncated_prompt, length_info = _truncate_for_logging(prompt, 300)
            self.app._add_log(
                "llm_summarization_prompt",
                f"Prompt sent to {model_name} {length_info}: {truncated_prompt}",
            )

            # Build parameters using centralized utility
            params = llm_utils.get_model_parameters(model_name)
            params["messages"] = [
                {
                    "role": "system",
                    "content": prompts.summary_system_message(),
                },
                {"role": "user", "content": prompt},
            ]

            response = client.chat.completions.create(**params)

            summary_response = response.choices[0].message.content.strip()

            # Log the LLM response
            self.app._add_log(
                "llm_summarization_response",
                f"{model_name} response received ({len(summary_response)} chars)",
            )
            truncated_content, length_info = _truncate_for_logging(
                summary_response, 300
            )
            self.app._add_log(
                "llm_summarization_content",
                f"Generated summary {length_info}: {truncated_content}",
            )

            return summary_response

        except Exception as e:
            self.app._add_log(
                "paper_summary_error", f"Failed to generate paper summary: {e}"
            )
            return ""  # Return empty string if summarization fails, don't break the workflow

    def extract_from_bibtex(self, bib_path: str) -> List[Dict[str, Any]]:
        """Extract metadata from BibTeX file."""
        try:
            with open(bib_path, "r", encoding="utf-8") as file:
                bib_database = bibtexparser.load(file)

            papers_metadata = []

            for entry in bib_database.entries:
                metadata = {
                    "title": entry.get("title", "").replace("{ ", "").replace("}", ""),
                    "abstract": entry.get("abstract", ""),
                    "year": (
                        int(entry.get("year"))
                        if entry.get("year", "").isdigit()
                        else None
                    ),
                    "venue_full": entry.get("booktitle") or entry.get("journal", ""),
                    "venue_acronym": "",
                    "paper_type": self._infer_paper_type_from_bibtex(entry),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "category": "",
                    "pdf_path": None,
                    "preprint_id": entry.get("eprint", ""),
                    "volume": entry.get("volume", ""),
                    "issue": entry.get("number", ""),
                    "pages": entry.get("pages", ""),
                }

                metadata["authors"] = entry.get("author", "")

                papers_metadata.append(metadata)

            return papers_metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from BibTeX file: {e}")

    def extract_from_ris(self, ris_path: str) -> List[Dict[str, Any]]:
        """Extract metadata from RIS file."""
        try:
            with open(ris_path, "r", encoding="utf-8") as file:
                entries = rispy.load(file)

            papers_metadata = []

            for entry in entries:
                metadata = {
                    "title": entry.get("title", "") or entry.get("primary_title", ""),
                    "abstract": entry.get("abstract", ""),
                    "year": int(entry.get("year")) if entry.get("year") else None,
                    "venue_full": entry.get("journal_name", "")
                    or entry.get("secondary_title", ""),
                    "venue_acronym": entry.get("alternate_title1", ""),
                    "paper_type": self._infer_paper_type_from_ris(entry),
                    "doi": entry.get("doi", ""),
                    "url": entry.get("url", ""),
                    "category": "",
                    "pdf_path": None,
                    "preprint_id": "",
                    "volume": entry.get("volume", ""),
                    "issue": entry.get("number", ""),
                    "pages": entry.get("start_page", "")
                    + (
                        "-" + entry.get("end_page", "") if entry.get("end_page") else ""
                    ),
                }

                authors = entry.get("authors", []) or entry.get("first_authors", [])
                if authors:
                    author_names = [
                        (
                            f"{author.get('given', '')} {author.get('family', '')}".strip()
                            if isinstance(author, dict)
                            else str(author)
                        )
                        for author in authors
                    ]
                    # Convert to string format that normalize_author_names expects
                    metadata["authors"] = " and ".join(author_names)
                else:
                    metadata["authors"] = ""

                papers_metadata.append(metadata)

            return papers_metadata

        except Exception as e:
            raise Exception(f"Failed to extract metadata from RIS file: {e}")

    def _infer_paper_type_from_bibtex(self, entry: Dict[str, str]) -> str:
        """Infer paper type from BibTeX entry type."""
        entry_type = entry.get("ENTRYTYPE", "").lower()

        if entry_type in ["article"]:
            return "journal"
        elif entry_type in ["inproceedings", "conference"]:
            return "conference"
        elif entry_type in ["inbook", "incollection"]:
            return "workshop"
        elif entry_type in ["misc", "unpublished"]:
            return "preprint"
        else:
            return "other"

    def _infer_paper_type_from_ris(self, entry: Dict[str, Any]) -> str:
        """Infer paper type from RIS entry type."""
        type_of_reference = entry.get("type_of_reference", "").upper()

        if type_of_reference in ["JOUR"]:
            return "journal"
        elif type_of_reference in ["CONF", "CPAPER"]:
            return "conference"
        elif type_of_reference in ["CHAP", "BOOK"]:
            return "workshop"
        elif type_of_reference in ["UNPB", "MANSCPT"]:
            return "preprint"
        else:
            return "other"

    def extract_from_doi(self, doi: str) -> Dict[str, Any]:
        """Extract metadata from DOI using Crossref API."""
        doi = doi.strip()
        if doi.startswith("http"):
            # Extract DOI from URL like https://doi.org/10.1000/example
            match = re.search(r"10\.\d+/[^\s]+", doi)
            if match:
                doi = match.group(0)
        elif doi.startswith("doi:"):
            doi = doi[4:]

        try:
            url = f"https://api.crossref.org/works/{doi}"
            headers = {
                "User-Agent": "PaperCLI/1.0 (https://github.com/your-repo) mailto:your-email@example.com"
            }

            response = http_utils.get(url, headers=headers, timeout=10)
            data = response.json()
            work = data.get("message", {})

            metadata = {}

            titles = work.get("title", [])
            if titles:
                metadata["title"] = titles[0]

            authors = []
            for author in work.get("author", []):
                given = author.get("given", "")
                family = author.get("family", "")
                if given and family:
                    authors.append(f"{given} {family}")
                elif family:
                    authors.append(family)
            metadata["authors"] = (
                " and ".join(authors)
                if authors
                else ""  # Convert to string format for consistency
            )

            if "abstract" in work:
                metadata["abstract"] = work["abstract"]

            published_date = work.get("published-print") or work.get("published-online")
            if published_date and "date-parts" in published_date:
                date_parts = published_date["date-parts"][0]
                if date_parts:
                    metadata["year"] = date_parts[0]

            if "container-title" in work:
                container_titles = work["container-title"]
                if container_titles:
                    metadata["venue_full"] = container_titles[0]
                    # Try to extract acronym from short-container-title
                    if "short-container-title" in work:
                        short_titles = work["short-container-title"]
                        if short_titles:
                            metadata["venue_acronym"] = short_titles[0]

            metadata["doi"] = work.get("DOI", doi)

            if "URL" in work:
                metadata["url"] = work["URL"]

            if "page" in work:
                metadata["pages"] = work["page"]

            if "volume" in work:
                metadata["volume"] = work["volume"]
            if "issue" in work:
                metadata["issue"] = work["issue"]

            work_type = work.get("type", "").lower()
            if "journal" in work_type:
                metadata["paper_type"] = "journal"
            elif "proceedings" in work_type or "conference" in work_type:
                metadata["paper_type"] = "conference"
            elif "preprint" in work_type or "posted-content" in work_type:
                metadata["paper_type"] = "preprint"
            else:
                metadata["paper_type"] = "journal"  # Default for most DOIs

            return metadata

        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to fetch DOI metadata: {e}")
        except Exception as e:
            raise Exception(f"Failed to extract metadata from DOI: {e}")
