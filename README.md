# PaperCLI

```
 ██████╗  █████╗ ██████╗ ███████╗██████╗  ██████╗██╗     ██╗
 ██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔════╝██║     ██║
 ██████╔╝███████║██████╔╝█████╗  ██████╔╝██║     ██║     ██║
 ██╔═══╝ ██╔══██║██╔═══╝ ██╔══╝  ██╔══██╗██║     ██║     ██║
 ██║     ██║  ██║██║     ███████╗██║  ██║╚██████╗███████╗██║
 ╚═╝     ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝
                                                              
        📚 Your Command-Line Research Paper Manager 📚
```

A powerful command-line paper management system for researchers and academics. PaperCLI helps you organize, search, and manage your research papers with an intuitive terminal interface.

## Features

### 📄 Paper Management
- **Multiple Import Sources**: Add papers from arXiv, DBLP, OpenReview, local PDFs, BibTeX, and RIS files
- **Smart Metadata Extraction**: Automatically extract metadata from PDFs and online sources
- **Collection Organization**: Organize papers into custom collections
- **Comprehensive Search**: Filter papers by title, author, venue, year, type, and collection

### 🤖 AI-Powered Features
- **Interactive Chat Interface**: Local chat dialog with configurable OpenAI models (GPT-4o, etc.)
  - Automatic PDF content inclusion (configurable pages limit) for comprehensive context
  - Auto-summarization for papers without notes
  - Input history navigation and keyboard shortcuts
- **Browser Chat Integration**: Quick access to Claude, ChatGPT, or Gemini web interfaces
- **Enhanced Metadata**: AI-powered metadata extraction and improvement

### 📊 Export & Integration
- **Multiple Export Formats**: Export to BibTeX, IEEE references, Markdown, HTML, and JSON
- **Clipboard Support**: Copy paper data directly to clipboard
- **PDF Management**: Automatic PDF downloading and organization

### 🔧 Advanced Features
- **OneDrive Sync**: Comprehensive synchronization with conflict detection and resolution options
- **Database Health**: Built-in diagnostic tools for database maintenance
- **Interactive UI**: Modern terminal interface with auto-completion and consistent status messaging
- **Multi-selection**: Batch operations on multiple papers
- **Real-time Search**: Filter and search as you type
- **Version Management**: Automatic update checking and seamless upgrades
- **Cross-platform**: Works with pipx, pip, or source installations

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Using pipx (Recommended)
```bash
# Install directly from GitHub
pipx install git+https://github.com/SXKDZ/papercli.git

# Run from anywhere
papercli
```

### Using pip
```bash
# Install directly from GitHub
pip install git+https://github.com/SXKDZ/papercli.git

# Run from anywhere
papercli
```

### Install from Source
```bash
git clone https://github.com/SXKDZ/papercli.git
cd papercli
pip install -r requirements.txt

# Run the application
python -m ng.papercli
```

## Quick Start

1. **Launch PaperCLI**:
   ```bash
   # If installed via pipx or pip
   papercli
   
   # Or if running from source
   python -m ng.papercli
   ```

2. **Set up OpenAI API key** (prompted on first run if missing):
   - Option 1: Environment variable (recommended)
     ```bash
     export OPENAI_API_KEY=your_openai_api_key_here
     ```
   - Option 2: Create `.env` file in current directory or `~/.papercli/`
     ```bash
     echo "OPENAI_API_KEY=your_openai_api_key_here" > .env
     ```

3. **Add your first paper** (arXiv is now the default option):
   ```
   /add arxiv 2307.10635
   ```

4. **Search and filter**:
   ```
   /filter all machine learning
   ```

5. **Export your library**:
   ```
   /export bibtex
   ```

## Commands Reference

### Core Commands
- `/add` - Open add dialog or add paper directly
  - `/add arxiv <id>` - Add from an arXiv ID (e.g., 2307.10635)
  - `/add dblp <url>` - Add from a DBLP URL
  - `/add openreview <id>` - Add from an OpenReview ID
  - `/add doi <id>` - Add from a DOI
  - `/add pdf <path>` - Add from a local PDF file
  - `/add bib <path>` - Add papers from a BibTeX file
  - `/add ris <path>` - Add papers from a RIS file
  - `/add manual` - Add a paper with manual entry
- `/filter` - Filter papers by criteria or search all fields
  - `/filter all <keyword>` - Search across all fields
  - `/filter title <keyword>` - Search in paper titles
  - `/filter abstract <keyword>` - Search in paper abstracts
  - `/filter notes <keyword>` - Search in paper notes
  - `/filter year <year>` - Filter by publication year
  - `/filter author <name>` - Filter by author name
  - `/filter venue <name>` - Filter by venue name
  - `/filter type <type>` - Filter by paper type
  - `/filter collection <name>` - Filter by collection name
