from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, List

import requests
from openai import OpenAI
from pluralizer import Pluralizer

from ng.commands import CommandHandler
from ng.dialogs import ConfigDialog, DoctorDialog, MessageDialog, SyncDialog
from ng.services import DatabaseHealthService
from ng.version import VersionManager

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class SystemCommandHandler(CommandHandler):
    """Handler for system commands like log, doctor, version, exit."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.version_manager = VersionManager()
        # Initialize with db_path and app so internal logging goes to Log panel
        self.db_health_service = DatabaseHealthService(
            db_path=self.app.db_path,
            app=self.app,
        )
        self._pluralizer = Pluralizer()

    def handle_log_command(self):
        """Handle /log command - toggle log panel."""
        if hasattr(self.app.screen, "action_toggle_log"):
            self.app.screen.action_toggle_log()
        else:
            self.app.notify("Log panel not available on this screen", severity="error")

    def handle_doctor_command(self, args: List[str]):
        """Handle /doctor command for database diagnostics and cleanup."""
        try:
            action = args[0] if args else None

            if not args:
                report = self.db_health_service.run_full_diagnostic()
                self._show_doctor_report(report)

            elif action == "clean":
                self.app.notify(
                    "Cleaning orphaned records, files, and PDF filenames...",
                    severity="information",
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
                        cleanup_summary.append(
                            self._pluralizer.pluralize(
                                "record", total_cleaned_records, True
                            )
                        )
                    if total_cleaned_pdfs > 0:
                        cleanup_summary.append(
                            self._pluralizer.pluralize("PDF", total_cleaned_pdfs, True)
                        )
                    if total_fixed_paths > 0:
                        cleanup_summary.append(
                            self._pluralizer.pluralize("path", total_fixed_paths, True)
                        )
                    if total_renamed > 0:
                        cleanup_summary.append(
                            self._pluralizer.pluralize("filename", total_renamed, True)
                        )

                    if cleanup_summary:
                        self.app.notify(
                            f"Database cleanup complete - fixed {' and '.join(cleanup_summary)}",
                            severity="information",
                        )
                    else:
                        self.app.notify(
                            "Database cleanup complete", severity="information"
                        )

                    # Trigger auto-sync if enabled and available
                    try:
                        if hasattr(self.app, "auto_sync_service") and self.app.auto_sync_service:
                            # Provide a specific op marker for observability
                            self.app.auto_sync_service.enqueue(
                                {
                                    "resource": "system",
                                    "op": "doctor_clean",
                                    "summary": {
                                        "records": total_cleaned_records,
                                        "pdfs": total_cleaned_pdfs,
                                        "paths": total_fixed_paths,
                                        "renamed": total_renamed,
                                    },
                                }
                            )
                    except Exception:
                        # Non-fatal: cleaning succeeded even if enqueue fails
                        pass
                else:
                    self.app.notify(
                        "No issues found - database is clean", severity="information"
                    )

            elif action == "help":
                help_markdown = """## Database Doctor Commands

### Usage

- `/doctor` — Run full diagnostic check
- `/doctor clean` — Clean orphaned records, files, and rename PDFs to follow naming convention
- `/doctor help` — Show this help

### What it checks

- Database integrity and structure
- Orphaned association records and PDF files
- Papers with absolute PDF paths (should be relative)
- Papers with missing PDF files
- System dependencies
- Terminal capabilities
- Opportunities for automated cleanup
- PDF filename consistency

### PDF Filename Convention

