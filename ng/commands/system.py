from __future__ import annotations
import os
import traceback
from pathlib import Path
from typing import List, TYPE_CHECKING

import requests
from openai import OpenAI

from ng.commands.base import CommandHandler
from ng.version import VersionManager # Reusing existing VersionManager
from ng.dialogs.message_dialog import MessageDialog # Import the new MessageDialog
from ng.dialogs.doctor_dialog import DoctorDialog # Import the new DoctorDialog
from ng.services.database import DatabaseHealthService # Import the new DatabaseHealthService
from ng.services.sync import SyncService # Import the sync service
from ng.screens.log_screen import LogScreen # Import the new LogScreen

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp

class SystemCommandHandler(CommandHandler):
    """Handler for system commands like log, doctor, version, exit."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.version_manager = VersionManager()
        self.db_health_service = DatabaseHealthService(db_path=self.app.db_path) # Initialize with db_path

    def handle_log_command(self):
        """Handle /log command - toggle log panel."""
        if hasattr(self.app.screen, 'action_toggle_log'):
            self.app.screen.action_toggle_log()
        else:
            self.app.screen.query_one("#status-bar").set_error("Log panel not available on this screen")

    def handle_doctor_command(self, args: List[str]):
        """Handle /doctor command for database diagnostics and cleanup."""
        try:
            action = args[0] if args else None

            if not args:
                self.app.screen.query_one("#status-bar").set_status(
                    "Running diagnostic checks...", "diagnose"
                )
                report = self.db_health_service.run_full_diagnostic()
                self._show_doctor_report(report)

            elif action == "clean":
                self.app.screen.query_one("#status-bar").set_status(
                    "Cleaning orphaned records, files, and PDF filenames...", "clean"
                )
                cleaned_records = self.db_health_service.clean_orphaned_records()
                cleaned_pdfs = self.db_health_service.clean_orphaned_pdfs()
                fixed_paths = self.db_health_service.fix_absolute_pdf_paths()
                renamed_files = self.db_health_service.clean_pdf_filenames()

                total_cleaned_records = sum(cleaned_records.values())
                total_cleaned_pdfs = sum(cleaned_pdfs.values())
                total_fixed_paths = sum(fixed_paths.values())
                total_renamed = sum(renamed_files.values())

                if (
                    total_cleaned_records > 0
                    or total_cleaned_pdfs > 0
                    or total_fixed_paths > 0
                    or total_renamed > 0
                ):
                    details = []
                    if total_cleaned_records > 0:
                        details.append(f"Records: {total_cleaned_records}")
                    if total_cleaned_pdfs > 0:
                        details.append(f"PDF files: {total_cleaned_pdfs}")
                    if total_fixed_paths > 0:
                        details.append(f"PDF paths: {total_fixed_paths}")
                    if total_renamed > 0:
                        details.append(f"Renamed files: {total_renamed}")

                    cleanup_summary = []
                    if total_cleaned_records > 0:
                        cleanup_summary.append(f"{total_cleaned_records} records")
                    if total_cleaned_pdfs > 0:
                        cleanup_summary.append(f"{total_cleaned_pdfs} PDFs")
                    if total_fixed_paths > 0:
                        cleanup_summary.append(f"{total_fixed_paths} paths")
                    if total_renamed > 0:
                        cleanup_summary.append(f"{total_renamed} filenames")

                    if cleanup_summary:
                        self.app.screen.query_one("#status-bar").set_success(
                            f"Database cleanup complete - fixed {' and '.join(cleanup_summary)}"
                        )
                    else:
                        self.app.screen.query_one("#status-bar").set_success("Database cleanup complete")
                else:
                    self.app.screen.query_one("#status-bar").set_success(
                        "No issues found - database is clean"
                    )

            elif action == "help":
                help_text = """Database Doctor Commands:

/doctor                 - Run full diagnostic check
/doctor clean           - Clean orphaned records, files, and rename PDFs to follow naming convention
/doctor help            - Show this help

The doctor command helps maintain database health by:
• Checking database integrity and structure
• Detecting orphaned association records and PDF files
• Identifying papers with absolute PDF paths (should be relative)
• Verifying system dependencies  
• Checking terminal capabilities
• Providing automated cleanup
• Ensuring PDF filenames follow consistent naming rules