- `/sort` - Open sort dialog or sort directly
  - `/sort title` - Sort by title
  - `/sort authors` - Sort by author names
  - `/sort venue` - Sort by venue
  - `/sort year` - Sort by publication year
- `/all` - Show all papers in the database
- `/select` - Enter multi-selection mode to act on multiple papers
- `/clear` - Clear all selected papers
- `/help` - Show help panel (or press F1)
- `/log` - Show the error log panel
- `/exit` - Exit the application (or press Ctrl+C)

### Paper Operations
Work on the paper under the cursor ► or selected papers ✓:
- `/chat [provider]` - Chat with an LLM about the paper(s)
  - `/chat` - Open local chat interface with OpenAI GPT (interactive dialog)
  - `/chat claude` - Open Claude AI in browser
  - `/chat chatgpt` - Open ChatGPT in browser  
  - `/chat gemini` - Open Google Gemini in browser
- `/edit` - Open edit dialog or edit field directly
  - `/edit extract-pdf` - Extract metadata from PDF
  - `/edit summarize` - Generate LLM summary
  - `/edit title <text>` - Edit the title
  - `/edit abstract <text>` - Edit the abstract
  - `/edit notes <text>` - Edit personal notes
  - `/edit venue_full <text>` - Edit full venue name
  - `/edit venue_acronym <text>` - Edit venue acronym
  - `/edit year <number>` - Edit publication year
  - `/edit paper_type <type>` - Edit paper type
  - `/edit doi <text>` - Edit DOI
  - `/edit pages <text>` - Edit page numbers
  - `/edit preprint_id <text>` - Edit preprint ID
  - `/edit url <text>` - Edit paper URL
- `/open` - Open the PDF for the paper(s)
- `/detail` - Show detailed metadata for the paper(s)
- `/export` - Export paper(s) to a file or clipboard
  - `/export bibtex` - Export to BibTeX format
  - `/export ieee` - Export to IEEE reference format
  - `/export markdown` - Export to Markdown format
  - `/export html` - Export to HTML format
  - `/export json` - Export to JSON format
- `/copy-prompt` - Copy paper prompt to clipboard for use with any LLM
- `/delete` - Delete the paper(s) from the library

### Collection Management
- `/collect` - Manage collections
- `/collect purge` - Delete all empty collections
- `/add-to` - Add selected paper(s) to a collection
- `/remove-from` - Remove selected paper(s) from a collection

### System Commands
- `/sync` - OneDrive synchronization with conflict detection and resolution
- `/doctor` - Diagnose and fix database/system issues (runs diagnostic check by default)
  - `/doctor clean` - Clean orphaned database records and PDF files
  - `/doctor help` - Show doctor command help
- `/config` - Configuration management for models, API keys, and sync settings
  - `/config show` - Show all current configuration
  - `/config model <model>` - Set OpenAI model (gpt-4o, gpt-4o-mini, gpt-3.5-turbo, etc.)
  - `/config openai_api_key <key>` - Set OpenAI API key
  - `/config max-tokens <number>` - Set OpenAI max tokens (default: 4000)
  - `/config temperature <number>` - Set OpenAI temperature (default: 0.7)
  - `/config remote <path>` - Set remote sync path for OneDrive
  - `/config auto-sync enable|disable` - Enable/disable automatic sync after edits
  - `/config auto-sync-interval <seconds>` - Set auto-sync interval (default: 5s)
  - `/config pdf-pages <number>` - Set PDF pages limit for chat/summarize operations
  - `/config help` - Show configuration help
- `/version` - Version management and updates
  - `/version check` - Check for available updates
  - `/version update` - Update to the latest version (if possible)
  - `/version info` - Show detailed version information
- `/log` - Show activity log panel

## Supported Sources

### Academic Platforms
- **arXiv**: Add papers using arXiv IDs (e.g., `2307.10635`)
- **DBLP**: Import papers from DBLP URLs
- **OpenReview**: Add papers using OpenReview IDs

### File Formats
- **PDF**: Local PDF files with automatic metadata extraction
- **BibTeX**: Import from `.bib` files
- **RIS**: Import from `.ris` files
- **Manual Entry**: Add papers manually with custom metadata

## Configuration

PaperCLI will prompt you for configuration on first run if needed. You can set up configuration in two ways:

