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
  - Automatic PDF content inclusion (first 10 pages) for comprehensive context
  - Auto-summarization for papers without notes
  - Input history navigation and keyboard shortcuts
- **Browser Chat Integration**: Quick access to Claude, ChatGPT, or Gemini web interfaces
- **Enhanced Metadata**: AI-powered metadata extraction and improvement

### 📊 Export & Integration
- **Multiple Export Formats**: Export to BibTeX, Markdown, HTML, and JSON
- **Clipboard Support**: Copy paper data directly to clipboard
- **PDF Management**: Automatic PDF downloading and organization

### 🔧 Advanced Features
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
python -m app.papercli
```

## Quick Start

1. **Launch PaperCLI**:
   ```bash
   # If installed via pipx or pip
   papercli
   
   # Or if running from source
   python -m app.papercli
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
- `/add` - Open add dialog or add paper directly (e.g., `/add arxiv 2307.10635`)
- `/filter` - Filter papers by criteria or search all fields (e.g., `/filter all keyword`)
- `/sort` - Open sort dialog or sort directly (e.g., `/sort title asc`)
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
- `/edit` - Open edit dialog or edit field directly (e.g., `/edit title ...`)
- `/open` - Open the PDF for the paper(s)
- `/detail` - Show detailed metadata for the paper(s)
- `/export` - Export paper(s) to a file or clipboard (BibTeX, Markdown, etc.)
- `/delete` - Delete the paper(s) from the library

### Collection Management
- `/collect` - Manage collections
- `/collect purge` - Delete all empty collections
- `/add-to` - Add selected paper(s) to a collection
- `/remove-from` - Remove selected paper(s) from a collection

### System Commands
- `/doctor` - Diagnose and fix database/system issues
  - `diagnose` - Run full diagnostic check (default)
  - `clean` - Clean orphaned database records and PDF files
  - `help` - Show doctor command help

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
export PAPERCLI_DATA_DIR=/path/to/data  # defaults to ~/.papercli
```

### Method 2: .env File
Create a `.env` file in your current directory or data directory (`~/.papercli/`):

```env
# OpenAI API key (required for local chat interface and summarization)
OPENAI_API_KEY=your_openai_api_key_here

# OpenAI model for chat and summarization (optional, defaults to gpt-4o)
OPENAI_MODEL=gpt-4o

# Data directory for database and PDFs (optional, defaults to ~/.papercli)
PAPERCLI_DATA_DIR=/path/to/your/papercli/data
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
- **ESC** - Close panels, exit selection mode, or clear input
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
- **Ctrl+J** - Insert newline in message
- **↑/↓** - Navigate input history (when focused on input)
- **↑/↓** - Scroll chat display (when focused on chat)
- **PageUp/PageDown** - Scroll chat display by page
- **Ctrl+S** - Send message (alternative)
- **Esc** - Close chat interface

## Troubleshooting

### Common Issues

1. **PDF Download Failures**:
   ```
   /doctor diagnose
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
- Use `/doctor diagnose` for system health checks
- Log files are stored in `~/.papercli/logs/`

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and add tests
4. Commit your changes: `git commit -m "feat: add new feature"`
5. Push to the branch: `git push origin feature-name`
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

- **Issues**: Report bugs and request features on [GitHub Issues](https://github.com/SXKDZ/papercli/issues)
- **Documentation**: Run `/help` within the application
- **Discussions**: Join discussions on [GitHub Discussions](https://github.com/SXKDZ/papercli/discussions)

## Roadmap

- [x] Package distribution via pipx and pip
- [x] Version management and auto-updates
- [ ] Package distribution via PyPI
- [ ] Plugin system for custom metadata extractors
- [ ] Cloud synchronization support
- [ ] Advanced citation analysis
- [ ] Integration with reference managers

---

**PaperCLI** - Streamline your research workflow with powerful command-line paper management.