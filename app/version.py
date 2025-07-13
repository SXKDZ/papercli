"""
Version management and update functionality for PaperCLI.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests
from packaging import version


__version__ = "1.0.0"


class VersionManager:
    """Manages version checking and updates for PaperCLI."""
    
    def __init__(self):
        self.github_repo = "SXKDZ/papercli"
        self.current_version = __version__
        self.config_dir = Path.home() / ".papercli"
        self.config_file = self.config_dir / "version_config.json"
        
    def get_current_version(self) -> str:
        """Get the current version of PaperCLI."""
        return self.current_version
    
    def get_latest_version(self) -> Optional[str]:
        """Get the latest version from GitHub releases."""
        try:
            url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            release_data = response.json()
            latest_version = release_data["tag_name"]
            
            # Remove 'v' prefix if present
            if latest_version.startswith('v'):
                latest_version = latest_version[1:]
                
            return latest_version
            
        except Exception as e:
            print(f"Warning: Could not check for latest version: {e}")
            return None
    
    def is_update_available(self) -> Tuple[bool, Optional[str]]:
        """Check if an update is available."""
        latest = self.get_latest_version()
        if not latest:
            return False, None
            
        try:
            current_ver = version.parse(self.current_version)
            latest_ver = version.parse(latest)
            
            return latest_ver > current_ver, latest
        except Exception:
            return False, None
    
    def get_update_config(self) -> Dict:
        """Get update configuration settings."""
        default_config = {
            "auto_check": True,
            "last_check": None,
            "check_interval_days": 7,
            "auto_update": False
        }
        
        if not self.config_file.exists():
            self.save_update_config(default_config)
            return default_config
            
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                # Merge with defaults to handle new keys
                return {**default_config, **config}
        except Exception:
            return default_config
    
    def save_update_config(self, config: Dict) -> None:
        """Save update configuration settings."""
        self.config_dir.mkdir(exist_ok=True)
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save update config: {e}")
    
    def should_check_for_updates(self) -> bool:
        """Determine if we should check for updates based on config."""
        config = self.get_update_config()
        
        if not config.get("auto_check", True):
            return False
            
        # Always check if we've never checked before
        if not config.get("last_check"):
            return True
            
        try:
            from datetime import datetime, timedelta
            last_check = datetime.fromisoformat(config["last_check"])
            check_interval = timedelta(days=config.get("check_interval_days", 7))
            
            return datetime.now() - last_check > check_interval
        except Exception:
            return True
    
    def mark_update_check(self) -> None:
        """Mark that we've checked for updates."""
        from datetime import datetime
        config = self.get_update_config()
        config["last_check"] = datetime.now().isoformat()
        self.save_update_config(config)
    
    def get_installation_method(self) -> str:
        """Detect how PaperCLI was installed."""
        # Check if running from pipx
        if "pipx" in sys.executable or ".local/share/pipx" in sys.executable:
            return "pipx"
        
        # Check if installed as a package
        try:
            import papercli
            if hasattr(papercli, "__file__"):
                install_path = Path(papercli.__file__).parent
                if "site-packages" in str(install_path):
                    return "pip"
        except ImportError:
            pass
        
        # Default to source
        return "source"
    
    def can_auto_update(self) -> bool:
        """Check if automatic updates are possible."""
        install_method = self.get_installation_method()
        return install_method in ["pipx", "pip"]
    
    def update_via_pipx(self) -> bool:
        """Update PaperCLI via pipx."""
        try:
            # For now, reinstall from git since we're not on PyPI yet
            result = subprocess.run([
                "pipx", "reinstall", f"git+https://github.com/{self.github_repo}.git"
            ], capture_output=True, text=True, check=True)
            
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            print(f"Failed to update via pipx: {e}")
            return False
        except FileNotFoundError:
            print("pipx not found. Please install pipx first.")
            return False
    
    def update_via_pip(self) -> bool:
        """Update PaperCLI via pip."""
        try:
            # For now, reinstall from git since we're not on PyPI yet
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", "--upgrade",
                f"git+https://github.com/{self.github_repo}.git"
            ], capture_output=True, text=True, check=True)
            
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            print(f"Failed to update via pip: {e}")
            return False
    
    def perform_update(self) -> bool:
        """Perform an automatic update based on installation method."""
        install_method = self.get_installation_method()
        
        if install_method == "pipx":
            return self.update_via_pipx()
        elif install_method == "pip":
            return self.update_via_pip()
        else:
            print("Automatic updates not supported for source installations.")
            print(f"Please update manually: git pull origin main")
            return False
    
    def get_update_instructions(self) -> str:
        """Get manual update instructions based on installation method."""
        install_method = self.get_installation_method()
        
        if install_method == "pipx":
            return "pipx reinstall git+https://github.com/SXKDZ/papercli.git"
        elif install_method == "pip":
            return "pip install --upgrade git+https://github.com/SXKDZ/papercli.git"
        else:
            return "cd /path/to/papercli && git pull origin main"
    
    def check_and_prompt_update(self, force_check: bool = False) -> None:
        """Check for updates and prompt user if available."""
        if not force_check and not self.should_check_for_updates():
            return
        
        self.mark_update_check()
        
        update_available, latest_version = self.is_update_available()
        if not update_available:
            if force_check:
                print(f"✅ You're running the latest version ({self.current_version})")
            return
        
        print(f"\n🎉 Update available!")
        print(f"Current version: {self.current_version}")
        print(f"Latest version:  {latest_version}")
        
        config = self.get_update_config()
        if config.get("auto_update", False) and self.can_auto_update():
            print("\n🔄 Auto-updating...")
            if self.perform_update():
                print("✅ Update successful! Please restart PaperCLI.")
                sys.exit(0)
            else:
                print("❌ Auto-update failed. Please update manually:")
                print(f"   {self.get_update_instructions()}")
        else:
            print(f"\n📝 To update, run:")
            print(f"   {self.get_update_instructions()}")
            
            if self.can_auto_update():
                print(f"\n💡 You can enable auto-updates with: /settings auto_update true")


def get_version() -> str:
    """Get the current version string."""
    return __version__


def check_for_updates(force: bool = False) -> None:
    """Check for updates (convenience function)."""
    version_manager = VersionManager()
    version_manager.check_and_prompt_update(force_check=force)