### Method 1: Environment Variables (Recommended)
```bash
# Required for AI features
export OPENAI_API_KEY=your_openai_api_key_here

# Optional settings
export OPENAI_MODEL=gpt-4o  # defaults to gpt-4o
export OPENAI_MAX_TOKENS=4000  # defaults to 4000
export OPENAI_TEMPERATURE=0.7  # defaults to 0.7
export PAPERCLI_DATA_DIR=/path/to/data  # defaults to ~/.papercli
export PAPERCLI_PDF_PAGES=10  # defaults to 10 pages for chat/summarize
export PAPERCLI_THEME=textual-dark  # defaults to textual-dark
export PAPERCLI_REMOTE_PATH=/path/to/remote  # OneDrive sync path
export PAPERCLI_AUTO_SYNC=true  # defaults to false
export PAPERCLI_AUTO_SYNC_INTERVAL=5  # defaults to 5 seconds
```

### Method 2: .env File
Create a `.env` file in your current directory or data directory (`~/.papercli/`):

```env
# OpenAI API key (required for local chat interface and summarization)
OPENAI_API_KEY=your_openai_api_key_here

# OpenAI model for chat and summarization (optional, defaults to gpt-4o)
OPENAI_MODEL=gpt-4o

# OpenAI API settings (optional)
OPENAI_MAX_TOKENS=4000
OPENAI_TEMPERATURE=0.7

# Data directory for database and PDFs (optional, defaults to ~/.papercli)
PAPERCLI_DATA_DIR=/path/to/your/papercli/data

# PDF pages limit for chat and summarization (optional, defaults to 10)
PAPERCLI_PDF_PAGES=10

# UI theme (optional, defaults to textual-dark)
PAPERCLI_THEME=textual-dark

# OneDrive sync settings (optional)
PAPERCLI_REMOTE_PATH=/path/to/onedrive/folder
PAPERCLI_AUTO_SYNC=false
PAPERCLI_AUTO_SYNC_INTERVAL=5
```

### Data Storage
PaperCLI stores all data in a single directory (default: `~/.papercli/`):
- `papers.db` - SQLite database with paper metadata
- `pdfs/` - Downloaded PDF files
- `version_config.json` - Version update settings

The application will check for `.env` files in this order:
1. Current working directory
2. Data directory (`~/.papercli/` or `$PAPERCLI_DATA_DIR`)

## Database Schema

PaperCLI uses a SQLite database with the following main entities:
- **Papers**: Title, abstract, venue, year, authors, collections, PDF path, notes
- **Authors**: Name, email, affiliation with ordered relationships
- **Collections**: Custom paper groupings
- **Metadata**: DOI, preprint IDs, URLs, paper types

## Keyboard Shortcuts

### Navigation & General
- **↑/↓** - Navigate the paper list or scroll panels
- **PageUp/PageDown** - Scroll panels by a full page
- **Space** - Toggle selection for a paper (only in `/select` mode)
- **Enter** - Execute a command from the input bar
- **ESC** - Close panels
- **Ctrl+C** - Clear input or exit application
- **Tab** - Trigger and cycle through auto-completions

### Function Keys (Quick Actions)
- **F1** - Add paper dialog
- **F2** - Open paper PDF  
- **F3** - Show paper details
- **F4** - Chat with AI about paper
- **F5** - Edit paper metadata
- **F6** - Delete paper
- **F7** - Manage collections
- **F8** - Filter papers
- **F9** - Show all papers
- **F10** - Sort papers
- **F11** - Toggle selection mode
- **F12** - Clear selection

### Chat Interface Shortcuts
When using the local chat interface (`/chat`):
- **Enter** - Send message
- **↑/↓** - Scroll chat display
- **PageUp/PageDown** - Scroll chat display by page
- **Ctrl+S** - Save chat to file
- **Esc** - Close chat interface

## Troubleshooting

### Common Issues

1. **PDF Download Failures**:
   ```
   /doctor
   ```

2. **Database Issues**:
   ```
   /doctor clean
   ```

3. **Missing Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Logs and Debugging
- Check `/log` panel for recent errors
- Use `/doctor` for system health checks
- Log files are stored in `~/.papercli/logs/`

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Commit your changes: `git commit -m "feat: add new feature"`
5. Push to the branch: `git push origin feature-name`
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

- **Issues**: Report bugs and request features on [GitHub Issues](https://github.com/SXKDZ/papercli/issues)
- **Documentation**: Run `/help` within the application
- **Discussions**: Join discussions on [GitHub Discussions](https://github.com/SXKDZ/papercli/discussions)

---

**PaperCLI** - Streamline your research workflow with powerful command-line paper management.
