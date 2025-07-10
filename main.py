import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
import pyperclip
import subprocess
import os

from database import init_db, SessionLocal, Paper
from paper_manager import PaperManager
from interactive_selector import InteractivePaperSelector

console = Console()

def display_help():
    help_text = """
Available commands:
  /add       Add a new paper
  /list      List all papers or filter by venue, year, author (and select for actions)
  /search    Search for papers (fuzzy search)
  /help      Display this help message
  /exit      Exit the application

Actions available after selecting papers (from /list or /search):
  /delete    Delete selected paper(s)
  /edit      Bulk edit selected paper(s)
  /export    Export reference of selected paper(s) (bib|md|html|clipboard)
  /chat      Chat with LLM about a selected paper (single selection only)
  /show      Show PDF of selected paper(s)
  /back      Return to main menu
    """
    console.print(Panel(Text(help_text, justify="left"), title="[bold blue]Help[/bold blue]"))

def display_papers_table(papers, title="Papers"):
    if not papers:
        console.print(f"[bold red]No {title.lower()} to display.[/bold red]")
        return
    table = Table(title=title)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="magenta")
    table.add_column("Authors", style="green")
    table.add_column("Year", style="blue")
    table.add_column("Venue", style="yellow")

    for paper in papers:
        table.add_row(str(paper.id), paper.title, paper.authors, str(paper.year) if paper.year else "N/A", paper.venue if paper.venue else "N/A")
    console.print(table)

