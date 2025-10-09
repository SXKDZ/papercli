import os
from pathlib import Path
from typing import Any, Callable, Dict

from dotenv import load_dotenv, set_key
from ng.services import dialog_utils, llm_utils
from openai import OpenAI
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import BUILTIN_THEMES
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)


class ConfigDialog(ModalScreen):
    """A floating modal dialog for interactive configuration management."""

    DEFAULT_CSS = """
    ConfigDialog {
        align: center middle;
        layer: dialog;
    }
    ConfigDialog > Container {
        width: 50%;
        height: auto;
        max-height: 60%;
        min-height: 35%;
        border: solid $accent;
        background: $panel;
    }
    ConfigDialog .dialog-title {
        text-align: center;
        text-style: bold;
        background: $accent;
        color: $text;
        height: 1;
        width: 100%;
    }
    ConfigDialog #config-tabs {
        height: 1fr;
        margin: 0 1;
        border: solid $border;
    }
    
    ConfigDialog TabPane {
        padding: 0;
    }
    ConfigDialog VerticalScroll {
        padding: 1;
        scrollbar-size: 2 2;
        scrollbar-background: $surface;
        scrollbar-color: $primary;
    }
    ConfigDialog .form-row {
        height: auto;
        margin: 0 0 1 2;
        align: left top;
    }
    ConfigDialog .form-label {
        text-style: bold;
        width: 20;
        margin: 0 1 0 0;
        text-align: right;
        height: 3;
        content-align: center middle;
    }
    ConfigDialog .form-input {
        width: 1fr;
        margin: 0 1 0 0;
        height: 3;
    }
    ConfigDialog .form-select {
        width: 1fr;
        margin: 0 1 0 0;
        height: 3;
    }
    ConfigDialog .form-switch {
        width: 1fr;
        margin: 0 1 0 0;
        height: 3;
    }
    ConfigDialog .form-textarea {
        width: 1fr;
        margin: 0 1 0 0;
        height: 5;
    }
    ConfigDialog .form-radio-set {
        width: 1fr;
        margin: 0 1 0 0;
        height: auto;
        max-height: 15;
        border: solid $border;
        padding: 0 1;
        overflow-y: auto;
    }
    ConfigDialog .bottom-buttons {
        height: 5;
        align: center middle;
    }
    ConfigDialog .bottom-buttons Button {
        margin: 0 2;
        min-width: 10;
        height: 3;
        content-align: center middle;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        callback: Callable[[Dict[str, Any] | None], None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.callback = callback
        self.changes = {}
        self.available_models = []
        self.reasoning_models = []
        self.standard_models = []
        self.available_themes = []
        self.default_config = {
            "OPENAI_MODEL": "gpt-4o",
            "OPENAI_API_KEY": "",
            "OPENAI_MAX_TOKENS": "4000",
            "OPENAI_TEMPERATURE": "0.7",
            "OPENAI_SHOW_THINKING": "false",
            "OPENAI_REASONING_EFFORT": "medium",
            "PAPERCLI_REMOTE_PATH": "",
            "PAPERCLI_AUTO_SYNC": "false",
            "PAPERCLI_AUTO_SYNC_INTERVAL": "5",
            "PAPERCLI_PDF_PAGES": "10",
            "PAPERCLI_THEME": "textual-dark",
        }
        self._load_available_models()
        self._load_available_themes()

    def _load_available_models(self):
        """Load available OpenAI models and separate reasoning from standard models."""
        try:
            client = OpenAI()
            models_response = client.models.list()

            # Filter for chat models and separate reasoning vs standard models
            reasoning_models = []
            standard_models = []

            for model in models_response.data:
                model_id = model.id
                # Include all GPT models, o1, o3 series
                if any(prefix in model_id for prefix in ["gpt-", "o1", "o3"]):
                    if llm_utils.is_reasoning_model(model_id):
                        reasoning_models.append(model_id)
                    else:
                        standard_models.append(model_id)

            self.reasoning_models = sorted(reasoning_models)
            self.standard_models = sorted(standard_models)
            self.available_models = sorted(reasoning_models + standard_models)

        except Exception:
            # Fallback to common models
            self.reasoning_models = [
                "o1-preview",
                "o1-mini",
                "o3-mini",
                "o4-mini",
                "gpt-5",
            ]
            self.standard_models = [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-4",
                "gpt-3.5-turbo",
            ]
            self.available_models = sorted(self.reasoning_models + self.standard_models)

    def _load_available_themes(self):
        """Load available Textual themes dynamically."""
        theme_names = list(BUILTIN_THEMES.keys())
        self.available_themes = [
            (name.replace("-", " ").replace("_", " ").title(), name)
            for name in sorted(theme_names)
        ]

    def _build_model_options(self):
        """Build model options with visual separation between standard and reasoning models."""
        options = []

        # Add standard models section
        if self.standard_models:
            options.append(("--- Standard Models ---", "SEPARATOR_STANDARD"))
            for model in self.standard_models:
                options.append((model, model))

        # Add reasoning models section
        if self.reasoning_models:
            options.append(("--- Reasoning Models ---", "SEPARATOR_REASONING"))
            for model in self.reasoning_models:
                options.append((model, model))

        return options

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("Configuration Settings", classes="dialog-title")

            with TabbedContent(id="config-tabs"):
                # OpenAI Tab
                with TabPane("OpenAI", id="openai-tab"):
                    with VerticalScroll():
                        # Model selection
                        with Horizontal(classes="form-row"):
                            yield Label("Model:", classes="form-label")
                            model_options = self._build_model_options()
                            current_model = os.getenv("OPENAI_MODEL", "gpt-4o")
                            # Ensure we have a valid default model
                            default_model = (
                                current_model
                                if current_model in self.available_models
                                else (
                                    self.available_models[0]
                                    if self.available_models
                                    else "gpt-4o"
                                )
                            )
                            yield Select(
                                options=model_options,
                                value=default_model,
                                id="model-select",
                                classes="form-select",
                            )

                        # API Key
                        with Horizontal(classes="form-row"):
                            yield Label("API Key:", classes="form-label")
                            api_key = os.getenv("OPENAI_API_KEY", "")
                            masked_key = dialog_utils.mask_api_key(api_key)
                            yield TextArea(
                                text=masked_key,
                                id="api-key-input",
                                classes="form-textarea",
                            )

                        # Max Tokens
                        with Horizontal(classes="form-row"):
                            yield Label("Max Tokens:", classes="form-label")
                            max_tokens = os.getenv("OPENAI_MAX_TOKENS", "4000")
                            yield Input(
                                value=max_tokens,
                                placeholder="4000",
                                id="max-tokens-input",
                                classes="form-input",
                            )

                        # Temperature
                        with Horizontal(classes="form-row"):
                            yield Label("Temperature:", classes="form-label")
                            temperature = os.getenv("OPENAI_TEMPERATURE", "0.7")
                            yield Input(
                                value=temperature,
                                placeholder="0.7",
                                id="temperature-input",
                                classes="form-input",
                            )

                        # Show Thinking (for reasoning models)
                        with Horizontal(classes="form-row"):
                            yield Label("Show Thinking:", classes="form-label")
                            with RadioSet(
                                id="show-thinking-radio-set", classes="form-radio-set"
                            ):
                                show_thinking = (
                                    os.getenv("OPENAI_SHOW_THINKING", "false").lower()
                                    == "true"
                                )
                                yield RadioButton(
                                    "Enable",
                                    value=show_thinking,
                                    id="show-thinking-enable",
                                )
                                yield RadioButton(
                                    "Disable",
                                    value=not show_thinking,
                                    id="show-thinking-disable",
                                )

                        # Reasoning Effort (for reasoning models)
                        with Horizontal(classes="form-row"):
                            yield Label("Reasoning Effort:", classes="form-label")
                            with RadioSet(
                                id="reasoning-effort-radio-set",
                                classes="form-radio-set",
                            ):
                                current_effort = os.getenv(
                                    "OPENAI_REASONING_EFFORT", "medium"
                                )
                                yield RadioButton(
                                    "Minimal",
                                    value=(current_effort == "minimal"),
                                    id="reasoning-effort-minimal",
                                )
                                yield RadioButton(
                                    "Low",
                                    value=(current_effort == "low"),
                                    id="reasoning-effort-low",
                                )
                                yield RadioButton(
                                    "Medium",
                                    value=(current_effort == "medium"),
                                    id="reasoning-effort-medium",
                                )
                                yield RadioButton(
                                    "High",
                                    value=(current_effort == "high"),
                                    id="reasoning-effort-high",
                                )

                # Sync Tab
                with TabPane("Sync", id="sync-tab"):
                    with VerticalScroll():
                        # Remote Path
                        with Horizontal(classes="form-row"):
                            yield Label("Remote Path:", classes="form-label")
                            remote_path = os.getenv("PAPERCLI_REMOTE_PATH", "")
                            yield Input(
                                value=remote_path,
                                placeholder="~/OneDrive/papercli-sync",
                                id="remote-path-input",
                                classes="form-input",
                            )

                        # Auto-sync radio buttons
                        with Horizontal(classes="form-row"):
                            yield Label("Auto-sync:", classes="form-label")
                            with RadioSet(
                                id="auto-sync-radio-set", classes="form-radio-set"
                            ):
                                auto_sync = (
                                    os.getenv("PAPERCLI_AUTO_SYNC", "false").lower()
                                    == "true"
                                )
                                yield RadioButton(
                                    "Enable",
                                    value=auto_sync,
                                    id="auto-sync-enable",
                                )
                                yield RadioButton(
                                    "Disable",
                                    value=not auto_sync,
                                    id="auto-sync-disable",
                                )

                        # Auto-sync interval
                        with Horizontal(classes="form-row"):
                            yield Label("Auto-sync Interval (s):", classes="form-label")
                            auto_sync_interval = os.getenv(
                                "PAPERCLI_AUTO_SYNC_INTERVAL", "5"
                            )
                            yield Input(
                                value=str(auto_sync_interval),
                                placeholder="5",
                                id="auto-sync-interval-input",
                                classes="form-input",
                            )

                # PDF Tab
                with TabPane("PDF", id="pdf-tab"):
                    with VerticalScroll():
                        # PDF Pages Limit
                        with Horizontal(classes="form-row"):
                            yield Label("PDF Pages Limit:", classes="form-label")
                            pdf_pages = os.getenv("PAPERCLI_PDF_PAGES", "10")
                            yield Input(
                                value=pdf_pages,
                                placeholder="10",
                                id="pdf-pages-input",
                                classes="form-input",
                            )

                # Theme Tab
                with TabPane("Theme", id="theme-tab"):
                    with VerticalScroll():
                        # Theme selection as radio buttons
                        with Horizontal(classes="form-row"):
                            yield Label("Theme:", classes="form-label")
                            current_theme = os.getenv("PAPERCLI_THEME", "textual-dark")
                            with RadioSet(
                                id="theme-radio-set", classes="form-radio-set"
                            ):
                                for theme_name, theme_value in self.available_themes:
                                    is_selected = theme_value == current_theme
                                    yield RadioButton(
                                        theme_name,
                                        value=is_selected,
                                        id=f"theme-{theme_value}",
                                        name=theme_value,
                                    )

            # Bottom buttons
            with Horizontal(classes="bottom-buttons"):
                yield Button("Save", id="save-button", variant="primary")
                yield Button("Cancel", id="cancel-button", variant="default")
                yield Button("Reset", id="reset-button", variant="warning")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle model and theme selection changes."""
        if event.select.id == "model-select":
            if event.value and str(event.value).startswith("SEPARATOR_"):
                # Prevent selecting separator items by reverting to previous valid selection
                current_model = os.getenv("OPENAI_MODEL", "gpt-4o")
                if current_model in self.available_models:
                    event.select.value = current_model
                else:
                    # Find first non-separator item
                    for option_text, option_value in event.select.options:
                        if not str(option_value).startswith("SEPARATOR_"):
                            event.select.value = option_value
                            break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            self.action_save()
        elif event.button.id == "cancel-button":
            self.action_cancel()
        elif event.button.id == "reset-button":
            self.action_reset()

    def action_save(self) -> None:
        """Save configuration changes."""
        try:
            # Get current values
            model_select = self.query_one("#model-select", Select)
            api_key_input = self.query_one("#api-key-input", TextArea)
            max_tokens_input = self.query_one("#max-tokens-input", Input)
            temperature_input = self.query_one("#temperature-input", Input)
            show_thinking_radio_set = self.query_one(
                "#show-thinking-radio-set", RadioSet
            )
            reasoning_effort_radio_set = self.query_one(
                "#reasoning-effort-radio-set", RadioSet
            )
            remote_path_input = self.query_one("#remote-path-input", Input)
            auto_sync_radio_set = self.query_one("#auto-sync-radio-set", RadioSet)
            auto_sync_interval_input = self.query_one(
                "#auto-sync-interval-input", Input
            )
            pdf_pages_input = self.query_one("#pdf-pages-input", Input)
            theme_radio_set = self.query_one("#theme-radio-set", RadioSet)

            # Validate max tokens
            is_valid, error_msg, max_tokens = dialog_utils.validate_numeric_input(
                max_tokens_input.value, min_val=1, input_type="int"
            )
            if not is_valid:
                self.notify(f"Max tokens error: {error_msg}", severity="error")
                return

            # Validate temperature
            is_valid, error_msg, temperature = dialog_utils.validate_numeric_input(
                temperature_input.value, min_val=0, max_val=2, input_type="float"
            )
            if not is_valid:
                self.notify(f"Temperature error: {error_msg}", severity="error")
                return

            # Validate PDF pages
            is_valid, error_msg, pdf_pages = dialog_utils.validate_numeric_input(
                pdf_pages_input.value, min_val=1, input_type="int"
            )
            if not is_valid:
                self.notify(f"PDF pages error: {error_msg}", severity="error")
                return

            # Validate auto-sync interval
            is_valid, error_msg, auto_sync_interval = (
                dialog_utils.validate_numeric_input(
                    auto_sync_interval_input.value, min_val=1, input_type="int"
                )
            )
            if not is_valid:
                self.notify(f"Auto-sync interval error: {error_msg}", severity="error")
                return

            # Prepare changes
            changes = {}

            # Model - skip separator values
            selected_model = model_select.value
            if (
                selected_model
                and not str(selected_model).startswith("SEPARATOR_")
                and selected_model != os.getenv("OPENAI_MODEL", "gpt-4o")
            ):
                changes["OPENAI_MODEL"] = selected_model

            # API Key (handle masking)
            original_key = os.getenv("OPENAI_API_KEY", "")
            new_key = dialog_utils.unmask_api_key(api_key_input.text, original_key)
            if new_key != original_key:
                if new_key and not new_key.startswith("sk-"):
                    self.notify(
                        "Invalid API key format. OpenAI keys should start with 'sk-'",
                        severity="error",
                    )
                    return
                changes["OPENAI_API_KEY"] = new_key

            # Max Tokens
            if str(max_tokens) != os.getenv("OPENAI_MAX_TOKENS", "4000"):
                changes["OPENAI_MAX_TOKENS"] = str(max_tokens)

            # Temperature
            if str(temperature) != os.getenv("OPENAI_TEMPERATURE", "0.7"):
                changes["OPENAI_TEMPERATURE"] = str(temperature)

            # Show Thinking
            show_thinking_value = "false"  # default
            if show_thinking_radio_set.pressed_button:
                show_thinking_value = (
                    "true"
                    if show_thinking_radio_set.pressed_button.id
                    == "show-thinking-enable"
                    else "false"
                )
            if show_thinking_value != os.getenv("OPENAI_SHOW_THINKING", "false"):
                changes["OPENAI_SHOW_THINKING"] = show_thinking_value

            # Reasoning Effort
            reasoning_effort_value = "medium"  # default
            if reasoning_effort_radio_set.pressed_button:
                button_id = reasoning_effort_radio_set.pressed_button.id
                if button_id == "reasoning-effort-minimal":
                    reasoning_effort_value = "minimal"
                elif button_id == "reasoning-effort-low":
                    reasoning_effort_value = "low"
                elif button_id == "reasoning-effort-medium":
                    reasoning_effort_value = "medium"
                elif button_id == "reasoning-effort-high":
                    reasoning_effort_value = "high"
            if reasoning_effort_value != os.getenv("OPENAI_REASONING_EFFORT", "medium"):
                changes["OPENAI_REASONING_EFFORT"] = reasoning_effort_value

            # Remote Path
            remote_path = os.path.expanduser(remote_path_input.value.strip())
            if remote_path != os.getenv("PAPERCLI_REMOTE_PATH", ""):
                changes["PAPERCLI_REMOTE_PATH"] = remote_path

            # Auto-sync
            auto_sync_value = "false"  # default
            if auto_sync_radio_set.pressed_button:
                auto_sync_value = (
                    "true"
                    if auto_sync_radio_set.pressed_button.id == "auto-sync-enable"
                    else "false"
                )
            if auto_sync_value != os.getenv("PAPERCLI_AUTO_SYNC", "false"):
                changes["PAPERCLI_AUTO_SYNC"] = auto_sync_value

            # Auto-sync interval
            if str(auto_sync_interval) != os.getenv("PAPERCLI_AUTO_SYNC_INTERVAL", "5"):
                changes["PAPERCLI_AUTO_SYNC_INTERVAL"] = str(auto_sync_interval)

            # PDF Pages
            if str(pdf_pages) != os.getenv("PAPERCLI_PDF_PAGES", "10"):
                changes["PAPERCLI_PDF_PAGES"] = str(pdf_pages)

            # Theme
            selected_theme = None
            if theme_radio_set.pressed_button:
                selected_theme = theme_radio_set.pressed_button.name
            if selected_theme and selected_theme != os.getenv(
                "PAPERCLI_THEME", "textual-dark"
            ):
                changes["PAPERCLI_THEME"] = selected_theme

            # Save changes to environment and .env file
            if changes:
                self._save_env_changes(changes)
                # Apply theme change after saving
                if "PAPERCLI_THEME" in changes and hasattr(self.app, "theme"):
                    try:
                        self.app.theme = changes["PAPERCLI_THEME"]
                    except Exception:
                        # If theme doesn't exist, fall back to textual-dark
                        self.app.theme = "textual-dark"
                        os.environ["PAPERCLI_THEME"] = "textual-dark"

            if self.callback:
                self.callback(changes)
            self.dismiss(changes)

        except Exception as e:
            self.notify(f"Error saving configuration: {e}", severity="error")

    def _save_env_changes(self, changes: Dict[str, str]) -> None:
        """Save environment changes to .env file using dotenv."""
        env_file_path = self._get_env_file_path()

        # Create parent directory if it doesn't exist
        env_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Update each environment variable and save to .env file
        for key, value in changes.items():
            os.environ[key] = value
            set_key(str(env_file_path), key, value)

    def _reload_environment(self) -> None:
        """Reload environment variables from .env file using dotenv."""
        env_file_path = self._get_env_file_path()
        if env_file_path.exists():
            load_dotenv(env_file_path, override=True)

    def _get_env_file_path(self) -> Path:
        """Get the path to the .env file."""
        # Try current directory first
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

    def action_cancel(self) -> None:
        """Cancel and close dialog."""
        if self.callback:
            self.callback(None)
        self.dismiss(None)

    def action_reset(self) -> None:
        """Reset all settings to defaults and apply them."""
        try:
            # Apply default configuration to environment and save to .env
            self._save_env_changes(self.default_config)

            # Apply theme change immediately
            if hasattr(self.app, "theme"):
                try:
                    self.app.theme = self.default_config["PAPERCLI_THEME"]
                except Exception:
                    # If theme doesn't exist, fall back to textual-dark
                    self.app.theme = "textual-dark"

            # Reset UI elements to default values
            model_select = self.query_one("#model-select", Select)
            default_model = self.default_config["OPENAI_MODEL"]
            if default_model in self.available_models:
                model_select.value = default_model
            elif self.available_models:
                model_select.value = self.available_models[0]

            api_key_input = self.query_one("#api-key-input", TextArea)
            api_key_input.text = self.default_config["OPENAI_API_KEY"]

            max_tokens_input = self.query_one("#max-tokens-input", Input)
            max_tokens_input.value = self.default_config["OPENAI_MAX_TOKENS"]

            temperature_input = self.query_one("#temperature-input", Input)
            temperature_input.value = self.default_config["OPENAI_TEMPERATURE"]

            # Reset show-thinking radio buttons
            show_thinking_radio_set = self.query_one(
                "#show-thinking-radio-set", RadioSet
            )
            show_thinking_disable = self.query_one(
                "#show-thinking-disable", RadioButton
            )
            show_thinking_enable = self.query_one("#show-thinking-enable", RadioButton)

            is_show_thinking_enabled = (
                self.default_config["OPENAI_SHOW_THINKING"].lower() == "true"
            )
            show_thinking_enable.value = is_show_thinking_enabled
            show_thinking_disable.value = not is_show_thinking_enabled

            # Reset reasoning-effort radio buttons
            reasoning_effort_radio_set = self.query_one(
                "#reasoning-effort-radio-set", RadioSet
            )
            default_effort = self.default_config["OPENAI_REASONING_EFFORT"]
            for effort in ["minimal", "low", "medium", "high"]:
                try:
                    button = self.query_one(f"#reasoning-effort-{effort}", RadioButton)
                    button.value = effort == default_effort
                except Exception:
                    pass

            remote_path_input = self.query_one("#remote-path-input", Input)
            remote_path_input.value = self.default_config["PAPERCLI_REMOTE_PATH"]

            # Reset auto-sync radio buttons
            auto_sync_radio_set = self.query_one("#auto-sync-radio-set", RadioSet)
            auto_sync_disable = self.query_one("#auto-sync-disable", RadioButton)
            auto_sync_enable = self.query_one("#auto-sync-enable", RadioButton)

            is_auto_sync_enabled = (
                self.default_config["PAPERCLI_AUTO_SYNC"].lower() == "true"
            )
            auto_sync_enable.value = is_auto_sync_enabled
            auto_sync_disable.value = not is_auto_sync_enabled

            auto_sync_interval_input = self.query_one(
                "#auto-sync-interval-input", Input
            )
            auto_sync_interval_input.value = self.default_config[
                "PAPERCLI_AUTO_SYNC_INTERVAL"
            ]

            pdf_pages_input = self.query_one("#pdf-pages-input", Input)
            pdf_pages_input.value = self.default_config["PAPERCLI_PDF_PAGES"]

            # Reset theme radio buttons
            theme_radio_set = self.query_one("#theme-radio-set", RadioSet)
            default_theme = self.default_config["PAPERCLI_THEME"]

            # Reset all theme radio buttons first
            for theme_name, theme_value in self.available_themes:
                try:
                    theme_button = self.query_one(f"#theme-{theme_value}", RadioButton)
                    theme_button.value = theme_value == default_theme
                except Exception:
                    pass  # Skip if button not found

            self.notify(
                "Configuration reset to defaults and applied", severity="information"
            )

        except Exception as e:
            self.notify(f"Error resetting configuration: {e}", severity="error")

    def on_mount(self) -> None:
        """Focus the first input when dialog opens."""
        try:
            self.query_one("#model-select", Select).focus()
        except Exception:
            pass