PDF Filename Convention:
• Format: {author_lastname}{year}{first_word}_{hash}.pdf
• Example: smith2023learning_a1b2c3.pdf
• Uses first author's last name, publication year, first significant word from title
• Includes 6-character hash from PDF content for uniqueness"""

                self.app.push_screen(MessageDialog("Database Doctor Help", help_text))

            else:
                self.app.screen.query_one("#status-bar").set_error(
                    f"Unknown doctor action: {action}. Use 'diagnose', 'clean', or 'help'"
                )

        except Exception as e:
            self.app.screen.query_one("#status-bar").set_error(
                f"Failed to run doctor command: {str(e)}"
            )

    def _show_doctor_report(self, report: dict):
        """Display the doctor diagnostic report."""
        # Create formatted report text
        lines = [
            f"Database Doctor Report - {report['timestamp'][:19]}",
            "=" * 60,
            "",
            "📊 DATABASE HEALTH:",
        ]

        db_checks = report["database_checks"]
        lines.extend(
            [
                f"  Database exists: {'✓' if db_checks['database_exists'] else '✗'}",
                f"  Tables exist: {'✓' if db_checks['tables_exist'] else '✗'}",
                f"  Database size: {db_checks.get('database_size', 0) // 1024} KB",
                f"  Foreign key constraints: {'✓' if db_checks['foreign_key_constraints'] else '✗'}",
            ]
        )

        if db_checks.get("table_counts"):
            lines.append("  Table counts:")
            for table, count in db_checks["table_counts"].items():
                lines.append(f"    {table}: {count}")

        lines.extend(["", "🔗 ORPHANED RECORDS:"])
        orphaned_records = report["orphaned_records"]["summary"]
        pc_count = orphaned_records.get("orphaned_paper_collections", 0)
        pa_count = orphaned_records.get("orphaned_paper_authors", 0)
        lines.extend(
            [
                f"  Paper-collection associations: {pc_count}",
                f"  Paper-author associations: {pa_count}",
            ]
        )

        orphaned_pdfs = report.get("orphaned_pdfs", {}).get("summary", {})
        pdf_count = orphaned_pdfs.get("orphaned_pdf_files", 0)
        if pdf_count > 0:
            lines.append(f"  Orphaned PDF files: {pdf_count}")

        absolute_paths = report.get("absolute_pdf_paths", {}).get("summary", {})
        absolute_count = absolute_paths.get("absolute_path_count", 0)
        if absolute_count > 0:
            lines.append(f"  Papers with absolute PDF paths: {absolute_count}")

        missing_pdfs = report.get("missing_pdfs", {}).get("summary", {})
        missing_count = missing_pdfs.get("missing_pdf_count", 0)
        if missing_count > 0:
            lines.append(f"  Papers with missing PDF files: {missing_count}")

        lines.extend(["", "💻 SYSTEM HEALTH:"])
        sys_checks = report["system_checks"]
        lines.append(f"  Python version: {sys_checks['python_version']}")
        lines.append("  Dependencies:")
        for dep, status in sys_checks["dependencies"].items():
            lines.append(f"    {dep}: {status}")

        if "disk_space" in sys_checks and "free_mb" in sys_checks["disk_space"]:
            lines.append(f"  Free disk space: {sys_checks['disk_space']['free_mb']} MB")

        lines.extend(["", "🖥️ TERMINAL SETUP:"])
        term_checks = report["terminal_checks"]
        lines.extend(
            [
                f"  Terminal type: {term_checks['terminal_type']}",
                f"  Unicode support: {'✓' if term_checks['unicode_support'] else '✗'}",
                f"  Color support: {'✓' if term_checks['color_support'] else '✗'}",
            ]
        )

        if "terminal_size" in term_checks and "columns" in term_checks["terminal_size"]:
            size = term_checks["terminal_size"]
            lines.append(f"  Terminal size: {size['columns']}x{size['lines']}")

        # Issues and recommendations
        if report["issues_found"]:
            lines.extend(["", "⚠ ISSUES FOUND:"])
            for issue in report["issues_found"]:
                lines.append(f"  • {issue}")

        if report["recommendations"]:
            lines.extend(["", "💡 RECOMMENDATIONS:"])
            for rec in report["recommendations"]:
                lines.append(f"  • {rec}")

        if pc_count > 0 or pa_count > 0 or absolute_count > 0 or pdf_count > 0:
            lines.extend(["", "🧹 To clean issues, run: /doctor clean"])

        report_text = "\n".join(lines)

        self.app.push_screen(DoctorDialog(report_text))

    def handle_exit_command(self):
        """Handle /exit command - exit the application."""
        self.app.exit()

    def handle_version_command(self, args: List[str]):
        """Handle /version command for version management."""
        status_bar = self.app.screen.query_one("#status-bar")

        if not args:
            # Show basic version info
            current_version = self.version_manager.get_current_version()
            install_method = self.version_manager.get_installation_method()

            version_info = f"PaperCLI v{current_version}\n"
            version_info += f"Installation: {install_method}\n"

            # Check for updates in background
            try:
                update_available, latest_version = self.version_manager.is_update_available()
                if update_available:
                    version_info += f"Update available: v{latest_version}\n"
                    version_info += f"Run '/version update' to upgrade"
                else:
                    version_info += "You're running the latest version"
            except Exception:
                version_info += "Could not check for updates"

            self.app.push_screen(MessageDialog("Version Information", version_info))
            return

        action = args[0].lower()

        if action == "check":
            status_bar.set_status("Checking for updates...")
            try:
                update_available, latest_version = self.version_manager.is_update_available()
                current_version = self.version_manager.get_current_version()

                if update_available:
                    update_info = f"Update Available!\n\n"
                    update_info += f"Current version: v{current_version}\n"
                    update_info += f"Latest version:  v{latest_version}\n\n"

                    if self.version_manager.can_auto_update():
                        update_info += "To update, run: /version update\n\n"
                    else:
                        update_info += f"To update manually, run:\n"
                        update_info += (
                            f"{self.version_manager.get_update_instructions()}\n\n"
                        )

                    # Get release notes from GitHub
                    try:
                        url = f"https://api.github.com/repos/{self.version_manager.github_repo}/releases/latest"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            release_data = response.json()
                            if release_data.get("body"):
                                update_info += f"Release Notes:\n{release_data['body']}"
                    except Exception:
                        pass

                    self.app.push_screen(MessageDialog("Update Available", update_info))
                else:
                    status_bar.set_success(
                        f"You're running the latest version (v{current_version})"
                    )
            except Exception as e:
                status_bar.set_error(f"Could not check for updates: {e}")

        elif action == "update":
            if not self.version_manager.can_auto_update():
                install_method = self.version_manager.get_installation_method()
                status_bar.set_error(
                    f"Auto-update not supported for {install_method} installations"
                )

                manual_info = f"Manual Update Required\n\n"
                manual_info += f"Installation method: {install_method}\n\n"
                manual_info += f"To update manually, run:\n"
                manual_info += f"{self.version_manager.get_update_instructions()}"

                self.app.push_screen(MessageDialog("Manual Update Required", manual_info))
                return

            # Check if update is available first
            try:
                update_available, latest_version = self.version_manager.is_update_available()
                if not update_available:
                    current_version = self.version_manager.get_current_version()
                    status_bar.set_success(
                        f"Already running latest version (v{current_version})"
                    )
                    return

                status_bar.set_status(f"Updating to v{latest_version}...")

                # Perform the update
                if self.version_manager.perform_update():
                    status_bar.set_success(
                        "Update successful! Please restart PaperCLI."
                    )
                    # Show restart dialog
                    restart_info = f"Update Successful!\n\n"
                    restart_info += (
                        f"PaperCLI has been updated to v{latest_version}.\n\n"
                    )
                    restart_info += (
                        f"Please restart the application to use the new version.\n\n"
                    )
                    restart_info += f"Press ESC to close this dialog and exit."

                    self.app.push_screen(MessageDialog("Restart Required", restart_info))
                else:
                    status_bar.set_error(
                        "Update failed. Please update manually."
                    )

            except Exception as e:
                status_bar.set_error(f"Update failed: {e}")

        elif action == "info":
            current_version = self.version_manager.get_current_version()
            install_method = self.version_manager.get_installation_method()
            config = self.version_manager.get_update_config()

            info = f"PaperCLI Version Information\n"
            info += f"=" * 30 + "\n\n"
            info += f"Version: v{current_version}\n"
            info += f"Installation: {install_method}\n"
            info += f"GitHub Repository: {self.version_manager.github_repo}\n\n"

            info += f"Update Settings:\n"
            info += (
                f"- Auto-check: {'Yes' if config.get('auto_check', True) else 'No'}\n"
            )
            info += f"- Check interval: {config.get('check_interval_days', 7)} days\n"
            info += f"- Auto-update: {'Yes' if config.get('auto_update', False) else 'No'}\n"
            info += f"- Can auto-update: {'Yes' if self.version_manager.can_auto_update() else 'No'}\n"

            if config.get("last_check"):
                info += f"- Last check: {config['last_check'][:19]}\n"
            else:
                info += f"- Last check: Never\n"

            info += f"\nTo check for updates: /version check\n"
            if self.version_manager.can_auto_update():
                info += f"To update: /version update\n"
            else:
                info += f"To update manually:\n{self.version_manager.get_update_instructions()}\n"

            self.app.push_screen(MessageDialog("Version Information", info))

        else:
            status_bar.set_error(f"Unknown version command: {action}")
            status_bar.set_status("Usage: /version [check|update|info]")

    def handle_config_command(self, args: List[str]):
        """Handle /config command for configuration management."""
        status_bar = self.app.screen.query_one("#status-bar")
        if not args:
            self._show_config_help()
            return

        action = args[0].lower()

        if action == "model":
            if len(args) < 2:
                self._show_current_model()
            else:
                model_name = args[1]
                self._set_model(model_name)

        elif action == "openai_api_key":
            if len(args) < 2:
                self._show_current_api_key()
            else:
                api_key = args[1]
                self._set_api_key(api_key)

        elif action == "remote":
            if len(args) < 2:
                self._show_current_remote_path()
            else:
                remote_path = args[1]
                self._set_remote_path(remote_path)

        elif action == "auto-sync":
            if len(args) < 2:
                self._show_current_auto_sync()
            else:
                setting = args[1].lower()
                if setting in ["enable", "on", "true"]:
                    self._set_auto_sync(True)
                elif setting in ["disable", "off", "false"]:
                    self._set_auto_sync(False)
                else:
                    status_bar.set_error(
                        "Use 'enable' or 'disable' for auto-sync"
                    )

        elif action == "pdf-pages":
            if len(args) < 2:
                self._show_current_pdf_pages()
            else:
                try:
                    pages = int(args[1])
                    if pages > 0:
                        self._set_pdf_pages(pages)
                    else:
                        status_bar.set_error(
                            "PDF pages must be a positive number"
                        )
                except ValueError:
                    status_bar.set_error(
                        "PDF pages must be a valid number"
                    )

        elif action == "show":
            self._show_all_config()

        elif action == "help":
            self._show_config_help()

        else:
            status_bar.set_error(f"Unknown config option: {action}")
            self._show_config_help()

    def _show_config_help(self):
        """Show configuration help."""
        # Get available models dynamically
        available_models_text = self._get_available_models_text()

        help_text = f"""Configuration Commands:

Available Commands:
-------------------
/config show                    - Show all current configuration
/config model                   - Show current OpenAI model
/config model <model_name>      - Set OpenAI model (e.g., gpt-4o, gpt-3.5-turbo)
/config openai_api_key          - Show current API key (masked)
/config openai_api_key <key>    - Set OpenAI API key
/config remote                  - Show current remote sync path
/config remote <path>           - Set remote sync path (e.g., ~/OneDrive/papercli-sync)
/config auto-sync               - Show current auto-sync setting
/config auto-sync enable        - Enable auto-sync after edits
/config auto-sync disable       - Disable auto-sync
/config pdf-pages               - Show current PDF pages limit for chat/summarize
/config pdf-pages <number>      - Set PDF pages limit (e.g., 15, 20)

{available_models_text}

Examples:
---------
/config show                    - View all current settings
/config model gpt-4o            - Set model to GPT-4 Omni
/config model gpt-3.5-turbo     - Set model to GPT-3.5 Turbo
/config openai_api_key sk-...   - Set your OpenAI API key
/config remote ~/OneDrive/papercli-sync  - Set OneDrive sync path
/config auto-sync enable        - Enable automatic sync after edits
/config pdf-pages 15            - Set PDF pages limit to 15 for chat/summarize

Configuration Storage:
----------------------
Settings are stored in environment variables and automatically saved to a .env file.
The .env file is searched in this order:
1. Current directory (.env)
2. PAPERCLI_DATA_DIR if set
3. ~/.papercli/.env (default)

