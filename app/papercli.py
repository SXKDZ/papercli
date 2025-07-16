#!/usr/bin/env python3
"""
PaperCLI - A command-line paper management system
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .cli import PaperCLI
from .database import init_database
from .version import get_version


def setup_environment():
    """Set up environment variables and data directory."""
    # Get data directory from environment or use default
    data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
    if data_dir_env:
        data_dir = Path(data_dir_env).expanduser().resolve()
    else:
        data_dir = Path.home() / ".papercli"

    # Ensure data directory exists
    data_dir.mkdir(exist_ok=True, parents=True)

    # Skip OpenAI setup if API key is already set via environment
    if os.getenv("OPENAI_API_KEY"):
        return data_dir

    # Try to load from .env files in order of preference
    env_locations = [Path.cwd() / ".env", data_dir / ".env"]

    for env_file in env_locations:
        if env_file.exists():
            load_dotenv(env_file)
            break

    # If still no API key, prompt user
    if not os.getenv("OPENAI_API_KEY"):
        current_dir = Path.cwd()
        print(
            f"""
🔧 Configuration Setup Required

PaperCLI requires OpenAI API configuration. You can set it up in two ways:

1. Using environment variables:
   export OPENAI_API_KEY=your_openai_api_key_here
   export OPENAI_MODEL=gpt-4o  # optional, defaults to gpt-4o
   export PAPERCLI_DATA_DIR=/path/to/data  # optional, defaults to ~/.papercli

2. Using a .env file in either location:
   - Current directory: {current_dir}
   - Data directory: {data_dir}

You can get an API key from: https://platform.openai.com/api-keys
"""
        )

        try:
            response = input(
                "Would you like to continue without OpenAI configuration? (y/N): "
            )
            if response.lower() not in ["y", "yes"]:
                print("Please set up OpenAI configuration and run papercli again.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)

    return data_dir


def main():
    """Main entry point for PaperCLI."""
    # Handle command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--version", "-v"]:
            print(f"PaperCLI v{get_version()}")
            sys.exit(0)
        elif sys.argv[1] in ["--help", "-h"]:
            print(
                f"""
PaperCLI v{get_version()}
A command-line paper management system for researchers and academics

Usage:
  papercli                Start the interactive CLI
  papercli --version      Show version information
  papercli --help         Show this help message

For more information, visit: https://github.com/SXKDZ/papercli
            """.strip()
            )
            sys.exit(0)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use 'papercli --help' for usage information.")
            sys.exit(1)

    # Set up environment variables and data directory
    data_dir = setup_environment()

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