def process_selected_papers_actions(session, paper_manager, selected_papers, completer):
    console.print("\n[bold yellow]Performing Actions on Selected Papers[/bold yellow]")
    console.print("Available actions: /delete, /edit, /export [bib|md|html|clipboard], /chat, /show, /back")

    while True:
        try:
            completer.current_context = "selected_papers_actions"
            action_command = session.prompt("Selected Papers Action> ").strip()
            if not action_command:
                continue

            if action_command == "/delete":
                if not selected_papers:
                    console.print("[bold red]No papers selected for deletion.[/bold red]")
                    continue
                confirm = session.prompt("Are you sure you want to delete selected papers? (yes/no): ").strip().lower()
                if confirm == "yes":
                    paper_ids_to_delete = [p.id for p in selected_papers]
                    paper_manager.delete_papers(paper_ids_to_delete)
                    console.print(f"[bold green]Deleted {len(paper_ids_to_delete)} papers.[/bold green]")
                    selected_papers.clear() # Clear selection after deletion
                else:
                    console.print("[bold yellow]Deletion cancelled.[/bold yellow]")

            elif action_command == "/edit":
                if not selected_papers:
                    console.print("[bold red]No papers selected for bulk edit.[/bold red]")
                    continue
                console.print("\n[bold yellow]Bulk Edit Selected Papers[/bold yellow]")
                updates = {}
                new_year = session.prompt("New Year (leave blank to skip): ").strip()
                if new_year: updates['year'] = int(new_year)
                new_venue = session.prompt("New Venue (leave blank to skip): ").strip()
                if new_venue: updates['venue'] = new_venue
                new_notes = session.prompt("Add to Notes (leave blank to skip): ").strip()
                if new_notes: updates['notes'] = new_notes

                if updates:
                    paper_manager.bulk_update_papers([p.id for p in selected_papers], updates)
                    console.print(f"[bold green]Bulk updated {len(selected_papers)} papers.[/bold green]")
                else:
                    console.print("[bold yellow]No updates provided.[/bold yellow]")

            elif action_command == "/export":
                console.print("[bold red]Usage: /export [bib|md|html|clipboard][/bold red]")
                completer.current_context = "export_format"
                continue
            elif action_command.startswith("/export "):
                if not selected_papers:
                    console.print("[bold red]No papers selected for export.[/bold red]")
                    continue
                export_parts = action_command.split(" ", 1)
                export_format = export_parts[1].strip().lower()
                
                content = ""
                if export_format == "bib":
                    content = paper_manager.export_to_bibtex(selected_papers)
                elif export_format == "md":
                    content = paper_manager.export_to_markdown(selected_papers)
                elif export_format == "html":
                    content = paper_manager.export_to_html(selected_papers)
                elif export_format == "clipboard":
                    content = paper_manager.export_to_markdown(selected_papers) # Default to markdown for clipboard
                    try:
                        pyperclip.copy(content)
                        console.print("[bold green]Copied to clipboard![/bold green]")
                        continue
                    except Exception as e:
                        console.print(f"[bold red]Error copying to clipboard: {e}. Please ensure you have a clipboard utility installed (e.g., xclip or xsel on Linux).[/bold red]")
                        continue
                else:
                    console.print("[bold red]Invalid export format. Choose from bib, md, html, clipboard.[/bold red]")
                    continue
                
                output_file = session.prompt(f"Enter output file path (e.g., papers.{export_format}): ").strip()
                if not output_file:
                    console.print("[bold red]Output file path cannot be empty.[/bold red]")
                    continue

                try:
                    with open(output_file, "w") as f:
                        f.write(content)
                    console.print(f"[bold green]Exported {len(selected_papers)} papers to {output_file}[/bold green]")
                except Exception as e:
                    console.print(f"[bold red]Error exporting papers:[/bold red] {e}")

            elif action_command == "/chat":
                if len(selected_papers) != 1:
                    console.print("[bold red]Please select exactly one paper to chat about.[/bold red]")
                    continue
                paper_to_chat = selected_papers[0]
                console.print(f"Chatting about: [bold]{paper_to_chat.title}[/bold]")
                user_query = session.prompt("Your question about the paper: ").strip()
                response = paper_manager.chat_with_llm(paper_to_chat.id, user_query)
                console.print(f"[bold blue]LLM Response:[/bold blue] {response}")

            elif action_command == "/show":
                if not selected_papers:
                    console.print("[bold red]No papers selected to show.[/bold red]")
                    continue
                for paper_to_show in selected_papers:
                    if paper_to_show.pdf_path and os.path.exists(paper_to_show.pdf_path):
                        try:
                            if sys.platform == "win32":
                                os.startfile(paper_to_show.pdf_path)
                            elif sys.platform == "darwin":
                                subprocess.run(['open', paper_to_show.pdf_path])
                            else:
                                try:
                                    subprocess.run(['xdg-open', paper_to_show.pdf_path], check=True)
                                except FileNotFoundError:
                                    console.print("[bold red]Error: `xdg-open` not found. Please install it (e.g., `sudo apt-get install xdg-utils` on Debian/Ubuntu) or ensure it's in your PATH.[/bold red]")
                                    continue
                                except subprocess.CalledProcessError as e:
                                    console.print(f"[bold red]Error opening PDF for {paper_to_show.title}: Command failed with exit code {e.returncode}.[/bold red]")
                                    continue
                            console.print(f"[bold green]Opened PDF for:[/bold green] {paper_to_show.title}")
                        except Exception as e:
                            console.print(f"[bold red]An unexpected error occurred opening PDF for {paper_to_show.title}:[/bold red] {e}")
                    else:
                        console.print(f"[bold red]No PDF path found or file does not exist for {paper_to_show.title}.[/bold red]")

            elif action_command == "/back":
                console.print("[bold yellow]Exiting Selected Papers Actions.[/bold yellow]")
                break
            else:
                console.print(f"[bold red]Unknown command: {action_command}[/bold red].")
        except KeyboardInterrupt:
            console.print("\n[bold red]Press /back to exit Selected Papers Actions.[/bold red]")
        except EOFError:
            console.print("[bold red]Exiting Selected Papers Actions.[/bold red]")
            break