API Key Security:
-----------------
API keys are masked when displayed for security.
Only the first 8 and last 4 characters are shown."""

        self.app.push_screen(MessageDialog("Configuration Help", help_text))

    def _get_available_models_text(self):
        """Get formatted text of available OpenAI models."""
        try:
            # Check if API key is available
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return """Available OpenAI Models:
------------------------
(Set OPENAI_API_KEY to query live model list)

Common Models:
gpt-4o                          - Latest GPT-4 Omni model (recommended)
gpt-4o-mini                     - Faster, smaller GPT-4 Omni model  
gpt-4-turbo                     - GPT-4 Turbo model
gpt-4                           - Standard GPT-4 model
gpt-3.5-turbo                   - GPT-3.5 Turbo model (faster, cheaper)"""

            # Query OpenAI for available models
            client = OpenAI(api_key=api_key)
            models_response = client.models.list()

            # Filter for chat models and sort by ID
            chat_models = []
            for model in models_response.data:
                model_id = model.id
                # Filter for common chat models
                if any(prefix in model_id for prefix in ["gpt-4", "gpt-3.5"]):
                    chat_models.append(model_id)

            chat_models.sort()

            if not chat_models:
                return """Available OpenAI Models:
------------------------
(No chat models found in API response)

Common Models:
gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4, gpt-3.5-turbo"""

            # Format the models list
            models_text = "Available OpenAI Models:\n"
            models_text += "------------------------\n"

            # Add descriptions for known models
            model_descriptions = {
                "gpt-4o": "Latest GPT-4 Omni model (recommended)",
                "gpt-4o-mini": "Faster, smaller GPT-4 Omni model",
                "gpt-4-turbo": "GPT-4 Turbo model",
                "gpt-4": "Standard GPT-4 model",
                "gpt-3.5-turbo": "GPT-3.5 Turbo model (faster, cheaper)",
            }

            for model in chat_models:
                description = model_descriptions.get(model, "OpenAI chat model")
                models_text += f"{model:<30} - {description}\n"

            return models_text.rstrip()

        except Exception as e:
            # Fallback to static list if API query fails
            error_msg = str(e)
            return f"""Available OpenAI Models:
