import json
import os
from pathlib import Path

# Use DATA_DIR from environment for persistent storage (e.g. Render), else default to current dir
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_notifications_enabled": True,
    "telegram_bot_enabled": True,
    "instagram_username": ""
}

def load_config():
    """Loads settings from config.json, or creates it with default settings if missing."""
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with CONFIG_FILE.open("r") as f:
            config = json.load(f)
            # Ensure all default keys exist
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception:
        return DEFAULT_CONFIG

def save_config(config):
    """Saves settings to config.json."""
    try:
        # Merge with existing configuration to avoid loss of keys
        current = load_config()
        current.update(config)
        with CONFIG_FILE.open("w") as f:
            json.dump(current, f, indent=4)
        return True
    except Exception:
        return False
