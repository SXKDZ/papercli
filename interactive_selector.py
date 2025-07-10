from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.widgets import SearchToolbar, TextArea
import os
from prompt_toolkit.formatted_text import FormattedText
from paper_manager import PaperManager

class InteractivePaperSelector:
    def __init__(self, papers):
        self.papers = papers
        self.paper_manager = PaperManager()
        self.selected_indices = set()
        self.highlighted_index = 0
        self.show_details_panel = False

        self.COL_WIDTHS = {
            "select": 4,
            "year": 6,
            "authors": 30,
            "venue": 15,
            "title": 60 # Adjust as needed
        }

        self.search_toolbar = SearchToolbar()
        self.text_area = TextArea(read_only=True, focus_on_click=False)

        self.kb = KeyBindings()

        @self.kb.add('up')
        def _(event):
            self.highlighted_index = max(0, self.highlighted_index - 1)
            self._update_ui()

        @self.kb.add('down')
        def _(event):
            self.highlighted_index = min(len(self.papers) - 1, self.highlighted_index + 1)
            self._update_ui()

        @self.kb.add(' ')
        def _(event):
            if self.papers:
                paper_id = self.papers[self.highlighted_index].id
                if paper_id in self.selected_indices:
                    self.selected_indices.remove(paper_id)
                else:
                    self.selected_indices.add(paper_id)
                self._update_ui()

        @self.kb.add('enter')
        def _(event):
            event.app.exit(result=self.get_selected_papers())

        @self.kb.add('d')
        def _(event):
            if self.papers:
                self.show_details_panel = True
                self._update_ui()

        @self.kb.add('x')
        def _(event):
            self.show_details_panel = False
            self._update_ui()

        @self.kb.add('c-c')
        def _(event):
            event.app.exit(result=None) # Exit without selection

        self.table_window = Window(content=FormattedTextControl(self._get_table_text), always_hide_cursor=True, height=Dimension(weight=1))
        self.details_window = Window(content=FormattedTextControl(self._get_details_text), always_hide_cursor=True, height=Dimension.exact(0), dont_extend_height=True, style="fg:white bg:black")

        self.root_container = HSplit([
            Window(height=Dimension.exact(1), content=FormattedTextControl(self._get_header_text, style="bold fg:white bg:blue")),
            HSplit([
                self.table_window,
                self.details_window
            ]),
            Window(height=Dimension.exact(1), content=FormattedTextControl(self._get_footer_text, style="bold fg:white bg:green")),
        ])

        self.application = Application(
            layout=Layout(self.root_container),
            key_bindings=self.kb,
            full_screen=True
        )
        self._update_ui()

    def _get_header_text(self):
        return "Use Up/Down to navigate, Space to select/deselect, Enter to confirm, Ctrl+C to cancel."

    def _get_footer_text(self):
        return f"Selected: {len(self.selected_indices)} papers"

    def _get_table_text(self):
        lines = []

        # Header line construction
        # Calculate the actual width for the title column in the header
        # This ensures the header's title column is wide enough to match the longest paper title
        header_title_width = self.COL_WIDTHS['title']

        header_line = (
            f" {'':<{self.COL_WIDTHS['select']}}"
            f" {'Year':<{self.COL_WIDTHS['year']}}"
            f" {'Authors':<{self.COL_WIDTHS['authors']}}"
            f" {'Venue':<{self.COL_WIDTHS['venue']}}"
            f" {'Title':<{header_title_width}}" # Use calculated width for title
        )

        lines.append(("bold fg:cyan", header_line))
        lines.append(("", "\n")) # Newline after header

        for i, paper in enumerate(self.papers):
            is_selected = paper.id in self.selected_indices
            is_highlighted = (i == self.highlighted_index)

            row_style = "" 
            if is_highlighted and is_selected:
                row_style = "bold fg:white bg:ansired"
            elif is_highlighted:
                row_style = "bold fg:white bg:ansiblue"
            elif is_selected:
                row_style = "bold fg:white bg:ansigreen"

            # Format data for each column (initially untruncated)
            select_col = f"[{'X' if is_selected else ' '}]"
            year_col = str(paper.year) if paper.year else "N/A"
            authors_col_full = (paper.authors if paper.authors else "N/A")[:self.COL_WIDTHS['authors']]
            venue_acronym = self.paper_manager._get_venue_acronym(paper.venue, paper.paper_type)
            venue_col_full = (venue_acronym if venue_acronym else "N/A")[:self.COL_WIDTHS['venue']]
            title_col_full = (paper.title if paper.title else "N/A")[:self.COL_WIDTHS['title']]

            # Construct the full paper line with proper spacing and truncation
            paper_line_full = (
                f"{select_col:<{self.COL_WIDTHS['select']}} "
                f"{year_col:<{self.COL_WIDTHS['year']}} "
                f"{authors_col_full:<{self.COL_WIDTHS['authors']}} "
                f"{venue_col_full:<{self.COL_WIDTHS['venue']}} "
                f"{title_col_full:<{self.COL_WIDTHS['title']}}"
            )

            lines.append((row_style, paper_line_full))
            lines.append(('', '\n')) # Newline after each paper entry
        return FormattedText(lines)

    def _get_details_text(self):
        if not self.papers or not self.show_details_panel:
            return FormattedText([])

        paper = self.papers[self.highlighted_index]
        details = [
                                ("bold", ""),
            ("", f"ID: {paper.id}" + "\n"),
            ("", f"Title: {paper.title}" + "\n"),
            ("", f"Authors: {paper.authors}" + "\n"),
            ("", f"Year: {paper.year}" + "\n"),
            ("", f"Venue: {paper.venue}" + "\n"),
            ("", f"Abstract: {paper.abstract if paper.abstract else 'N/A'}" + "\n"),
            ("", f"DBLP URL: {paper.dblp_url if paper.dblp_url else 'N/A'}" + "\n"),
            ("", f"Google Scholar URL: {paper.google_scholar_url if paper.google_scholar_url else 'N/A'}" + "\n"),
            ("", f"PDF Path: {paper.pdf_path if paper.pdf_path else 'N/A'}" + "\n"),
            ("bold", "Press 'X' to close details")
        ]
        return FormattedText(details)

    def _update_ui(self):
        if self.show_details_panel:
            self.details_window.height = Dimension(weight=1)
        else:
            self.details_window.height = Dimension.exact(0)
        self.application.invalidate()

    def get_selected_papers(self):
        return [paper for paper in self.papers if paper.id in self.selected_indices]

    def run(self):
        return self.application.run()