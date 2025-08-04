"""Collection management commands handler."""

import traceback
from typing import List

from prompt_toolkit.layout.containers import Float

from ...dialogs import CollectDialog
from ...services import CollectionService
from .base import BaseCommandHandler


class CollectionCommandHandler(BaseCommandHandler):
    """Handler for collection commands like collect, add-to, remove-from."""

    def handle_add_to_command(self, args: List[str]):
        """Handle /add-to command."""
        if not args:
            self.cli.status_bar.set_error(
                "Usage: /add-to <collection_name1> [collection_name2] ..."
            )
            return

        collection_names = args  # Each argument is a separate collection name
        papers_to_add = self._get_target_papers()

        if not papers_to_add:
            return

        paper_ids = [p.id for p in papers_to_add]
        paper_titles = [p.title for p in papers_to_add]

        successful_collections = []
        failed_collections = []

        for collection_name in collection_names:
            try:
                added_count = self.cli.collection_service.add_papers_to_collection(
                    paper_ids, collection_name
                )
                if added_count > 0:
                    successful_collections.append(collection_name)
                    self._add_log(
                        "add_to_collection",
                        f"Added {added_count} paper(s) to '{collection_name}': {', '.join(paper_titles)}",
                    )
            except Exception as e:
                failed_collections.append(collection_name)
                self._add_log(
                    "add_to_collection_error",
                    f"Failed to add papers to collection '{collection_name}': {str(e)}",
                )

        if successful_collections:
            self.load_papers()
            if len(successful_collections) == 1:
                self.cli.status_bar.set_success(
                    f"Added {len(papers_to_add)} paper(s) to collection '{successful_collections[0]}'."
                )
            else:
                self.cli.status_bar.set_success(
                    f"Added {len(papers_to_add)} paper(s) to {len(successful_collections)} collections: {', '.join(successful_collections)}"
                )

        if failed_collections:
            if not successful_collections:
                self.cli.status_bar.set_error(
                    f"Failed to add papers to collections: {', '.join(failed_collections)}"
                )
            else:
                self.cli.status_bar.set_error(
                    f"Some collections failed: {', '.join(failed_collections)}"
                )

    def handle_remove_from_command(self, args: List[str]):
        """Handle /remove-from command."""
        if not args:
            self.cli.status_bar.set_error(
                "Usage: /remove-from <collection_name1> [collection_name2] ..."
            )
            return

        collection_names = args  # Each argument is a separate collection name
        papers_to_remove = self._get_target_papers()

        if not papers_to_remove:
            return

        paper_ids = [p.id for p in papers_to_remove]
        paper_titles = [p.title for p in papers_to_remove]

        successful_collections = []
        failed_collections = []
        total_removed = 0
        all_errors = []

        for collection_name in collection_names:
            try:
                removed_count, errors = (
                    self.cli.collection_service.remove_papers_from_collection(
                        paper_ids, collection_name
                    )
                )

                if errors:
                    all_errors.extend(
                        [f"{collection_name}: {error}" for error in errors]
                    )
                    failed_collections.append(collection_name)

                if removed_count > 0:
                    total_removed += removed_count
                    successful_collections.append(collection_name)
                    self._add_log(
                        "remove_from_collection",
                        f"Removed {removed_count} paper(s) from '{collection_name}': {', '.join(paper_titles)}",
                    )
            except Exception as e:
                failed_collections.append(collection_name)
                all_errors.append(f"{collection_name}: {str(e)}")
                self._add_log(
                    "remove_from_collection_error",
                    f"Failed to remove papers from collection '{collection_name}': {str(e)}",
                )

        # Show errors if any
        if all_errors:
            self.show_error_panel_with_message(
                "Remove from Collection Error",
                f"Encountered {len(all_errors)} error(s).\n\n{chr(10).join(all_errors)}",
            )

        if successful_collections:
            self.load_papers()
            if len(successful_collections) == 1:
                self.cli.status_bar.set_success(
                    f"Removed {len(papers_to_remove)} paper(s) from collection '{successful_collections[0]}'."
                )
            else:
                self.cli.status_bar.set_success(
                    f"Removed {len(papers_to_remove)} paper(s) from {len(successful_collections)} collections: {', '.join(successful_collections)}"
                )
        elif not all_errors:
            self.cli.status_bar.set_status(
                "No papers were removed from any collection."
            )

    def handle_collect_command(self, args):
        """Handle /collect command with optional subcommands."""
        if not args:
            # No arguments - show the collection management dialog
            self.show_collect_dialog()
        elif args[0] == "purge":
            # Purge empty collections
            self.handle_collect_purge_command()
        else:
            self.cli.status_bar.set_error(
                f"Unknown collect subcommand '{args[0]}'. Usage: /collect [purge]"
            )

    def handle_collect_purge_command(self):
        """Handle /collect purge command to delete empty collections."""
        try:
            collection_service = CollectionService()
            deleted_count = collection_service.purge_empty_collections()

            if deleted_count == 0:
                self.cli.status_bar.set_status("No empty collections found to purge.")
                self._add_log("Collection Purge", "No empty collections found")
            else:
                self.cli.status_bar.set_success(
                    f"Purged {deleted_count} empty collection{'s' if deleted_count != 1 else ''}."
                )
                self._add_log(
                    "Collection Purge",
                    f"Successfully deleted {deleted_count} empty collection{'s' if deleted_count != 1 else ''}",
                )
        except Exception as e:
            self.show_error_panel_with_message(
                "Collection Purge Error",
                f"Failed to purge empty collections: {e}\n\n{traceback.format_exc()}",
            )

    def show_collect_dialog(self):
        """Show the collection management dialog."""

        def callback(result):
            """Callback executed when the dialog is closed."""
            if self.cli.collect_float in self.cli.app.layout.container.floats:
                self.cli.app.layout.container.floats.remove(self.cli.collect_float)

            self.cli.collect_dialog = None
            self.cli.collect_float = None
            self.cli.app.layout.focus(self.cli.input_buffer)

            # Restore original key bindings
            if hasattr(self.cli, "original_key_bindings"):
                self.cli.app.key_bindings = self.cli.original_key_bindings
                del self.cli.original_key_bindings

            if result and result.get("action") == "save":
                self.load_papers()  # Reload papers to reflect changes
                self.cli.status_bar.set_success("Collections updated successfully.")
            else:
                self.cli.status_bar.set_status("Collection management cancelled.")

            self.cli.app.invalidate()

        try:
            # Store original key bindings
            self.cli.original_key_bindings = self.cli.app.key_bindings

            self.cli.collect_dialog = CollectDialog(
                self.cli.collection_service.get_all_collections(),
                self.cli.paper_service.get_all_papers(),
                callback,
                self.cli.collection_service,
                self.cli.paper_service,
                self.cli.status_bar,
                self._add_log,
                self.show_error_panel_with_message,
            )

            self.cli.collect_float = Float(self.cli.collect_dialog)
            self.cli.app.layout.container.floats.append(self.cli.collect_float)

            initial_focus_target = self.cli.collect_dialog.get_initial_focus()
            if initial_focus_target:
                self.cli.app.layout.focus(initial_focus_target)
            else:
                self.cli.app.layout.focus(self.cli.collect_dialog)

            # Set application key bindings to dialog's key bindings
            self.cli.app.key_bindings = (
                self.cli.collect_dialog.dialog.container.key_bindings
            )

            self.cli.app.invalidate()

        except Exception as e:
            self.show_error_panel_with_message(
                "Collection Dialog Error",
                f"Could not open the collection management dialog.\n\n{traceback.format_exc()}",
            )