```
Format: {author_lastname}{year}{first_word}_{hash}.pdf
Example: smith2023learning_a1b2c3.pdf
Notes:
- Uses first author's last name, publication year, first significant word from title
- Includes 6-character hash from PDF content for uniqueness
```
"""

                self.app.push_screen(
                    MessageDialog("Database Doctor Help", help_markdown)
                )

            else:
                self.app.notify(
                    f"Unknown doctor action: {action}. Use 'diagnose', 'clean', or 'help'",
                    severity="error",
                )

        except Exception as e:
            self.app.notify(f"Failed to run doctor command: {str(e)}", severity="error")

    def _show_doctor_report(self, report: dict):
        """Display the doctor diagnostic report formatted as markdown."""
        # Create formatted markdown report (title already shown in dialog header)
        markdown_lines = [
            f"*Generated: {report['timestamp'][:19]}*",
            "",
            "## Database Health",
            "📊 *Database integrity and structure*",
            "",
        ]

        db_checks = report["database_checks"]
        health_items = [
            f"- **Database exists:** {'✅ Yes' if db_checks['database_exists'] else '❌ No'}",
            f"- **Tables exist:** {'✅ Yes' if db_checks['tables_exist'] else '❌ No'}",
            f"- **Database size:** {db_checks.get('database_size', 0) // 1024:,} KB",
            f"- **Foreign key constraints:** {'✅ Enabled' if db_checks['foreign_key_constraints'] else '❌ Disabled'}",
        ]
        markdown_lines.extend(health_items)

        if db_checks.get("table_counts"):
            markdown_lines.extend(["", "### Table Counts", ""])
            for table, count in db_checks["table_counts"].items():
                markdown_lines.append(f"- `{table}`: {count:,} records")

        markdown_lines.extend(
            [
                "",
                "## Orphaned Records",
                "🔗 *Records and files without valid references*",
                "",
            ]
        )
        orphaned_records = report["orphaned_records"]["summary"]
        pc_count = orphaned_records.get("orphaned_paper_collections", 0)
        pa_count = orphaned_records.get("orphaned_paper_authors", 0)

        orphan_items = [
            f"- **Paper-collection associations:** {pc_count:,}",
            f"- **Paper-author associations:** {pa_count:,}",
        ]

        orphaned_pdfs = report.get("orphaned_pdfs", {}).get("summary", {})
        pdf_count = orphaned_pdfs.get("orphaned_pdf_files", 0)
        if pdf_count > 0:
            orphan_items.append(f"- **Orphaned PDF files:** {pdf_count:,}")

        absolute_paths = report.get("absolute_pdf_paths", {}).get("summary", {})
        absolute_count = absolute_paths.get("absolute_path_count", 0)
        if absolute_count > 0:
            orphan_items.append(
                f"- **Papers with absolute PDF paths:** {absolute_count:,}"
            )

        missing_pdfs = report.get("missing_pdfs", {}).get("summary", {})
        missing_count = missing_pdfs.get("missing_pdf_count", 0)
        if missing_count > 0:
            orphan_items.append(
                f"- **Papers with missing PDF files:** {missing_count:,}"
            )

        markdown_lines.extend(orphan_items)

        # Add detailed missing PDF information if available
        if missing_count > 0:
            missing_pdf_details = report.get("missing_pdfs", {}).get("details", [])
            if missing_pdf_details:
                markdown_lines.extend(["", "### Missing PDF Files Details", ""])
                for detail in missing_pdf_details[:10]:  # Limit to first 10 for display
                    paper_id = detail.get("paper_id", "Unknown")
                    title = detail.get("title", "No title")
                    pdf_path = detail.get("pdf_path", "No path")
                    path_type = detail.get("path_type", "unknown")
                    markdown_lines.append(f"- **Paper {paper_id}**: {title}")
                    markdown_lines.append(f"  - Path: `{pdf_path}` ({path_type})")

                if len(missing_pdf_details) > 10:
                    remaining = len(missing_pdf_details) - 10
                    markdown_lines.append(
                        f"- ... and {remaining} more papers with missing PDFs"
                    )

        # Add PDF statistics section
        pdf_stats = report.get("pdf_statistics", {})
        if pdf_stats:
            markdown_lines.extend(
                [
                    "",
                    "## PDF Collection",
                    "📁 *PDF folder statistics and information*",
                    "",
                ]
            )

            if pdf_stats.get("pdf_folder_exists", False):
                total_files = pdf_stats.get("total_pdf_files", 0)
                total_size = pdf_stats.get("total_size_formatted", "0 B")

                pdf_info = [
                    f"- **Total PDF files:** {total_files:,}",
                    f"- **Total folder size:** {total_size}",
                ]

                markdown_lines.extend(pdf_info)
            else:
                pdf_folder_path = pdf_stats.get("pdf_folder_path", "Unknown")
                markdown_lines.append(
                    f"- **PDF folder:** ❌ Does not exist (`{pdf_folder_path}`)"
                )

        markdown_lines.extend(
            ["", "## System Health", "💻 *Python environment and dependencies*", ""]
        )
        sys_checks = report["system_checks"]
        python_version = (
            sys_checks["python_version"].split()[0]
            if sys_checks["python_version"]
            else "Unknown"
        )
        markdown_lines.append(f"- **Python version:** `{python_version}`")

        # Show dependencies as individual list items
        markdown_lines.extend(["", "### Dependencies", ""])
        for dep, status in sys_checks["dependencies"].items():
            status_icon = "✅" if status else "❌"
            markdown_lines.append(f"- `{dep}`: {status_icon}")

        markdown_lines.extend(
            ["", "## Terminal Setup", "🖥️ *Terminal capabilities and configuration*", ""]
        )
        term_checks = report["terminal_checks"]
        terminal_items = [
            f"- **Terminal type:** `{term_checks['terminal_type']}`",
            f"- **Unicode support:** {'✅ Yes' if term_checks['unicode_support'] else '❌ No'}",
            f"- **Color support:** {'✅ Yes' if term_checks['color_support'] else '❌ No'}",
        ]

        if "terminal_size" in term_checks and "columns" in term_checks["terminal_size"]:
            size = term_checks["terminal_size"]
            terminal_items.append(
                f"- **Terminal size:** {size['columns']}×{size['lines']}"
            )

        # Add Textual-specific features if available
        if "textual_features" in term_checks:
            textual_features = term_checks["textual_features"]
            terminal_items.extend(
                [
                    "",
                    "### Textual Application Features",
                    f"- **Rich rendering:** {'✅ Yes' if textual_features.get('rich_rendering') else '❌ No'}",
                    f"- **Mouse support:** {'✅ Yes' if textual_features.get('mouse_support') else '❌ No'}",
                    f"- **Keyboard events:** {'✅ Yes' if textual_features.get('keyboard_events') else '❌ No'}",
                    f"- **Async events:** {'✅ Yes' if textual_features.get('async_events') else '❌ No'}",
                ]
            )

        markdown_lines.extend(terminal_items)

        # Issues and recommendations
        if report["issues_found"]:
            markdown_lines.extend(
                ["", "## Issues Found", "⚠️ *Problems detected that need attention*", ""]
            )
            for issue in report["issues_found"]:
                markdown_lines.append(f"- {issue}")

        if report["recommendations"]:
            markdown_lines.extend(
                [
                    "",
                    "## Recommendations",
                    "💡 *Suggested actions to improve database health*",
                    "",
                ]
            )
            for rec in report["recommendations"]:
                markdown_lines.append(f"- {rec}")

        if pc_count > 0 or pa_count > 0 or absolute_count > 0 or pdf_count > 0:
            markdown_lines.extend(
                [
                    "",
                    "## Quick Fix",
                    "🧹 *Automatic cleanup command*",
                    "",
                    "To automatically clean up issues, run:",
                    "```",
                    "/doctor clean",
                    "```",
                ]
            )

        report_markdown = "\n".join(markdown_lines)
        self.app.push_screen(DoctorDialog(report_markdown))

    def handle_exit_command(self):
        """Handle /exit command - exit the application."""
        self.app.exit()

    def handle_version_command(self, args: List[str]):
        """Handle /version command for version management."""

        if not args:
            # Show basic version info
            current_version = self.version_manager.current_version
            install_method = self.version_manager.get_installation_method()

            version_info = f"PaperCLI v{current_version}\n"
            version_info += f"Installation: {install_method}\n"

            # Check for updates in background
            try:
                update_available, latest_version = (
                    self.version_manager.is_update_available()
                )
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
            self.app.notify("Checking for updates...", severity="information")
            try:
                update_available, latest_version = (
                    self.version_manager.is_update_available()
                )
                current_version = self.version_manager.current_version

                if update_available:
                    update_info = f"Update Available!\n\n"
                    update_info += f"Current version: v{current_version}\n"
                    update_info += f"Latest version:  v{latest_version}\n\n"

                    if self.version_manager.can_auto_update():
                        update_info += "To update, run: /version update\n\n"
                    else:
                        update_info += "To update manually, run:\n"
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
                    self.app.notify(
                        f"You're running the latest version (v{current_version})",
                        severity="information",
                    )
            except Exception as e:
                self.app.notify(f"Could not check for updates: {e}", severity="error")

        elif action == "update":
            if not self.version_manager.can_auto_update():
                install_method = self.version_manager.get_installation_method()
                self.app.notify(
                    f"Auto-update not supported for {install_method} installations",
                    severity="error",
                )

                manual_info = f"Manual Update Required\n\n"
                manual_info += f"Installation method: {install_method}\n\n"
                manual_info += f"To update manually, run:\n"
                manual_info += f"{self.version_manager.get_update_instructions()}"

                self.app.push_screen(
                    MessageDialog("Manual Update Required", manual_info)
                )
                return

            # Check if update is available first
            try:
                update_available, latest_version = (
                    self.version_manager.is_update_available()
                )
                if not update_available:
                    current_version = self.version_manager.current_version
                    self.app.notify(
                        f"Already running latest version (v{current_version})",
                        severity="information",
                    )
                    return

                self.app.notify(
                    f"Updating to v{latest_version}...", severity="information"
                )

                # Perform the update
                if self.version_manager.perform_update():
                    self.app.notify(
                        "Update successful! Please restart PaperCLI.",
                        severity="information",
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

                    self.app.push_screen(
                        MessageDialog("Restart Required", restart_info)
                    )
                else:
                    self.app.notify(
                        "Update failed. Please update manually.", severity="error"
                    )

            except Exception as e:
                self.app.notify(f"Update failed: {e}", severity="error")

        elif action == "info":
            current_version = self.version_manager.current_version
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
            self.app.notify(f"Unknown version command: {action}", severity="error")
            self.app.notify(
                "Usage: /version [check|update|info]", severity="information"
            )

    def handle_config_command(self, args: List[str]):
        """Handle /config command for configuration management."""
        # Check if using legacy command format
        if args:
            action = args[0].lower()

            # Handle legacy commands
            if action == "model":
                if len(args) < 2:
                    self._show_current_model()
                else:
                    model_name = args[1]
                    self._set_model(model_name)
                return

            elif action == "openai_api_key":
                if len(args) < 2:
                    self._show_current_api_key()
                else:
                    api_key = args[1]
                    self._set_api_key(api_key)
                return

            elif action == "remote":
                if len(args) < 2:
                    self._show_current_remote_path()
                else:
                    remote_path = args[1]
                    self._set_remote_path(remote_path)
                return

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
                        self.app.notify(
                            "Use 'enable' or 'disable' for auto-sync", severity="error"
                        )
                return

            elif action == "auto-sync-interval":
                if len(args) < 2:
                    self._show_current_auto_sync_interval()
                else:
                    try:
                        seconds = int(args[1])
                        if seconds > 0:
                            self._set_auto_sync_interval(seconds)
                        else:
                            self.app.notify(
                                "Auto-sync interval must be a positive number",
                                severity="error",
                            )
                    except ValueError:
                        self.app.notify(
                            "Auto-sync interval must be a valid number",
                            severity="error",
                        )
                return

            elif action == "pdf-pages":
                if len(args) < 2:
                    self._show_current_pdf_pages()
                else:
                    try:
                        pages = int(args[1])
                        if pages > 0:
                            self._set_pdf_pages(pages)
                        else:
                            self.app.notify(
                                "PDF pages must be a positive number", severity="error"
                            )
                    except ValueError:
                        self.app.notify(
                            "PDF pages must be a valid number", severity="error"
                        )
                return

            elif action == "max-tokens":
                if len(args) < 2:
                    self._show_current_max_tokens()
                else:
                    try:
                        max_tokens = int(args[1])
                        if max_tokens > 0:
                            self._set_max_tokens(max_tokens)
                        else:
                            self.app.notify(
                                "Max tokens must be a positive number", severity="error"
                            )
                    except ValueError:
                        self.app.notify(
                            "Max tokens must be a valid number", severity="error"
                        )
                return

            elif action == "temperature":
                if len(args) < 2:
                    self._show_current_temperature()
                else:
                    try:
                        temperature = float(args[1])
                        if 0 <= temperature <= 2:
                            self._set_temperature(temperature)
                        else:
                            self.app.notify(
                                "Temperature must be between 0 and 2", severity="error"
                            )
                    except ValueError:
                        self.app.notify(
                            "Temperature must be a valid number", severity="error"
                        )
                return

            elif action == "show":
                self._show_all_config()
                return

            elif action == "theme":
                if len(args) < 2:
                    self._show_current_theme()
                else:
                    theme_name = args[1].lower()
                    self._set_theme(theme_name)
                return

            elif action == "help":
                self._show_config_help()
                return

        # Show interactive config dialog (new default behavior)
        def config_callback(changes):
            if changes:
                changed_settings = []
                for key, value in changes.items():
                    setting_name = (
                        key.replace("PAPERCLI_", "")
                        .replace("OPENAI_", "")
                        .lower()
                        .replace("_", "-")
                    )
                    if key == "OPENAI_API_KEY":
                        # Mask the API key in the message
                        masked_value = (
                            value[:8] + "*" * (len(value) - 12) + value[-4:]
                            if len(value) > 12
                            else "****"
                        )
                        changed_settings.append(f"{setting_name}: {masked_value}")
                    else:
                        changed_settings.append(f"{setting_name}: {value}")

                if changed_settings:
                    self.app.notify(
                        f"Configuration updated: {', '.join(changed_settings)}",
                        severity="information",
                    )
                else:
                    self.app.notify(
                        "No configuration changes made", severity="information"
                    )

                # Inform auto-sync service of relevant changes
                if hasattr(self.app, "auto_sync_service"):
                    self.app.auto_sync_service.on_config_changed(changes)

        self.app.push_screen(ConfigDialog(callback=config_callback))

    def _show_config_help(self):
        """Show configuration help."""
        # Get available models dynamically
        available_models_text = self._get_available_models_text()

        # Build markdown-formatted help content
        markdown_lines = [
            "## Configuration Commands",
            "",
            "### Available Commands",
            "",
            "- `/config show` — Show all current configuration",
            "- `/config model` — Show current OpenAI model",
            "- `/config model <model_name>` — Set OpenAI model (e.g., gpt-4o, gpt-3.5-turbo)",
            "- `/config max-tokens` — Show current OpenAI max tokens",
            "- `/config max-tokens <number>` — Set OpenAI max tokens",
            "- `/config temperature` — Show current OpenAI temperature",
            "- `/config temperature <0-2>` — Set OpenAI temperature (0–2)",
            "- `/config openai_api_key` — Show current API key (masked)",
            "- `/config openai_api_key <key>` — Set OpenAI API key",
            "- `/config remote` — Show current remote sync path",
            "- `/config remote <path>` — Set remote sync path (e.g., ~/OneDrive/papercli-sync)",
            "- `/config auto-sync` — Show current auto-sync setting",
            "- `/config auto-sync enable` — Enable auto-sync after edits",
            "- `/config auto-sync disable` — Disable auto-sync",
            "- `/config auto-sync-interval` — Show current auto-sync interval (seconds)",
            "- `/config auto-sync-interval <seconds>` — Set auto-sync interval",
            "- `/config pdf-pages` — Show current PDF pages limit for chat/summarize",
            "- `/config pdf-pages <number>` — Set PDF pages limit (e.g., 15, 20)",
            "- `/config theme` — Show current theme",
            "- `/config theme <theme_name>` — Set theme (dark, light, textual-dark, textual-light)",
            "",
            "### Available OpenAI Models",
            "",
            "```",
            available_models_text,
            "```",
            "",
            "### Examples",
            "",
            "```",
            "/config show",
            "/config model gpt-4o",
            "/config max-tokens 4000",
            "/config temperature 0.7",
            "/config model gpt-3.5-turbo",
            "/config openai_api_key sk-...",
            "/config remote ~/OneDrive/papercli-sync",
            "/config auto-sync enable",
            "/config auto-sync-interval 5",
            "/config pdf-pages 15",
            "/config theme dark",
            "/config theme light",
            "```",
            "",
            "### Temperature Guidance",
            "",
            "You can think of temperature like randomness, with 0 being least random (most deterministic) and 2 being most random (least deterministic).",
            "When using low values (e.g. `0.2`) responses are more consistent but may feel robotic.",
            "Values higher than `1.0` can lead to erratic outputs. For creative tasks, try `1.2` and prompt the model to be creative.",
            "Experiment to find the best setting for your use case.",
            "",
            "### Configuration Storage",
            "",
            "Settings are stored in environment variables and automatically saved to a `.env` file.",
            "The `.env` file is searched in this order:",
            "1. Current directory (`.env`)",
            "2. `PAPERCLI_DATA_DIR` if set",
            "3. `~/.papercli/.env` (default)",
            "",
            "### API Key Security",
            "",
            "API keys are masked when displayed for security. Only the first 8 and last 4 characters are shown.",
        ]

        help_markdown = "\n".join(markdown_lines)
        self.app.push_screen(MessageDialog("Configuration Help", help_markdown))

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
                self.app.notify(f"Error reading .env file: {e}", severity="error")

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
            self.app.notify(f"Error writing .env file: {e}", severity="error")
            return False

    def _show_current_model(self):
        """Show the current OpenAI model."""
        current_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.app.notify(
            f"Current OpenAI model: {current_model}", severity="information"
        )

    def _set_model(self, model_name):
        """Set the OpenAI model."""
        # Update environment variable
        os.environ["OPENAI_MODEL"] = model_name

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_MODEL"] = model_name

        if self._write_env_file(env_vars):
            self.app.notify(
                f"OpenAI model set to: {model_name}", severity="information"
            )
            # self._add_log("config_model", f"OpenAI model changed to: {model_name}") # Need to implement logging
        else:
            self.app.notify(
                "Failed to save model setting to .env file", severity="error"
            )

    def _show_current_api_key(self):
        """Show the current API key (masked)."""
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            masked_key = (
                api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:]
                if len(api_key) > 12
                else "****"
            )
            self.app.notify(
                f"Current OpenAI API key: {masked_key}", severity="information"
            )
        else:
            self.app.notify("No OpenAI API key set", severity="information")

    def _set_api_key(self, api_key):
        """Set the OpenAI API key."""
        # Basic validation
        if not api_key.startswith("sk-"):
            self.app.notify(
                "Invalid API key format. OpenAI keys should start with 'sk-'",
                severity="error",
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
            self.app.notify(f"OpenAI API key set: {masked_key}", severity="information")
            # self._add_log("config_api_key", f"OpenAI API key updated: {masked_key}") # Need to implement logging
        else:
            self.app.notify("Failed to save API key to .env file", severity="error")

    def _show_current_remote_path(self):
        """Show the current remote sync path."""
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "")
        if remote_path:
            self.app.notify(
                f"Current remote sync path: {remote_path}", severity="information"
            )
        else:
            self.app.notify("No remote sync path set", severity="information")

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
            self.app.notify(
                f"Remote sync path set to: {expanded_path}", severity="information"
            )
            # Notify auto-sync service
            if hasattr(self.app, "auto_sync_service"):
                self.app.auto_sync_service.on_config_changed(
                    {"PAPERCLI_REMOTE_PATH": expanded_path}
                )
            # self._add_log("config_remote", f"Remote sync path changed to: {expanded_path}") # Need to implement logging
        else:
            self.app.notify("Failed to save remote path to .env file", severity="error")

    def _show_current_auto_sync(self):
        """Show the current auto-sync setting."""
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
        status = "enabled" if auto_sync else "disabled"
        self.app.notify(f"Auto-sync is currently: {status}", severity="information")

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
            self.app.notify(f"Auto-sync {status}", severity="information")
            # Notify auto-sync service
            if hasattr(self.app, "auto_sync_service"):
                self.app.auto_sync_service.on_config_changed(
                    {"PAPERCLI_AUTO_SYNC": value}
                )
            # self._add_log("config_auto_sync", f"Auto-sync {status}") # Need to implement logging
        else:
            self.app.notify(
                "Failed to save auto-sync setting to .env file", severity="error"
            )

    def _show_current_auto_sync_interval(self):
        """Show current auto-sync interval in seconds."""
        interval = int(os.getenv("PAPERCLI_AUTO_SYNC_INTERVAL", "5"))
        self.app.notify(
            f"Auto-sync interval: {interval} seconds", severity="information"
        )

    def _set_auto_sync_interval(self, seconds: int):
        """Set the auto-sync interval seconds."""
        value = str(seconds)

        # Update environment variable
        os.environ["PAPERCLI_AUTO_SYNC_INTERVAL"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_AUTO_SYNC_INTERVAL"] = value

        if self._write_env_file(env_vars):
            self.app.notify(
                f"Auto-sync interval set to: {seconds} seconds", severity="information"
            )
            # Notify auto-sync service
            if hasattr(self.app, "auto_sync_service"):
                self.app.auto_sync_service.on_config_changed(
                    {"PAPERCLI_AUTO_SYNC_INTERVAL": value}
                )
        else:
            self.app.notify(
                "Failed to save auto-sync interval to .env file", severity="error"
            )

    def _show_current_pdf_pages(self):
        """Show the current PDF pages limit."""
        pdf_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
        self.app.notify(f"Current PDF pages limit: {pdf_pages}", severity="information")

    def _set_pdf_pages(self, pages):
        """Set the PDF pages limit."""
        value = str(pages)

        # Update environment variable
        os.environ["PAPERCLI_PDF_PAGES"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_PDF_PAGES"] = value

        if self._write_env_file(env_vars):
            self.app.notify(f"PDF pages limit set to: {pages}", severity="information")
            # self._add_log("config_pdf_pages", f"PDF pages limit set to: {pages}") # Need to implement logging
        else:
            self.app.notify(
                "Failed to save PDF pages setting to .env file", severity="error"
            )

    def _show_current_max_tokens(self):
        """Show the current OpenAI max tokens."""
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        self.app.notify(
            f"Current OpenAI max tokens: {max_tokens}", severity="information"
        )

    def _set_max_tokens(self, max_tokens: int):
        """Set the OpenAI max tokens."""
        value = str(max_tokens)

        # Update environment variable
        os.environ["OPENAI_MAX_TOKENS"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_MAX_TOKENS"] = value

        if self._write_env_file(env_vars):
            self.app.notify(
                f"OpenAI max tokens set to: {max_tokens}", severity="information"
            )
        else:
            self.app.notify(
                "Failed to save max tokens setting to .env file", severity="error"
            )

    def _show_current_temperature(self):
        """Show the current OpenAI temperature."""
        temperature = os.getenv("OPENAI_TEMPERATURE", "0.7")
        self.app.notify(
            f"Current OpenAI temperature: {temperature}", severity="information"
        )

    def _set_temperature(self, temperature: float):
        """Set the OpenAI temperature."""
        value = str(temperature)

        # Update environment variable
        os.environ["OPENAI_TEMPERATURE"] = value

        # Update .env file
        env_vars = self._read_env_file()
        env_vars["OPENAI_TEMPERATURE"] = value

        if self._write_env_file(env_vars):
            self.app.notify(
                f"OpenAI temperature set to: {temperature}", severity="information"
            )
        else:
            self.app.notify(
                "Failed to save temperature setting to .env file", severity="error"
            )

    def _show_all_config(self):
        """Show all current configuration."""
        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        api_key = os.getenv("OPENAI_API_KEY", "")
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        temperature = os.getenv("OPENAI_TEMPERATURE", "0.7")
        remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "Not set")
        auto_sync = os.getenv("PAPERCLI_AUTO_SYNC", "false").lower() == "true"
        auto_sync_interval = int(os.getenv("PAPERCLI_AUTO_SYNC_INTERVAL", "5"))
        pdf_pages = int(os.getenv("PAPERCLI_PDF_PAGES", "10"))
        theme = os.getenv("PAPERCLI_THEME", getattr(self.app, "theme", "textual-dark"))

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

        # Build markdown-formatted configuration details for proper rendering
        markdown_lines = [
            "## Current Configuration",
            "",
            f"- **OpenAI Model**: `{model}`",
            f"- **OpenAI Max Tokens**: `{max_tokens}`",
            f"- **OpenAI Temperature**: `{temperature}`",
            f"- **OpenAI API Key**: `{masked_key}`",
            f"- **Remote Sync Path**: `{remote_path}`",
            f"- **Auto-sync**: `{auto_sync_status}`",
            f"- **Auto-sync Interval (s)**: `{auto_sync_interval}`",
            f"- **PDF Pages Limit**: `{pdf_pages}`",
            f"- **Theme**: `{theme}`",
            "",
            "### Configuration File",
            "",
            f"- **Path**: `{env_file}`",
            f"- **Exists**: {'✅ Yes' if env_file.exists() else '❌ No'}",
            "",
            "### Change Settings",
            "",
            "```",
            "/config model <model_name>",
            "/config max-tokens <number>",
            "/config temperature <0-2>",
            "/config openai_api_key <key>",
            "/config remote <path>",
            "/config auto-sync enable|disable",
            "/config auto-sync-interval <seconds>",
            "/config pdf-pages <number>",
            "/config theme <theme_name>",
            "```",
        ]

        config_markdown = "\n".join(markdown_lines)
        self.app.push_screen(MessageDialog("Current Configuration", config_markdown))

    def _show_current_theme(self):
        """Show the current theme."""
        current_theme = getattr(self.app, "theme", "textual-dark")
        self.app.notify(f"Current theme: {current_theme}", severity="information")

    def _set_theme(self, theme_name):
        """Set the application theme."""
        available_themes = ["textual-dark", "textual-light", "dark", "light"]

        # Normalize theme name
        theme_map = {
            "dark": "textual-dark",
            "light": "textual-light",
            "textual-dark": "textual-dark",
            "textual-light": "textual-light",
        }

        normalized_theme = theme_map.get(theme_name)
        if not normalized_theme:
            available = ", ".join(available_themes)
            self.app.notify(
                f"Unknown theme: {theme_name}. Available: {available}", severity="error"
            )
            return

        # Set the theme
        self.app.theme = normalized_theme

        # Save to environment and .env file
        os.environ["PAPERCLI_THEME"] = normalized_theme
        env_vars = self._read_env_file()
        env_vars["PAPERCLI_THEME"] = normalized_theme

        if self._write_env_file(env_vars):
            self.app.notify(f"Theme set to: {normalized_theme}", severity="information")
        else:
            self.app.notify(
                "Failed to save theme setting to .env file", severity="error"
            )

    def handle_sync_command(self, args: List[str]):
        """Handle /sync command for synchronizing with remote storage."""
        try:
            # Get data directory path
            local_data_dir = Path(self.app.db_path).parent

            # Check for remote path - first from args, then from config
            remote_data_dir = None
            if args:
                remote_data_dir = Path(args[0])
            else:
                # Check configured remote path
                configured_path = os.getenv("PAPERCLI_REMOTE_PATH", "")
                if configured_path:
                    remote_data_dir = Path(os.path.expanduser(configured_path))

            if not remote_data_dir:
                self.app.notify(
                    "No remote path configured. Set it with: /config remote <path> or use: /sync <remote_path>",
                    severity="error",
                )
                return

            # Show sync dialog with progress
            def sync_callback(result):
                if result:
                    # Refresh papers after successful sync
                    self.app.load_papers()

            self.app.push_screen(
                SyncDialog(
                    callback=sync_callback,
                    local_path=str(local_data_dir),
                    remote_path=str(remote_data_dir),
                )
            )

        except Exception as e:
            self.app.notify(f"Sync error: {str(e)}", severity="error")
