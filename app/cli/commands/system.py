"""System commands handler."""

import os
import threading
import traceback
from pathlib import Path
from typing import List

import requests
from openai import OpenAI

from ...services.sync_service import SyncService
from ...version import VersionManager
from .base import BaseCommandHandler


class SystemCommandHandler(BaseCommandHandler):
    """Handler for system commands like log, doctor, version, exit."""

    def handle_log_command(self):
        """Handle /log command."""
        if not self.cli.logs:
            log_content = "No activities logged in this session."
        else:
            # Limit to last 500 entries to prevent scrolling issues
            recent_logs = (
                self.cli.logs[-500:] if len(self.cli.logs) > 500 else self.cli.logs
            )

            log_entries = []
            # Show most recent first
            for log in reversed(recent_logs):
                # Limit each log entry to ~500 characters to keep the log readable
                details = log["details"]
                if len(details) > 500:
                    details = details[:500] + "... [truncated]"

                log_entries.append(
                    f"[{log['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {log['action']}: {details}"
                )

            # Add header if we're showing limited entries
            if len(self.cli.logs) > 500:
                header = (
                    f"Activity Log (showing last 500 of {len(self.cli.logs)} entries)\n"
                    + "=" * 60
                    + "\n\n"
                )
                log_content = header + "\n".join(log_entries)
            else:
                log_content = (
                    f"Activity Log ({len(self.cli.logs)} entries)\n"
                    + "=" * 40
                    + "\n\n"
                    + "\n".join(log_entries)
                )

        self.cli.show_help_dialog(log_content, "Activity Log")
        self.cli.status_bar.set_status(
            "Activity log opened - Press ESC to close", "open"
        )

    def handle_doctor_command(self, args: List[str]):
        """Handle /doctor command for database diagnostics and cleanup."""
        try:
            action = args[0] if args else "diagnose"

            if action == "diagnose":
                self.cli.status_bar.set_status(
                    "Running diagnostic checks...", "diagnose"
                )
                report = self.cli.db_health_service.run_full_diagnostic()
                self._show_doctor_report(report)

            elif action == "clean":
                self.cli.status_bar.set_status(
                    "Cleaning orphaned records and files...", "clean"
                )
                cleaned_records = self.cli.db_health_service.clean_orphaned_records()
                cleaned_pdfs = self.cli.db_health_service.clean_orphaned_pdfs()

                total_cleaned_records = sum(cleaned_records.values())
                total_cleaned_pdfs = sum(cleaned_pdfs.values())

                if total_cleaned_records > 0 or total_cleaned_pdfs > 0:
                    details = []
                    if total_cleaned_records > 0:
                        details.append(f"Records: {total_cleaned_records}")
                    if total_cleaned_pdfs > 0:
                        details.append(f"PDF files: {total_cleaned_pdfs}")

                    # Log detailed cleanup results on one line
                    cleanup_details = " • ".join(details)
                    self._add_log(
                        "database_cleanup",
                        f"Database cleanup completed: {cleanup_details}",
                    )

                    # Show cleanup results in status bar
                    cleanup_summary = []
                    if total_cleaned_records > 0:
                        cleanup_summary.append(f"{total_cleaned_records} records")
                    if total_cleaned_pdfs > 0:
                        cleanup_summary.append(f"{total_cleaned_pdfs} PDFs")

                    if cleanup_summary:
                        self.cli.status_bar.set_success(
                            f"Database cleanup complete - cleaned {' and '.join(cleanup_summary)}"
                        )
                    else:
                        self.cli.status_bar.set_success("Database cleanup complete")
                else:
                    self.cli.status_bar.set_success(
                        "No orphaned items found - database is clean"
                    )

            elif action == "help":
                help_text = """Database Doctor Commands:

/doctor                 - Run full diagnostic check
/doctor diagnose        - Run full diagnostic check  
/doctor clean           - Clean orphaned database records and PDF files
/doctor help            - Show this help

The doctor command helps maintain database health by:
• Checking database integrity and structure
• Detecting orphaned association records and PDF files
• Verifying system dependencies  
• Checking terminal capabilities
• Providing automated cleanup"""

                self.cli.show_help_dialog(help_text, "Database Doctor Help")

            else:
                self.cli.status_bar.set_error(
                    f"Unknown doctor action: {action}. Use 'diagnose', 'clean', or 'help'"
                )

        except Exception as e:
            self.show_error_panel_with_message(
                "PaperCLI Doctor - Error",
                f"Failed to run doctor command: {str(e)}",
                f"Action: {action if 'action' in locals() else 'unknown'}\nError details: {traceback.format_exc()}",
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

        if pc_count > 0 or pa_count > 0:
            lines.extend(["", "🧹 To clean orphaned records, run: /doctor clean"])

        report_text = "\n".join(lines)

        # Show in error panel (reusing for display)
        issues_count = len(report["issues_found"])
        status = (
            "✓ System healthy"
            if issues_count == 0
            else f"⚠ {issues_count} issues found"
        )

        self.cli.show_help_dialog(report_text, "Database Doctor Report")

    def handle_exit_command(self):
        """Handle /exit command - exit the application."""
        self.cli.app.exit()

    def handle_version_command(self, args: List[str]):
        """Handle /version command for version management."""
        version_manager = VersionManager()

        if not args:
            # Show basic version info
            current_version = version_manager.get_current_version()
            install_method = version_manager.get_installation_method()

            version_info = f"PaperCLI v{current_version}\n"
            version_info += f"Installation: {install_method}\n"

            # Check for updates in background
            try:
                update_available, latest_version = version_manager.is_update_available()
                if update_available:
                    version_info += f"Update available: v{latest_version}\n"
                    version_info += f"Run '/version update' to upgrade"
                else:
                    version_info += "You're running the latest version"
            except Exception:
                version_info += "Could not check for updates"

            self.cli.show_help_dialog(version_info, "Version Information")
            return

        action = args[0].lower()

        if action == "check":
            self.cli.status_bar.set_status("Checking for updates...")
            try:
                update_available, latest_version = version_manager.is_update_available()
                current_version = version_manager.get_current_version()

                if update_available:
                    update_info = f"Update Available!\n\n"
                    update_info += f"Current version: v{current_version}\n"
                    update_info += f"Latest version:  v{latest_version}\n\n"

                    if version_manager.can_auto_update():
                        update_info += "To update, run: /version update\n\n"
                    else:
                        update_info += f"To update manually, run:\n"
                        update_info += (
                            f"{version_manager.get_update_instructions()}\n\n"
                        )

                    # Get release notes from GitHub
                    try:
                        url = f"https://api.github.com/repos/{version_manager.github_repo}/releases/latest"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            release_data = response.json()
                            if release_data.get("body"):
                                update_info += f"Release Notes:\n{release_data['body']}"
                    except Exception:
                        pass

                    self.cli.show_help_dialog(update_info, "Update Available")
                else:
                    self.cli.status_bar.set_success(
                        f"You're running the latest version (v{current_version})"
                    )
            except Exception as e:
                self.cli.status_bar.set_error(f"Could not check for updates: {e}")

        elif action == "update":
            if not version_manager.can_auto_update():
                install_method = version_manager.get_installation_method()
                self.cli.status_bar.set_error(
                    f"Auto-update not supported for {install_method} installations"
                )

                manual_info = f"Manual Update Required\n\n"
                manual_info += f"Installation method: {install_method}\n\n"
                manual_info += f"To update manually, run:\n"
                manual_info += f"{version_manager.get_update_instructions()}"

                self.cli.show_help_dialog(manual_info, "Manual Update Required")
                return

            # Check if update is available first
            try:
                update_available, latest_version = version_manager.is_update_available()
                if not update_available:
                    current_version = version_manager.get_current_version()
                    self.cli.status_bar.set_success(
                        f"Already running latest version (v{current_version})"
                    )
                    return

                self.cli.status_bar.set_status(f"Updating to v{latest_version}...")

                # Perform the update
                if version_manager.perform_update():
                    self.cli.status_bar.set_success(
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

                    self.cli.show_help_dialog(restart_info, "Restart Required")
                else:
                    self.cli.status_bar.set_error(
                        "Update failed. Please update manually."
                    )

            except Exception as e:
                self.cli.status_bar.set_error(f"Update failed: {e}")

        elif action == "info":
            version_manager = VersionManager()
            current_version = version_manager.get_current_version()
            install_method = version_manager.get_installation_method()
            config = version_manager.get_update_config()

            info = f"PaperCLI Version Information\n"
            info += f"=" * 30 + "\n\n"
            info += f"Version: v{current_version}\n"
            info += f"Installation: {install_method}\n"
            info += f"GitHub Repository: {version_manager.github_repo}\n\n"

            info += f"Update Settings:\n"
            info += (
                f"- Auto-check: {'Yes' if config.get('auto_check', True) else 'No'}\n"
            )
            info += f"- Check interval: {config.get('check_interval_days', 7)} days\n"
            info += f"- Auto-update: {'Yes' if config.get('auto_update', False) else 'No'}\n"
            info += f"- Can auto-update: {'Yes' if version_manager.can_auto_update() else 'No'}\n"

            if config.get("last_check"):
                info += f"- Last check: {config['last_check'][:19]}\n"
            else:
                info += f"- Last check: Never\n"

            info += f"\nTo check for updates: /version check\n"
            if version_manager.can_auto_update():
                info += f"To update: /version update\n"
            else:
                info += f"To update manually:\n{version_manager.get_update_instructions()}\n"

            self.cli.show_help_dialog(info, "Version Information")

        else:
            self.cli.status_bar.set_error(f"Unknown version command: {action}")
            self.cli.status_bar.set_status("Usage: /version [check|update|info]")

    def handle_config_command(self, args: List[str]):
        """Handle /config command for configuration management."""
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
                    self.cli.status_bar.set_error("Use 'enable' or 'disable' for auto-sync")

        elif action == "show":
            self._show_all_config()

        elif action == "help":
            self._show_config_help()

        else:
            self.cli.status_bar.set_error(f"Unknown config option: {action}")
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

{available_models_text}

Examples:
---------
/config show                    - View all current settings
/config model gpt-4o            - Set model to GPT-4 Omni
/config model gpt-3.5-turbo     - Set model to GPT-3.5 Turbo
/config openai_api_key sk-...   - Set your OpenAI API key
/config remote ~/OneDrive/papercli-sync  - Set OneDrive sync path
/config auto-sync enable        - Enable automatic sync after edits

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

        self.cli.show_help_dialog(help_text, "Configuration Help")

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
                self.cli.status_bar.set_error(f"Error reading .env file: {e}")

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
            self.cli.status_bar.set_error(f"Error writing .env file: {e}")
            return False

    def _show_current_model(self):
        """Show the current OpenAI model."""
        current_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.cli.status_bar.set_status(f"Current OpenAI model: {current_model}")

    def _set_model(self, model_name):
        """Set the OpenAI model."""
        # Update environment variable
        os.environ["OPENAI_MODEL"] = model_name

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_MODEL"] = model_name

        if self._write_env_file(env_vars):
            self.cli.status_bar.set_success(f"OpenAI model set to: {model_name}")
            self._add_log("config_model", f"OpenAI model changed to: {model_name}")
        else:
            self.cli.status_bar.set_error("Failed to save model setting to .env file")

    def _show_current_api_key(self):
        """Show the current API key (masked)."""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            masked_key = (
                api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
                if len(api_key) > 12
                else "****"
            )
            self.cli.status_bar.set_status(f"Current OpenAI API key: {masked_key}")
        else:
            self.cli.status_bar.set_status("No OpenAI API key set")

    def _set_api_key(self, api_key):
        """Set the OpenAI API key."""
        # Basic validation
        if not api_key.startswith("sk-"):
            self.cli.status_bar.set_error(
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
            self.cli.status_bar.set_success(f"OpenAI API key set: {masked_key}")
            self._add_log("config_api_key", f"OpenAI API key updated: {masked_key}")
        else:
            self.cli.status_bar.set_error("Failed to save API key to .env file")

    def _show_current_remote_path(self):
        """Show the current remote sync path."""
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "")
        if remote_path:
            self.cli.status_bar.set_status(f"Current remote sync path: {remote_path}")
        else:
            self.cli.status_bar.set_status("No remote sync path set")

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
            self.cli.status_bar.set_success(f"Remote sync path set to: {expanded_path}")
            self._add_log("config_remote", f"Remote sync path changed to: {expanded_path}")
        else:
            self.cli.status_bar.set_error("Failed to save remote path to .env file")

    def _show_current_auto_sync(self):
        """Show the current auto-sync setting."""
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
        status = "enabled" if auto_sync else "disabled"
        self.cli.status_bar.set_status(f"Auto-sync is currently: {status}")

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
            self.cli.status_bar.set_success(f"Auto-sync {status}")
            self._add_log("config_auto_sync", f"Auto-sync {status}")
        else:
            self.cli.status_bar.set_error("Failed to save auto-sync setting to .env file")

    def _show_all_config(self):
        """Show all current configuration."""
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        api_key = os.getenv("OPENAI_API_KEY", "")
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "Not set")
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"

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

Configuration file: {env_file}
File exists: {'Yes' if env_file.exists() else 'No'}

To change settings:
/config model <model_name>
/config openai_api_key <key>
/config remote <path>
/config auto-sync enable|disable"""

        self.cli.show_help_dialog(config_text, "Current Configuration")

    def handle_sync_command(self, args: List[str]):
        """Handle /sync command for synchronizing with remote storage."""
        # Check if remote path is configured
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH")
        if not remote_path:
            self.cli.status_bar.set_error(
                "No remote sync path configured. Use '/config remote <path>' to set one."
            )
            return

        # Get local data directory
        local_path = os.path.dirname(self.cli.db_path)
        
        # Run sync synchronously but with progress updates
        # The progress callback will update the status bar in real-time
        try:
            self.cli.status_bar.set_status("Starting sync operation...", "sync")
            
            # Create progress callback that updates UI
            def progress_callback(percentage: int, message: str):
                status_message = f"Sync {percentage}%: {message}"
                self.cli.status_bar.set_status(status_message, "sync")
                # Force UI update
                if hasattr(self.cli, 'app') and self.cli.app:
                    self.cli.app.invalidate()
            
            # Create sync service with progress tracking
            sync_service = SyncService(local_path, remote_path, progress_callback=progress_callback)
            
            # Perform sync with conflict resolution
            result = sync_service.sync(conflict_resolver=self._resolve_sync_conflicts)
            
            if result.cancelled:
                self.cli.status_bar.set_status("Sync cancelled", "cancelled")
                self._add_log("sync_cancelled", "Sync operation was cancelled by user")
                return
                
            # Log the sync results
            self._add_log("sync", result.get_summary())
            
            # Show summary dialog if manual sync
            auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
            if not auto_sync:
                self._show_sync_summary(result)
            else:
                # For auto-sync, also log with auto-sync prefix
                self._add_log("auto_sync", result.get_summary())
                
            # Update status
            if result.errors:
                self.cli.status_bar.set_error(f"Sync completed with errors: {result.errors[0]}")
            elif result.has_conflicts():
                self.cli.status_bar.set_status("Sync completed with conflicts resolved", "success")
            else:
                self.cli.status_bar.set_success("Sync completed successfully")
                
        except Exception as e:
            error_msg = f"Sync failed: {str(e)}"
            self.cli.status_bar.set_error(error_msg)
            self._add_log("sync_error", error_msg)

    def _resolve_sync_conflicts(self, conflicts):
        """Show conflict resolution dialog and return user choices."""
        if not conflicts:
            return {}
        
        # Create detailed conflict summary for the dialog
        conflict_lines = [f"Found {len(conflicts)} sync conflicts that need resolution:", ""]
        
        for i, conflict in enumerate(conflicts, 1):
            conflict_lines.append(f"Conflict {i}: {conflict.conflict_type.title()} #{conflict.item_id}")
            conflict_lines.append("-" * 50)
            
            if conflict.conflict_type == "paper":
                for field, diff in conflict.differences.items():
                    local_val = str(diff['local'])[:100] + ("..." if len(str(diff['local'])) > 100 else "")
                    remote_val = str(diff['remote'])[:100] + ("..." if len(str(diff['remote'])) > 100 else "")
                    conflict_lines.append(f"Field: {field}")
                    conflict_lines.append(f"  Local:  {local_val}")
                    conflict_lines.append(f"  Remote: {remote_val}")
                    conflict_lines.append("")
                    
            elif conflict.conflict_type == "pdf":
                local_info = conflict.local_data
                remote_info = conflict.remote_data
                conflict_lines.append(f"PDF File: {conflict.item_id}")
                conflict_lines.append(f"  Local:  Size={local_info.get('size', 0):,} bytes, Modified={local_info.get('modified', 'Unknown')}")
                conflict_lines.append(f"  Remote: Size={remote_info.get('size', 0):,} bytes, Modified={remote_info.get('modified', 'Unknown')}")
                conflict_lines.append(f"  Local MD5:  {local_info.get('hash', 'Unknown')}")
                conflict_lines.append(f"  Remote MD5: {remote_info.get('hash', 'Unknown')}")
                conflict_lines.append("")
            
            conflict_lines.append("")
        
        conflict_lines.extend([
            "RESOLUTION OPTIONS:",
            "",
            "Press ENTER to continue and auto-resolve conflicts:",
            "• LOCAL versions will be kept (safer option)",
            "• Remote changes will be discarded",
            "• You can review changes in the sync summary",
            "",
            "Press ESC to cancel sync operation.",
            "",
            "Note: Interactive conflict resolution will be added in future versions."
        ])
        
        conflict_text = "\n".join(conflict_lines)
        
        # Show conflict details and wait for user confirmation
        self.cli.show_help_dialog(conflict_text, f"Sync Conflicts Found ({len(conflicts)} conflicts)")
        
        # Log the conflicts for debugging
        self._add_log("sync_conflicts", f"Found {len(conflicts)} sync conflicts that will be auto-resolved by keeping local versions")
        
        # Auto-resolve all conflicts by keeping local versions for safety
        resolutions = {}
        for conflict in conflicts:
            conflict_id = f"{conflict.conflict_type}_{conflict.item_id}"
            resolutions[conflict_id] = "local"
            # Log each conflict resolution
            self._add_log("sync_conflict_resolved", f"Conflict {conflict.conflict_type} #{conflict.item_id}: kept local version")
            
        return resolutions

    def _show_sync_summary(self, result):
        """Show sync summary dialog."""
        # Use the existing help dialog system instead of creating new application
        summary_text = self._format_sync_summary(result)
        self.cli.show_help_dialog(summary_text, "Sync Operation Summary")
        
    def _format_sync_summary(self, result):
        """Format sync summary as text."""
        lines = []
        
        # Overall status
        if result.cancelled:
            lines.append("❌ Sync was cancelled")
            lines.append("\nNo changes were made to local or remote data.")
            return "\n".join(lines)
            
        if result.errors:
            lines.append("❌ Sync completed with errors")
            lines.append("")
            for error in result.errors:
                lines.append(f"Error: {error}")
            lines.append("")
            
        if not result.errors and not result.has_conflicts():
            lines.append("✅ Sync completed successfully")
            lines.append("")
            
        # Changes summary
        changes = result.changes_applied
        total_changes = sum(changes.values())
        
        if total_changes == 0:
            lines.append("No changes were needed - local and remote are in sync.")
        else:
            lines.append("Changes Applied:")
            lines.append("")
            
            # Show detailed changes if available
            detailed_changes = getattr(result, 'detailed_changes', None)
            
            if changes['papers_added'] > 0:
                lines.append(f"📄 Papers Added ({changes['papers_added']}):")
                if detailed_changes and 'papers_added' in detailed_changes:
                    for paper_title in detailed_changes['papers_added'][:10]:  # Limit to first 10
                        lines.append(f"  • {paper_title}")
                    if len(detailed_changes['papers_added']) > 10:
                        lines.append(f"  • ... and {len(detailed_changes['papers_added']) - 10} more")
                lines.append("")
                
            if changes['papers_updated'] > 0:
                lines.append(f"📝 Papers Updated ({changes['papers_updated']}):")
                if detailed_changes and 'papers_updated' in detailed_changes:
                    for paper_title in detailed_changes['papers_updated'][:10]:
                        lines.append(f"  • {paper_title}")
                    if len(detailed_changes['papers_updated']) > 10:
                        lines.append(f"  • ... and {len(detailed_changes['papers_updated']) - 10} more")
                lines.append("")
                
            if changes['collections_added'] > 0:
                lines.append(f"📁 Collections Added ({changes['collections_added']}):")
                if detailed_changes and 'collections_added' in detailed_changes:
                    for collection_name in detailed_changes['collections_added']:
                        lines.append(f"  • {collection_name}")
                lines.append("")
                
            if changes['collections_updated'] > 0:
                lines.append(f"📂 Collections Updated ({changes['collections_updated']}):")
                if detailed_changes and 'collections_updated' in detailed_changes:
                    for collection_name in detailed_changes['collections_updated']:
                        lines.append(f"  • {collection_name}")
                lines.append("")
                
            if changes['pdfs_copied'] > 0:
                lines.append(f"📎 PDF Files Synchronized: {changes['pdfs_copied']}")
                lines.append("")
                
        # Conflicts resolved
        if result.has_conflicts():
            lines.append("")
            lines.append(f"⚠️  {len(result.conflicts)} conflicts were auto-resolved")
            lines.append("Local versions were kept for safety.")
            
        return "\n".join(lines)
