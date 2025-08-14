from __future__ import annotations
from typing import List, TYPE_CHECKING, Any, Dict

from ng.commands import CommandHandler
from ng.dialogs import CollectDialog
from ng.services import CollectionService
from pluralizer import Pluralizer

if TYPE_CHECKING:
    from ng.papercli import PaperCLIApp


class CollectionCommandHandler(CommandHandler):
    """Handler for collection commands like collect, add-to, remove-from."""

    def __init__(self, app: PaperCLIApp):
        super().__init__(app)
        self.collection_service = CollectionService()
        self.pluralizer = Pluralizer()

    def _get_target_papers(self):
        """Helper to get selected papers from the main app's paper list."""
        return self.app.screen.query_one("#paper-list-view").get_selected_papers()

    async def handle_add_to_command(self, args: List[str]):
        """Handle /add-to command."""
        if not args:
            self.app.notify(
                "Usage: /add-to <collection_name1> [collection_name2] ...",
                severity="error",
            )
            return

        collection_names = args  # Each argument is a separate collection name
        papers_to_add = self._get_target_papers()

        if not papers_to_add:
            self.app.notify("No papers selected or under cursor", severity="warning")
            return

        paper_ids = [p.id for p in papers_to_add]
        paper_titles = [p.title for p in papers_to_add]

        successful_collections = []
        failed_collections = []

        for collection_name in collection_names:
            try:
                added_count = self.collection_service.add_papers_to_collection(
                    paper_ids, collection_name
                )
                if added_count > 0:
                    successful_collections.append(collection_name)
                    # self._add_log(
                    #     "add_to_collection",
                    #     f"Added {added_count} paper(s) to '{collection_name}': {', '.join(paper_titles)}",
                    # ) # Need to implement logging
            except Exception as e:
                failed_collections.append(collection_name)
                # self._add_log(
                #     "add_to_collection_error",
                #     f"Failed to add papers to collection '{collection_name}': {str(e)}",
                # ) # Need to implement logging

        if successful_collections:
            self.app.load_papers()  # Reload papers to reflect changes
            if len(successful_collections) == 1:
                count = len(papers_to_add)
                self.app.notify(
                    f"Added {self.pluralizer.pluralize('paper', count, True)} to collection '{successful_collections[0]}'",
                    severity="information",
                )
            else:
                count = len(papers_to_add)
                collections_text = self.pluralizer.pluralize('collection', len(successful_collections), True)
                self.app.notify(
                    f"Added {self.pluralizer.pluralize('paper', count, True)} to {collections_text}: {', '.join(successful_collections)}",
                    severity="information",
                )

        if failed_collections:
            if not successful_collections:
                collections_text = self.pluralizer.pluralize('collection', len(failed_collections))
                self.app.notify(
                    f"Failed to add papers to {collections_text}: {', '.join(failed_collections)}",
                    severity="error",
                )
            else:
                collections_text = self.pluralizer.pluralize('collection', len(failed_collections))
                self.app.notify(
                    f"Some {collections_text} failed: {', '.join(failed_collections)}",
                    severity="error",
                )

    async def handle_remove_from_command(self, args: List[str]):
        """Handle /remove-from command."""
        if not args:
            self.app.notify(
                "Usage: /remove-from <collection_name1> [collection_name2] ...",
                severity="error",
            )
            return

        collection_names = args  # Each argument is a separate collection name
        papers_to_remove = self._get_target_papers()

        if not papers_to_remove:
            self.app.notify("No papers selected or under cursor", severity="warning")
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
                    self.collection_service.remove_papers_from_collection(
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
                    # self._add_log(
                    #     "remove_from_collection",
                    #     f"Removed {removed_count} paper(s) from '{collection_name}': {', '.join(paper_titles)}",
                    # ) # Need to implement logging
            except Exception as e:
                failed_collections.append(collection_name)
                all_errors.append(f"{collection_name}: {str(e)}")
                # self._add_log(
                #     "remove_from_collection_error",
                #     f"Failed to remove papers from collection '{collection_name}': {str(e)}",
                # ) # Need to implement logging

        # Show errors if any
        if all_errors:
            # self.show_error_panel_with_message( # Need to implement error panel message
            #     "Remove from Collection Error",
            #     f"Encountered {len(all_errors)} error(s).\n\n{chr(10).join(all_errors)}",
            # )
            collections_text = self.pluralizer.pluralize('collection', len(failed_collections))
            self.app.notify(
                f"Errors removing from {collections_text}: {all_errors[0]}...",
                severity="error",
            )

        if successful_collections:
            self.app.load_papers()
            if len(successful_collections) == 1:
                count = len(papers_to_remove)
                self.app.notify(
                    f"Removed {self.pluralizer.pluralize('paper', count, True)} from collection '{successful_collections[0]}'",
                    severity="information",
                )
            else:
                count = len(papers_to_remove)
                collections_text = self.pluralizer.pluralize('collection', len(successful_collections), True)
                self.app.notify(
                    f"Removed {self.pluralizer.pluralize('paper', count, True)} from {collections_text}: {', '.join(successful_collections)}",
                    severity="information",
                )
        elif not all_errors:
            self.app.notify(
                "No papers were removed from any collection.", severity="information"
            )

    async def handle_collect_command(self, args):
        """Handle /collect command with optional subcommands."""
        if not args:
            # No arguments - show the collection management dialog
            await self.show_collect_dialog()
        elif args[0] == "purge":
            # Purge empty collections
            self.handle_collect_purge_command()
        else:
            self.app.notify(
                f"Unknown collect subcommand '{args[0]}'. Usage: /collect [purge]",
                severity="error",
            )

    def handle_collect_purge_command(self):
        """Handle /collect purge command to delete empty collections."""
        try:
            deleted_count = self.collection_service.purge_empty_collections()

            if deleted_count == 0:
                self.app.notify(
                    "No empty collections found to purge", severity="information"
                )
                # self._add_log("Collection Purge", "No empty collections found") # Need to implement logging
            else:
                self.app.notify(
                    f"Purged {self.pluralizer.pluralize('empty collection', deleted_count, True)}",
                    severity="information",
                )
                # self._add_log(
                #     "Collection Purge",
                #     f"Successfully deleted {deleted_count} empty collection{'s' if deleted_count != 1 else ''}",
                # ) # Need to implement logging
        except Exception as e:
            # self.show_error_panel_with_message(
            #     "Collection Purge Error",
            #     f"Failed to purge empty collections: {e}\n\n{traceback.format_exc()}",
            # ) # Need to implement error panel message
            self.app.notify(f"Failed to purge empty collections: {e}", severity="error")

    async def show_collect_dialog(self):
        """Show the collection management dialog."""

        def callback(result: Dict[str, Any] | None):
            if result:
                try:
                    # Process the changes
                    changes_made = False

                    # Create new collections
                    for collection_name in result.get("new_collections", []):
                        self.collection_service.create_collection(collection_name)
                        changes_made = True

                    # Delete collections
                    for collection_name in result.get("deleted_collections", []):
                        collection = self.collection_service.get_collection_by_name(
                            collection_name
                        )
                        if collection:
                            self.collection_service.delete_collection(collection.id)
                            changes_made = True

                    # Process collection renames
                    for old_name, new_name in result.get("collection_changes", {}).items():
                        collection = self.collection_service.get_collection_by_name(old_name)
                        if collection:
                            self.collection_service.update_collection_name(collection.id, new_name)
                            changes_made = True

                    # Process paper moves
                    for paper_id, collection_name, action in result.get(
                        "paper_moves", []
                    ):
                        collection = self.collection_service.get_collection_by_name(
                            collection_name
                        )
                        if collection:
                            if action == "add":
                                self.collection_service.add_paper_to_collection(
                                    paper_id, collection.id
                                )
                                changes_made = True
                            elif action == "remove":
                                self.collection_service.remove_paper_from_collection(
                                    paper_id, collection.id
                                )
                                changes_made = True

                    if changes_made:
                        # Small delay to ensure database changes are fully committed
                        import time
                        time.sleep(0.1)
                        
                        self.app.load_papers()  # Reload papers to reflect changes
                        
                        # Force an explicit UI refresh to ensure collection changes are visible
                        try:
                            if hasattr(self.app, 'main_screen') and self.app.main_screen:
                                # Call the refresh method directly on the paper list widget
                                paper_list = self.app.main_screen.query_one("#paper-list-view")
                                if paper_list:
                                    paper_list.set_papers(self.app.current_papers)
                                    self.app.main_screen.update_header_stats()
                        except Exception as e:
                            self.app._add_log("collection_refresh_error", f"Error refreshing UI after collection changes: {e}")
                        
                        self.app.notify(
                            "Collections updated successfully", severity="information"
                        )
                    else:
                        self.app.notify(
                            "No changes made to collections", severity="information"
                        )

                except Exception as e:
                    self.app.notify(
                        f"Error updating collections: {e}", severity="error"
                    )

        # Get collections and papers
        try:
            collections = self.collection_service.get_all_collections()
            papers = self.app.paper_service.get_all_papers()

            await self.app.push_screen(
                CollectDialog(
                    collections,
                    papers,
                    callback,
                )
            )
        except Exception as e:
            self.app.notify(f"Error opening collection dialog: {e}", severity="error")
