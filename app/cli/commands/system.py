"""System commands handler."""

import traceback
from datetime import datetime
from typing import List

import requests

from .base import BaseCommandHandler
from ...version import VersionManager


class SystemCommandHandler(BaseCommandHandler):
    """Handler for system commands like log, doctor, version, exit."""
    
    def handle_log_command(self):
        """Handle /log command."""
        if not self.cli.logs:
            log_content = "No activities logged in this session."
        else:
            # Limit to last 500 entries to prevent scrolling issues
            recent_logs = self.cli.logs[-500:] if len(self.cli.logs) > 500 else self.cli.logs

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
        self.cli.status_bar.set_status("Activity log opened - Press ESC to close", "open")

    def handle_doctor_command(self, args: List[str]):
        """Handle /doctor command for database diagnostics and cleanup."""
        try:
            action = args[0] if args else "diagnose"

            if action == "diagnose":
                self.cli.status_bar.set_status("Running diagnostic checks...", "diagnose")
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
                    self.cli.status_bar.set_error("Update failed. Please update manually.")

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