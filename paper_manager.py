import json
import requests
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader
from scholarly import scholarly
from database import SessionLocal, Paper
from sqlalchemy import or_
from thefuzz import fuzz
import openai
import os
import re

class PaperManager:
    def __init__(self):
        self.db = SessionLocal()
        openai.api_key = os.getenv("OPENAI_API_KEY")

    def _get_venue_acronym(self, venue_full, paper_type=None):
        # Simplified acronym generation.
        # For a robust solution, consider a dedicated library or a comprehensive mapping.

        # Common conference acronyms (can be expanded)
        conference_acronyms = {
            "Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition": "CVPR",
            "International Conference on Machine Learning": "ICML",
            "Advances in Neural Information Processing Systems": "NeurIPS",
            "International Conference on Learning Representations": "ICLR",
            "Association for Computational Linguistics": "ACL",
            "European Conference on Computer Vision": "ECCV",
            "International Conference on Computer Vision": "ICCV",
            "Conference on Empirical Methods in Natural Language Processing": "EMNLP",
            "Annual Meeting of the Association for Computational Linguistics": "ACL"
        }

        # ISO4-like abbreviations for journals (can be expanded)
        iso4_abbreviations = {
            "International": "Int.",
            "Journal": "J.",
            "Computer": "Comput.",
            "Vision": "Vis.",
            "Machine": "Mach.",
            "Learning": "Learn.",
            "Artificial": "Artif.",
            "Intelligence": "Intell.",
            "Neural": "Neural",
            "Information": "Inf.",
            "Processing": "Process.",
            "Systems": "Syst.",
            "Natural": "Nat.",
            "Language": "Lang.",
            "Computational": "Comput.",
            "Methods": "Methods",
            "Empirical": "Empir.",
            "Pattern": "Pattern",
            "Recognition": "Recogn."
        }

        if paper_type == "conference" and venue_full in conference_acronyms:
            return conference_acronyms[venue_full]
        elif paper_type == "journal":
            words = venue_full.split()
            acronym_words = []
            for word in words:
                # Remove punctuation for abbreviation
                cleaned_word = re.sub(r'[^a-zA-Z]', '', word)
                if cleaned_word in iso4_abbreviations:
                    acronym_words.append(iso4_abbreviations[cleaned_word])
                else:
                    acronym_words.append(word) # Keep original if no abbreviation
            return " ".join(acronym_words)
        else:
            # Default to full name or a simple acronym if type is unknown or not specified
            # For now, just return the full name if no specific rule applies
            return venue_full

    def add_paper_from_pdf(self, pdf_path, paper_type=None, notes=None):
        try:
            reader = PdfReader(pdf_path)
            text_content = ""
            for page in reader.pages:
                text_content += page.extract_text() or ""

            metadata = reader.metadata
            title = metadata.get('/Title', None)
            authors = metadata.get('/Author', None)
            year = None
            venue = None
            abstract = None

            # If basic metadata is missing, try LLM extraction
            if not (title and authors and year and venue and abstract):
                llm_prompt = f"""
                Extract the following information from the provided academic paper text.
                Respond in JSON format with keys: "title", "authors" (comma-separated string), "year" (integer), "venue" (string), "abstract" (string), "paper_type" (e.g., "journal", "conference", "preprint", "book chapter", "thesis", "report", "other").
                If a field is not found, use null.

                Paper Text:
                {text_content[:4000]} # Limit text to avoid exceeding token limits
                """
                try:
                    response = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "You are an expert in academic paper metadata extraction. Provide concise JSON output."},
                            {"role": "user", "content": llm_prompt}
                        ],
                        response_format={"type": "json_object"}
                    )
                    llm_output = response.choices[0].message.content
                    extracted_data = json.loads(llm_output)

                    title = extracted_data.get("title") or title
                    authors = extracted_data.get("authors") or authors
                    year = extracted_data.get("year") or year
                    venue = extracted_data.get("venue") or venue
                    abstract = extracted_data.get("abstract") or abstract
                    paper_type = extracted_data.get("paper_type") or paper_type

                except Exception as llm_e:
                    print(f"Warning: LLM metadata extraction failed: {llm_e}")
                    # Fallback to whatever was extracted from PDF directly

            # Use extracted or default values
            title = title if title else 'Unknown Title'
            authors = authors if authors else 'Unknown Author'
            venue_full = venue if venue else 'N/A'
            venue_acronym = self._get_venue_acronym(venue_full, paper_type)

            paper = Paper(
                title=title,
                authors=authors,
                year=year,
                venue=venue_full, # Store full venue name
                abstract=abstract,
                pdf_path=pdf_path,
                paper_type=paper_type,
                notes=notes
            )
            self.db.add(paper)
            self.db.commit()
            return paper
        except Exception as e:
            self.db.rollback()
            raise e

    def add_paper_from_arxiv(self, arxiv_id, paper_type=None, notes=None):
        try:
            search_query = scholarly.search_pubs(arxiv_id)
            pub = next(search_query)

            # Download PDF
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            pdf_dir = "pdfs"
            os.makedirs(pdf_dir, exist_ok=True)
            pdf_path = os.path.join(pdf_dir, f"{arxiv_id}.pdf")
            
            response = requests.get(pdf_url, stream=True)
            response.raise_for_status() # Raise an exception for HTTP errors
            with open(pdf_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Extract metadata
            title = pub['bib']['title']
            authors = ", ".join(pub['bib']['author'])
            year = int(pub['bib']['pub_year'])
            abstract = pub['bib'].get('abstract', '')
            
            # Determine venue and paper type (arXiv papers are typically preprints)
            venue_full = pub['bib'].get('journal', 'arXiv') # Scholarly might provide a journal if published
            if not paper_type:
                paper_type = "preprint" # Default for arXiv
            venue_acronym = self._get_venue_acronym(venue_full, paper_type)

            paper = Paper(
                title=title,
                authors=authors,
                year=year,
                abstract=abstract,
                arxiv_id=arxiv_id,
                pdf_path=pdf_path,
                venue=venue_full, # Store full venue name
                paper_type=paper_type,
                notes=notes
            )
            self.db.add(paper)
            self.db.commit()
            return paper
        except Exception as e:
            self.db.rollback()
            raise e

    def add_paper_from_dblp(self, dblp_url, paper_type=None, notes=None):
        try:
            response = requests.get(dblp_url)
            soup = BeautifulSoup(response.content, 'lxml')
            title_tag = soup.find('h1', class_='title')
            title = title_tag.text.strip() if title_tag else 'Unknown Title'
            authors = ', '.join([a.text.strip() for a in soup.find_all('span', itemprop='author')])
            year_tag = soup.find('span', class_='publ')
            year = int(year_tag.text.strip().split(' ')[-1]) if year_tag and year_tag.text.strip().split(' ')[-1].isdigit() else None

            venue_full = None
            # Try to find venue information
            venue_tag = soup.find('span', class_='publ')
            if venue_tag:
                # DBLP often has the venue in the same span as the year or in a preceding <em> tag
                venue_text = venue_tag.find('a').text.strip() if venue_tag.find('a') else venue_tag.text.strip()
                # Clean up the venue text, remove year if present
                venue_full = re.sub(r'\d{4}', '', venue_text).strip()
                if venue_full.endswith('.'):
                    venue_full = venue_full[:-1]

            # Determine paper type based on common DBLP patterns or keywords
            if not paper_type:
                if "journal" in dblp_url.lower() or (venue_full and "journal" in venue_full.lower()):
                    paper_type = "journal"
                elif "conf" in dblp_url.lower() or (venue_full and ("proceedings" in venue_full.lower() or "conference" in venue_full.lower())):
                    paper_type = "conference"
                else:
                    paper_type = "other"

            venue_acronym = self._get_venue_acronym(venue_full, paper_type)
            
            paper = Paper(
                title=title,
                authors=authors,
                year=year,
                venue=venue_full, # Store full venue name
                dblp_url=dblp_url,
                paper_type=paper_type,
                notes=notes
            )
            self.db.add(paper)
            self.db.commit()
            return paper
        except Exception as e:
            self.db.rollback()
            raise e

    def add_paper_from_google_scholar(self, gs_url, paper_type=None, notes=None):
        try:
            # Use the URL as a search query for scholarly. This is a heuristic.
            # A more robust solution might involve parsing the URL for specific IDs
            # or using a dedicated Google Scholar API if available and allowed.
            search_query = scholarly.search_pubs(gs_url)
            pub = next(search_query, None) # Get the first result, or None if no results

            if pub:
                title = pub['bib'].get('title', 'Unknown Title')
                authors = ", ".join(pub['bib'].get('author', []))
                year = int(pub['bib']['pub_year']) if 'pub_year' in pub['bib'] else None
                abstract = pub['bib'].get('abstract', '')
                venue_full = pub['bib'].get('journal', pub['bib'].get('venue', 'N/A')) # Try 'journal' then 'venue'

                # Attempt to infer paper_type if not provided
                if not paper_type:
                    if 'journal' in pub['bib']:
                        paper_type = "journal"
                    elif 'conference' in pub['bib'] or 'booktitle' in pub['bib']:
                        paper_type = "conference"
                    else:
                        paper_type = "other"

                venue_acronym = self._get_venue_acronym(venue_full, paper_type)

                paper = Paper(
                    title=title,
                    authors=authors,
                    year=year,
                    abstract=abstract,
                    google_scholar_url=gs_url,
                    venue=venue_full, # Store full venue name
                    paper_type=paper_type,
                    notes=notes
                )
                self.db.add(paper)
                self.db.commit()
                return paper
            else:
                # Fallback if scholarly doesn't find anything
                paper = Paper(
                    title=f"Paper from Google Scholar URL: {gs_url} (Metadata not found)",
                    google_scholar_url=gs_url,
                    paper_type=paper_type,
                    notes=notes
                )
                self.db.add(paper)
                self.db.commit()
                return paper

        except Exception as e:
            self.db.rollback()
            raise e

    def search_papers(self, query, search_by="title"):
        query_lower = f"%{query.lower()}%"
        if search_by == "title":
            papers = self.db.query(Paper).filter(Paper.title.ilike(query_lower)).all()
        elif search_by == "author":
            papers = self.db.query(Paper).filter(Paper.authors.ilike(query_lower)).all()
        elif search_by == "venue":
            papers = self.db.query(Paper).filter(Paper.venue.ilike(query_lower)).all()
        elif search_by == "year":
            try:
                year_int = int(query)
                papers = self.db.query(Paper).filter(Paper.year == year_int).all()
            except ValueError:
                papers = []
        else:
            papers = []
        return papers

    def fuzzy_search_papers(self, query, threshold=70):
        all_papers = self.db.query(Paper).all()
        results = []
        for paper in all_papers:
            title_score = fuzz.ratio(query.lower(), paper.title.lower())
            author_score = fuzz.ratio(query.lower(), paper.authors.lower() if paper.authors else '')
            
            if title_score >= threshold or author_score >= threshold:
                results.append((max(title_score, author_score), paper))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return [paper for score, paper in results]

    def get_paper_by_id(self, paper_id):
        return self.db.query(Paper).filter(Paper.id == paper_id).first()

    def update_paper(self, paper_id, updates):
        try:
            paper = self.get_paper_by_id(paper_id)
            if paper:
                for key, value in updates.items():
                    setattr(paper, key, value)
                self.db.commit()
                return paper
            return None
        except Exception as e:
            self.db.rollback()
            raise e

    def delete_papers(self, paper_ids):
        try:
            self.db.query(Paper).filter(Paper.id.in_(paper_ids)).delete(synchronize_session=False)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def bulk_update_papers(self, paper_ids, updates):
        try:
            self.db.query(Paper).filter(Paper.id.in_(paper_ids)).update(updates, synchronize_session=False)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def extract_metadata_with_llm(self, paper):
        if not paper.pdf_path or not os.path.exists(paper.pdf_path):
            return None

        try:
            reader = PdfReader(paper.pdf_path)
            text_content = ""
            for page in reader.pages:
                text_content += page.extract_text() or ""

            llm_prompt = f"""
            Extract the following information from the provided academic paper text.
            Respond in JSON format with keys: "title", "authors" (comma-separated string), "year" (integer), "venue" (string), "abstract" (string), "paper_type" (e.g., "journal", "conference", "preprint", "book chapter", "thesis", "report", "other").
            If a field is not found, use null.

            Paper Text:
            {text_content[:4000]} # Limit text to avoid exceeding token limits
            """
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert in academic paper metadata extraction. Provide concise JSON output."},
                    {"role": "user", "content": llm_prompt}
                ],
                response_format={"type": "json_object"}
            )
            llm_output = response.choices[0].message.content
            extracted_data = json.loads(llm_output)
            return extracted_data
        except Exception as e:
            print(f"Error during LLM metadata extraction: {e}")
            return None

    def chat_with_llm(self, paper_id, user_query):
        paper = self.get_paper_by_id(paper_id)
        if not paper:
            return "Paper not found."

        # Construct a prompt for the LLM
        prompt = f"""You are an AI assistant specialized in academic papers. 
        Here is information about a paper:
        Title: {paper.title}
        Authors: {paper.authors}
        Year: {paper.year}
        Abstract: {paper.abstract if paper.abstract else 'N/A'}
        
        User's question about this paper: {user_query}
        
        Please provide a concise and informative answer based on the provided paper information.
        """
        
        try:
            response = openai.chat.completions.create(
                model="gpt-3.5-turbo",  # Or another suitable model
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ]
            )
            llm_response = response.choices[0].message.content
            
            # Optionally, add user's query and LLM's response to paper notes
            paper.notes = (paper.notes if paper.notes else "") + f"\n\nUser: {user_query}\nLLM: {llm_response}"
            self.db.commit()
            
            return llm_response
        except openai.APIError as e:
            self.db.rollback()
            return f"OpenAI API Error: {e}"
        except Exception as e:
            self.db.rollback()
            return f"An error occurred during LLM interaction: {e}"

    def export_to_bibtex(self, papers):
        bibtex_entries = []
        for paper in papers:
            # Simplified BibTeX generation. A more robust solution would use a dedicated BibTeX library.
            entry = f"@article{{{paper.id},\n"
            entry += f"  title={{{paper.title}}},\n"
            entry += f"  author={{{paper.authors}}},\n"
            if paper.year: entry += f"  year={{{paper.year}}},\n"
            if paper.venue: entry += f"  journal={{{paper.venue}}},\n"
            entry += f"}}"
            bibtex_entries.append(entry)
        return "\n\n".join(bibtex_entries)

    def export_to_markdown(self, papers):
        markdown_output = []
        for paper in papers:
            markdown_output.append(f"## {paper.title}\n")
            markdown_output.append(f"*Authors*: {paper.authors}\n")
            if paper.year: markdown_output.append(f"*Year*: {paper.year}\n")
            if paper.venue: markdown_output.append(f"*Venue*: {paper.venue}\n")
            if paper.abstract: markdown_output.append(f"*Abstract*: {paper.abstract}\n")
            if paper.notes: markdown_output.append(f"*Notes*: {paper.notes}\n")
            markdown_output.append("\n---\n\n")
        return "".join(markdown_output)

    def export_to_html(self, papers):
        html_output = ["<!DOCTYPE html>\n<html>\n<head><title>Papers</title></head>\n<body>\n<h1>Paper Export</h1>\n"]
        for paper in papers:
            html_output.append(f"<div>\n  <h2>{paper.title}</h2>\n")
            html_output.append(f"  <p><strong>Authors:</strong> {paper.authors}</p>\n")
            if paper.year: html_output.append(f"  <p><strong>Year:</strong> {paper.year}</p>\n")
            if paper.venue: html_output.append(f"  <p><strong>Venue:</strong> {paper.venue}</p>\n")
            if paper.abstract: html_output.append(f"  <p><strong>Abstract:</strong> {paper.abstract}</p>\n")
            if paper.notes: html_output.append(f"  <p><strong>Notes:</strong> {paper.notes}</p>\n")
            html_output.append("</div>\n<hr>\n")
        html_output.append("</body>\n</html>")
        return "".join(html_output)

    def list_papers(self, list_by="all", query=None):
        q = self.db.query(Paper)
        if list_by == "venue" and query:
            q = q.filter(Paper.venue.ilike(f"%{query.lower()}%" ))
        elif list_by == "year" and query:
            try:
                year_int = int(query)
                q = q.filter(Paper.year == year_int)
            except ValueError:
                return []
        elif list_by == "author" and query:
            q = q.filter(Paper.authors.ilike(f"%{query.lower()}%" ))
        elif list_by == "paper_type" and query:
            q = q.filter(Paper.paper_type.ilike(f"%{query.lower()}%" ))
        return q.all()

    def close(self):
        self.db.close()