------------------------
(API query failed: {error_msg})

Common Models:
gpt-4o                          - Latest GPT-4 Omni model (recommended)
gpt-4o-mini                     - Faster, smaller GPT-4 Omni model
gpt-4-turbo                     - GPT-4 Turbo model  
gpt-4                           - Standard GPT-4 model
gpt-3.5-turbo                   - GPT-3.5 Turbo model (faster, cheaper)"""

    def _get_env_file_path(self):
        """Get the path to the .env file."""
        # Try current directory first, then home directory
        current_dir_env = Path.cwd() / ".env"
        if current_dir_env.exists():
            return current_dir_env

        # Check in PAPERCLI_DATA_DIR if set
        data_dir_env = os.getenv("PAPERCLI_DATA_DIR")
        if data_dir_env:
            data_dir = Path(data_dir_env).expanduser().resolve()
            data_env = data_dir / ".env"
            if data_env.exists():
                return data_env

        # Default to ~/.papercli/.env
        home_env = Path.home() / ".papercli" / ".env"
        return home_env

    def _read_env_file(self):
        """Read the .env file and return a dict of key-value pairs."""
        env_file = self._get_env_file_path()
        env_vars = {}

        if env_file.exists():
            try:
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            # Remove quotes if present
                            value = value.strip("\"'")
                            env_vars[key.strip()] = value
            except Exception as e:
                self.app.screen.query_one("#status-bar").set_error(f"Error reading .env file: {e}")

        return env_vars

    def _write_env_file(self, env_vars):
        """Write environment variables to .env file."""
        env_file = self._get_env_file_path()

        try:
            # Create parent directory if it doesn't exist
            env_file.parent.mkdir(parents=True, exist_ok=True)

            with open(env_file, "w") as f:
                f.write("# PaperCLI Configuration\n")
                for key, value in sorted(env_vars.items()):
                    f.write(f"{key}={value}\n")

            return True
        except Exception as e:
            self.app.screen.query_one("#status-bar").set_error(f"Error writing .env file: {e}")
            return False

    def _show_current_model(self):
        """Show the current OpenAI model."""
        current_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        try:
            self.app.query_one("#status-bar").set_status(f"Current OpenAI model: {current_model}")
        except:
            pass

    def _set_model(self, model_name):
        """Set the OpenAI model."""
        # Update environment variable
        os.environ["OPENAI_MODEL"] = model_name

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_MODEL"] = model_name

        if self._write_env_file(env_vars):
            self.app.screen.query_one("#status-bar").set_success(f"OpenAI model set to: {model_name}")
            # self._add_log("config_model", f"OpenAI model changed to: {model_name}") # Need to implement logging
        else:
            self.app.screen.query_one("#status-bar").set_error("Failed to save model setting to .env file")

    def _show_current_api_key(self):
        """Show the current API key (masked)."""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            masked_key = (
                api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
                if len(api_key) > 12
                else "****"
            )
            self.app.screen.query_one("#status-bar").set_status(f"Current OpenAI API key: {masked_key}")
        else:
            self.app.screen.query_one("#status-bar").set_status("No OpenAI API key set")

    def _set_api_key(self, api_key):
        """Set the OpenAI API key."""
        # Basic validation
        if not api_key.startswith("sk-"):
            self.app.screen.query_one("#status-bar").set_error(
                "Invalid API key format. OpenAI keys should start with 'sk-'"
            )
            return

        # Update environment variable
        os.environ["OPENAI_API_KEY"] = api_key

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_API_KEY"] = api_key

        if self._write_env_file(env_vars):
            masked_key = (
                api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
                if len(api_key) > 12
                else "****"
            )
            self.app.screen.query_one("#status-bar").set_success(f"OpenAI API key set: {masked_key}")
            # self._add_log("config_api_key", f"OpenAI API key updated: {masked_key}") # Need to implement logging
        else:
            self.app.screen.query_one("#status-bar").set_error("Failed to save API key to .env file")

    def _show_current_remote_path(self):
        """Show the current remote sync path."""
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "")
        if remote_path:
            self.app.screen.query_one("#status-bar").set_status(f"Current remote sync path: {remote_path}")
        else:
            self.app.screen.query_one("#status-bar").set_status("No remote sync path set")

    def _set_remote_path(self, remote_path):
        """Set the remote sync path."""
        # Expand user path
        expanded_path = os.path.expanduser(remote_path)

        # Update environment variable
        os.environ["PAPERCLI_REMOTE_PATH"] = expanded_path

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_REMOTE_PATH"] = expanded_path

        if self._write_env_file(env_vars):
            self.app.screen.query_one("#status-bar").set_success(f"Remote sync path set to: {expanded_path}")
            # self._add_log("config_remote", f"Remote sync path changed to: {expanded_path}") # Need to implement logging
        else:
            self.app.screen.query_one("#status-bar").set_error("Failed to save remote path to .env file")

    def _show_current_auto_sync(self):
        """Show the current auto-sync setting."""
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
        status = "enabled" if auto_sync else "disabled"
        self.app.query_one("#status-bar").set_status(f"Auto-sync is currently: {status}")

    def _set_auto_sync(self, enabled):
        """Set the auto-sync setting."""
        value = "true" if enabled else "false"

        # Update environment variable
        os.environ["PAPERCLI_AUTO_SYNC"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_AUTO_SYNC"] = value

        if self._write_env_file(env_vars):
            status = "enabled" if enabled else "disabled"
            self.app.screen.query_one("#status-bar").set_success(f"Auto-sync {status}")
            # self._add_log("config_auto_sync", f"Auto-sync {status}") # Need to implement logging
        else:
            self.app.screen.query_one("#status-bar").set_error(
                "Failed to save auto-sync setting to .env file"
            )

    def _show_current_pdf_pages(self):
        """Show the current PDF pages limit."""
        pdf_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
        self.app.query_one("#status-bar").set_status(f"Current PDF pages limit: {pdf_pages}")

    def _set_pdf_pages(self, pages):
        """Set the PDF pages limit."""
        value = str(pages)

        # Update environment variable
        os.environ["PAPERCLI_PDF_PAGES"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_PDF_PAGES"] = value

        if self._write_env_file(env_vars):
            self.app.screen.query_one("#status-bar").set_success(f"PDF pages limit set to: {pages}")
            # self._add_log("config_pdf_pages", f"PDF pages limit set to: {pages}") # Need to implement logging
        else:
            self.app.screen.query_one("#status-bar").set_error("Failed to save PDF pages setting to .env file")

    def _show_all_config(self):
        """Show all current configuration."""
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        api_key = os.getenv("OPENAI_API_KEY", "")
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "Not set")
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
        pdf_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))

        if api_key:
            masked_key = (
                api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
                if len(api_key) > 12
                else "****"
            )
        else:
            masked_key = "Not set"

        auto_sync_status = "enabled" if auto_sync else "disabled"
        env_file = self._get_env_file_path()

        config_text = f"""Current Configuration:

