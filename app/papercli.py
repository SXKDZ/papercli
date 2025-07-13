#!/usr/bin/env python3
"""
PaperCLI - A command-line paper management system
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

from .cli import PaperCLI
from .database import init_database
from .version import get_version


def main():
    """Main entry point for PaperCLI."""
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ['--version', '-v']:
            print(f"PaperCLI v{get_version()}")
            sys.exit(0)
        elif sys.argv[1] in ['--help', '-h']:
            print(f"""
PaperCLI v{get_version()}
A command-line paper management system for researchers and academics

Usage:
  papercli                Start the interactive CLI
  papercli --version      Show version information
  papercli --help         Show this help message

For more information, visit: https://github.com/SXKDZ/papercli
            """.strip())
            sys.exit(0)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use 'papercli --help' for usage information.")
            sys.exit(1)
    
    load_dotenv()
    
    # Get data directory from environment or use default
    data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
    if data_dir_env:
        data_dir = Path(data_dir_env).expanduser().resolve()
    else:
        data_dir = Path.home() / ".papercli"
    
    # Ensure data directory exists
    data_dir.mkdir(exist_ok=True, parents=True)
    
    # Initialize database
    db_path = data_dir / "papers.db"
    init_database(str(db_path))
    
    # Start the CLI application
    app = PaperCLI(str(db_path))
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()