"""
Centralized prompts for LLM interactions throughout PaperCLI.
"""


class ChatPrompts:
    """Prompts for chat functionality."""

    @staticmethod
    def system_message(paper_context: str) -> str:
        """System message for chat interactions."""
        return f"""You are an AI assistant helping to discuss and analyze academic papers. 

{paper_context}

IMPORTANT: Only provide information that is explicitly present in the paper information provided above. Do not hallucinate or make up information. If you cannot answer a question based on the provided information, say "I don't know" or "This information is not available in the provided paper content." You can reference papers by their numbers (e.g., "Paper 1", "Paper 2")."""

    @staticmethod
    def clipboard_prompt(papers_count: int, context_parts: str) -> str:
        """Prompt for external LLM use via clipboard."""
        return f"""I have {papers_count} research paper(s) that I'd like to discuss with you. Here's the information about each paper:

{context_parts}

You can reference these papers by their numbers (e.g., "Paper 1", "Paper 2"). Please help me analyze and understand these papers, compare different approaches, explain key concepts, or discuss how they relate to each other."""

    @staticmethod
    def initial_single_paper(paper_details: str) -> str:
        """Initial content for single paper chat (UI only, not sent to LLM)."""
        return f"""Here is the selected paper for discussion:

{paper_details}

(You can ask questions about this paper or request specific analyses.)"""

    @staticmethod
    def initial_multiple_papers(papers_count: int, paper_details: str) -> str:
        """Initial content for multiple papers chat (UI only, not sent to LLM)."""
        return f"""Here are the {papers_count} selected papers for discussion:

{paper_details}

(You can refer to papers by their numbers, e.g., 'Paper 1', 'Paper 2', etc.)"""

    @staticmethod
    def paper_context_header() -> str:
        """Header for paper context in chat."""
        return "Papers for discussion:\n\n"


class SummaryPrompts:
    """Prompts for paper summarization."""

    @staticmethod
    def academic_summary(full_text: str) -> str:
        """Comprehensive academic paper summary prompt."""
        return f"""You are an excellent academic paper reviewer. You conduct paper summarization on the full paper text provided, with following instructions:

IMPORTANT: Only include information that is explicitly present in the paper text. Do not hallucinate or make up information. If a section is not applicable (e.g., a theory paper may not have experiments), clearly state "Not applicable" or "Not described in the provided text".

Motivation: Explain the motivation behind this research - what problem or gap in knowledge motivated the authors to conduct this study. Only include if explicitly mentioned.

Objective: Begin by clearly stating the primary objective of the research presented in the academic paper. Describe the core idea or hypothesis that underpins the study in simple, accessible language.

Technical Approach: Provide a detailed explanation of the methodology used in the research. Focus on describing how the study was conducted, including any specific techniques, models, or algorithms employed. Only describe what is actually present in the text.

Distinctive Features: Identify and elaborate on what sets this research apart from other studies in the same field. Only mention features that are explicitly highlighted by the authors.

Experimental Setup and Results: Describe the experimental design and data collection process used in the study. Summarize the results obtained or key findings. If this is a theoretical paper without experiments, state "Not applicable - theoretical work".

Advantages and Limitations: Concisely discuss the strengths of the proposed approach and limitations mentioned by the authors. Only include what is explicitly stated in the paper.

Conclusion: Sum up the key points made about the paper's technical approach, its uniqueness, and its comparative advantages and limitations. Base this only on information present in the text.

Please provide your analysis in clear, readable text format (not markdown). Use the exact headers provided above. Be honest about missing information rather than making assumptions.

Paper text:
{full_text[:16000]}"""

    @staticmethod
    def system_message() -> str:
        """System message for summarization requests."""
        return "You are an expert academic paper reviewer specializing in technical paper analysis and summarization. You are extremely careful to only report information that is explicitly present in the provided text and never hallucinate or make assumptions."


class MetadataPrompts:
    """Prompts for metadata extraction."""

    @staticmethod
    def system_message() -> str:
        """System message for metadata extraction."""
        return "You are an expert at extracting metadata from academic papers. Always respond with valid JSON."

    @staticmethod
    def extraction_prompt(pdf_text: str) -> str:
        """Prompt for extracting metadata from PDF text."""
        return f"""
            Extract the following metadata from this academic paper text. Return your response as a JSON object with these exact keys:
            
            - title: The paper title
            - authors: List of author names as strings
            - abstract: The abstract text (if available)
            - year: Publication year as integer (if available)
            - venue_full: Full venue/conference/journal name following these guidelines:
              * For journals: Use full journal name (e.g., "Journal of Chemical Information and Modeling")
              * For conferences: Use full name without "Proceedings of" or ordinal numbers (e.g., "International Conference on Machine Learning" for Proceedings of the 41st International Conference on Machine Learning)
            - venue_acronym: Venue abbreviation following these guidelines:
              * For journals: Use ISO 4 abbreviated format with periods (e.g., "J. Chem. Inf. Model." for Journal of Chemical Information and Modeling)
              * For conferences: Use common name (e.g., "NeurIPS" for Conference on Neural Information Processing Systems, not "NIPS")
            - paper_type: One of "conference", "journal", "workshop", "preprint", "other"
            - doi: DOI (if available)
            - url: URL of the PDF to the paper itself mentioned (if available, not the link to the supplementary material or the code repository)
            - category: Subject category like "cs.LG" (if available)
            
            If any field is not available, use null for that field.
            
            Paper text:
            {pdf_text[:8000]}
            """