class PaperCliCompleter(Completer):
    def __init__(self, initial_context="main_menu"):
        self.current_context = initial_context

    def get_completions(self, document, complete_event):
        word_before_cursor = document.get_word_before_cursor(WORD=True)
        text_before_cursor = document.text_before_cursor.lstrip()

        # Handle /export format autocompletion
        if self.current_context == "selected_papers_actions" and text_before_cursor.startswith("/export "):
            completion_commands = ["bib", "md", "html", "clipboard"]
            # Calculate start_position for the format part
            start_pos = -len(word_before_cursor)
            if " " in text_before_cursor:
                # Find the position of the last space to correctly complete the format
                last_space_index = text_before_cursor.rfind(" ")
                if last_space_index != -1:
                    start_pos = -(len(text_before_cursor) - last_space_index - 1)
            
            for command in completion_commands:
                if command.startswith(word_before_cursor):
                    yield Completion(command, start_position=start_pos)
            return # Exit after yielding format completions

        # Normal context-based completions
        if self.current_context == "main_menu":
            commands = ["/add", "/list", "/search", "/help", "/exit"]
        elif self.current_context == "add_type":
            commands = ["pdf", "arxiv", "dblp", "gs"]
        elif self.current_context == "search_by":
            commands = ["title", "author", "venue", "year"]
        elif self.current_context == "list_filter":
            commands = ["all", "venue", "year", "author", "paper_type"]
        elif self.current_context == "selected_papers_actions":
            commands = ["/delete", "/edit", "/export", "/chat", "/show", "/back"]
        elif self.current_context == "export_format": # This context is now primarily for internal use if needed, or for direct prompts
            commands = ["bib", "md", "html", "clipboard"]
        else:
            commands = []

        for command in commands:
            if command.startswith(word_before_cursor):
                yield Completion(command, start_position=-len(word_before_cursor))