OpenAI Model: {model}
OpenAI API Key: {masked_key}
Remote Sync Path: {remote_path}
Auto-sync: {auto_sync_status}
PDF Pages Limit: {pdf_pages}

Configuration file: {env_file}
File exists: {'Yes' if env_file.exists() else 'No'}

To change settings:
/config model <model_name>
/config openai_api_key <key>
/config remote <path>
/config auto-sync enable|disable
/config pdf-pages <number>"""

        self.app.push_screen(MessageDialog("Current Configuration", config_text))

    def handle_sync_command(self, args: List[str]):
        """Handle /sync command for synchronizing with remote storage."""
        try:
            # Get data directory path 
            local_data_dir = Path(self.app.db_path).parent
            
            # Default remote path - typically OneDrive or cloud storage
            remote_data_dir = None
            if args:
                remote_data_dir = Path(args[0])
            else:
                # Try to find OneDrive directory
                home = Path.home()
                possible_paths = [
                    home / "OneDrive" / "PaperCLI",
                    home / "OneDrive - Personal" / "PaperCLI", 
                    home / "Dropbox" / "PaperCLI",
                    home / "Google Drive" / "PaperCLI"
                ]
                for path in possible_paths:
                    if path.exists():
                        remote_data_dir = path
                        break
                        
            if not remote_data_dir:
                try:
                    self.app.query_one("#status-bar").set_error("No remote path specified. Use: /sync <remote_path>")
                except:
                    pass
                return
                
            # Create sync service
            def progress_callback(message):
                try:
                    self.app.query_one("#status-bar").set_status(message)
                except:
                    pass
                    
            def log_callback(action, details):
                self.app._add_log(action, details)
            
            sync_service = SyncService(
                str(local_data_dir),
                str(remote_data_dir),
                progress_callback=progress_callback,
                log_callback=log_callback
            )
            
            try:
                self.app.query_one("#status-bar").set_status("Starting sync...", "info")
            except:
                pass
                
            # Run sync
            result = sync_service.sync()
            
            # Display result
            summary = result.get_summary()
            try:
                if result.has_conflicts():
                    self.app.query_one("#status-bar").set_warning(summary)
                elif result.errors:
                    self.app.query_one("#status-bar").set_error(f"Sync failed: {result.errors[0]}")
                else:
                    self.app.query_one("#status-bar").set_success(summary)
                    # Refresh papers after sync
                    self.app.load_papers()
            except:
                pass
            
        except Exception as e:
            try:
                self.app.query_one("#status-bar").set_error(f"Sync error: {str(e)}")
            except:
                pass

    def _run_sync_with_progress(self, local_path, remote_path):
        """Show centered progress dialog using SyncProgressDialog."""
        pass
