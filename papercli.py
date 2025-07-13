#!/usr/bin/env python3
"""
PaperCLI - A command-line paper management system
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

from app.cli import PaperCLI
from app.database import init_database


def main():
    """Main entry point for PaperCLI."""
    load_dotenv()
    
    # Ensure data directory exists
    data_dir = Path.home() / ".papercli"
    data_dir.mkdir(exist_ok=True)
    
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