def main():
    init_db()
    console.print(Panel("[bold green]Welcome to PaperCLI![/bold green]"))
    display_help()

    completer = PaperCliCompleter()
    session = PromptSession(history=FileHistory('./.papercli_history'), completer=completer)
    paper_manager = PaperManager()

    while True:
        try:
            completer.current_context = "main_menu"
            command = session.prompt("PaperCLI> ").strip()
            if not command:
                continue

            if command == "/exit":
                console.print("[bold red]Exiting PaperCLI. Goodbye![/bold red]")
                break
            elif command == "/help":
                display_help()
            elif command == "/add":
                console.print("\n[bold yellow]Add Paper[/bold yellow]")
                completer.current_context = "add_type"
                add_type = session.prompt("Add by (pdf, arxiv, dblp, gs): ").strip().lower() or "pdf"
                if add_type == "pdf":
                    pdf_path = session.prompt("Enter PDF file path: ").strip()
                    try:
                        paper = paper_manager.add_paper_from_pdf(pdf_path)
                        console.print(f"[bold green]Added paper:[/bold green] {paper.title}")
                    except Exception as e:
                        console.print(f"[bold red]Error adding PDF:[/bold red] {e}")
                elif add_type == "arxiv":
                    arxiv_id = session.prompt("Enter arXiv ID: ").strip()
                    try:
                        paper = paper_manager.add_paper_from_arxiv(arxiv_id)
                        console.print(f"[bold green]Added paper:[/bold green] {paper.title}")
                    except Exception as e:
                        console.print(f"[bold red]Error adding arXiv paper:[/bold red] {e}")
                elif add_type == "dblp":
                    dblp_url = session.prompt("Enter DBLP URL: ").strip()
                    try:
                        paper = paper_manager.add_paper_from_dblp(dblp_url)
                        console.print(f"[bold green]Added paper:[/bold green] {paper.title}")
                    except Exception as e:
                        console.print(f"[bold red]Error adding DBLP paper:[/bold red] {e}")
                elif add_type == "gs":
                    gs_url = session.prompt("Enter Google Scholar URL: ").strip()
                    try:
                        paper = paper_manager.add_paper_from_google_scholar(gs_url)
                        console.print(f"[bold green]Added paper:[/bold green] {paper.title}")
                    except Exception as e:
                        console.print(f"[bold red]Error adding Google Scholar paper:[/bold red] {e}")
                else:
                    console.print("[bold red]Invalid add type.[/bold red]")
            elif command == "/list":
                console.print("\n[bold yellow]List Papers[/bold yellow]")
                completer.current_context = "list_filter"
                list_by = session.prompt("List by (all, venue, year, author, paper_type) [all]: ").strip().lower() or "all"
                query = None
                if list_by != "all":
                    query = session.prompt(f"Enter {list_by} to filter by: ").strip()
                
                results = paper_manager.list_papers(list_by, query)
                
                if results:
                    selector = InteractivePaperSelector(results)
                    selected_papers = selector.run()

                    if selected_papers is not None:
                        if selected_papers:
                            console.print(f"[bold green]Selected {len(selected_papers)} papers.[/bold green]")
                            perform_selected_actions(session, paper_manager, selected_papers, completer)
                        else:
                            console.print("[bold yellow]No papers selected.[/bold yellow]")
                    else:
                        console.print("[bold yellow]Selection cancelled.[/bold yellow]")
                else:
                    console.print("[bold red]No papers found matching your criteria.[/bold red]")
            elif command == "/search":
                console.print("\n[bold yellow]Search Papers[/bold yellow]")
                search_query = session.prompt("Enter search query: ").strip()
                completer.current_context = "search_by"
                search_by = session.prompt("Search by (title, author, venue, year) [title]: ").strip().lower() or "title"
                
                results = paper_manager.search_papers(search_query, search_by)
                
                if results:
                    selector = InteractivePaperSelector(results)
                    selected_papers = selector.run()
                    if selected_papers is not None:
                        if selected_papers:
                            console.print(f"[bold green]Selected {len(selected_papers)} papers.[/bold green]")
                            perform_selected_actions(session, paper_manager, selected_papers, completer)
                        else:
                            console.print("[bold yellow]No papers selected.[/bold yellow]")
                    else:
                        console.print("[bold yellow]Selection cancelled.[/bold yellow]")
                else:
                    console.print("[bold red]No papers found matching your criteria.[/bold red]")
            elif command == "/fuzzy_search":
                console.print("\n[bold yellow]Lookup Paper (Fuzzy Search)[/bold yellow]")
                lookup_query = session.prompt("Enter lookup query (title or author): ").strip()
                
                results = paper_manager.fuzzy_search_papers(lookup_query)
                
                if results:
                    selector = InteractivePaperSelector(results)
                    selected_papers = selector.run()
                    if selected_papers is not None:
                        if selected_papers:
                            console.print(f"[bold green]Selected {len(selected_papers)} papers.[/bold green]")
                            perform_selected_actions(session, paper_manager, selected_papers, completer)
                        else:
                            console.print("[bold yellow]No papers selected.[/bold yellow]")
                    else:
                        console.print("[bold yellow]Selection cancelled.[/bold yellow]")
                else:
                    console.print("[bold red]No papers found matching your query.[/bold red]")
            elif command == "/chat":
                console.print("\n[bold yellow]Chat with LLM[/bold yellow]")
                console.print("[bold yellow]Please use /list, /search, or /lookup to select a paper for chat.[/bold yellow]")
            elif command == "/update":                console.print("\n[bold yellow]Update Paper[/bold yellow]")                all_papers = paper_manager.list_papers() # Get all papers for selection                display_papers_table(all_papers, title="Available Papers for Update")                paper_id_str = session.prompt("Enter paper ID to update: ").strip()                if not paper_id_str:                    continue                try:                    paper_id = int(paper_id_str)                    paper_to_update = paper_manager.get_paper_by_id(paper_id)                    if paper_to_update:                        console.print(f"Updating paper: [bold]{paper_to_update.title}[/bold]")                        updates = {}                        if paper_to_update.pdf_path and os.path.exists(paper_to_update.pdf_path):                            llm_extract_choice = session.prompt("Extract metadata using LLM from PDF? (yes/no) [no]: ").strip().lower()                            if llm_extract_choice == 'yes':                                console.print("[bold yellow]Extracting metadata with LLM...[/bold yellow]")                                extracted_data = paper_manager.extract_metadata_with_llm(paper_to_update)                                if extracted_data:                                    console.print("[bold green]LLM extracted metadata:[/bold green]")                                    for key, value in extracted_data.items():                                        console.print(f"  {key.replace('_', ' ').title()}: {value}")                                    confirm_llm_updates = session.prompt("Apply LLM extracted metadata? (yes/no) [yes]: ").strip().lower() or 'yes'                                    if confirm_llm_updates == 'yes':                                        if 'title' in extracted_data and extracted_data['title']: updates['title'] = extracted_data['title']                                        if 'authors' in extracted_data and extracted_data['authors']: updates['authors'] = extracted_data['authors']                                        if 'year' in extracted_data and extracted_data['year']: updates['year'] = extracted_data['year']                                        if 'venue' in extracted_data and extracted_data['venue']: updates['venue'] = extracted_data['venue']                                        if 'abstract' in extracted_data and extracted_data['abstract']: updates['abstract'] = extracted_data['abstract']                                        if 'paper_type' in extracted_data and extracted_data['paper_type']: updates['paper_type'] = extracted_data['paper_type']                                        console.print("[bold green]LLM extracted data applied for further refinement.[/bold green]")                                else:                                    console.print("[bold red]LLM metadata extraction failed or returned no data.[/bold red]")                        editable_fields = {                            "1": "title",                            "2": "authors",                            "3": "year",                            "4": "venue",                            "5": "abstract",                            "6": "notes",                            "7": "paper_type"                        }                        while True:                            console.print("\n[bold yellow]Select field to edit (or 'd' for done):[/bold yellow]")                            for num, field_name in editable_fields.items():                                current_value = updates.get(field_name, getattr(paper_to_update, field_name))                                console.print(f"  [cyan]{num}. {field_name.replace('_', ' ').title()}:[/cyan] {current_value if current_value is not None else 'N/A'}")                            edit_choice = session.prompt("Edit field number (or 'd' for done)> ").strip().lower()                            if not edit_choice:                                continue                            if edit_choice == 'd':                                break                            if edit_choice in editable_fields:                                field_to_edit = editable_fields[edit_choice]                                current_value = updates.get(field_to_edit, getattr(paper_to_update, field_to_edit))                                new_value = session.prompt(f"Enter new {field_to_edit.replace('_', ' ').lower()} (current: {current_value if current_value is not None else 'N/A'}) [leave blank to keep]: ").strip()                                if new_value:                                    if field_to_edit == 'year':                                        try:                                            updates[field_to_edit] = int(new_value)                                        except ValueError:                                            console.print("[bold red]Invalid year. Please enter a number.[/bold red]")                                    else:                                        updates[field_to_edit] = new_value                                console.print(f"[bold green]{field_to_edit.replace('_', ' ').title()} updated in staging.[/bold green]")                            else:                                console.print("[bold red]Invalid field number.[/bold red]")                        if updates:                            console.print("\n[bold yellow]Proposed Changes:[/bold yellow]")                            for key, value in updates.items():                                old_value = getattr(paper_to_update, key)                                console.print(f"  [cyan]{key.replace('_', ' ').title()}:[/cyan] [magenta]{old_value if old_value is not None else 'N/A'}[/magenta] -> [green]{value}[/green]")                            confirm_update = session.prompt("Confirm update? (yes/no): ").strip().lower()                            if confirm_update == 'yes':                                updated_paper = paper_manager.update_paper(paper_id, updates)                                if updated_paper:                                    console.print(f"[bold green]Paper updated successfully:[/bold green] {updated_paper.title}[/bold green]")                                else:                                    console.print("[bold red]Failed to update paper.[/bold red]")                            else:                                console.print("[bold yellow]Update cancelled.[/bold yellow]")                        else:                            console.print("[bold yellow]No updates provided.[/bold yellow]")                    else:                        console.print("[bold red]Paper not found with that ID.[/bold red]")                except ValueError:                    console.print("[bold red]Invalid paper ID. Please enter a number.[/bold red]")                except Exception as e:                    console.print(f"[bold red]Error updating paper:[/bold red] {e}")
            else:
                console.print(f"[bold red]Unknown command: {command}[/bold red]. Type /help for available commands.")
        except KeyboardInterrupt:
            console.print("\n[bold red]Press /exit to quit.[/bold red]")
        except EOFError:
            console.print("[bold red]Exiting PaperCLI. Goodbye![/bold red]")
            break
        finally:
            paper_manager.close()

if __name__ == "__main__":
    main()