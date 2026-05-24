import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()

# Use DATA_DIR from environment for persistent storage (e.g. Render), else default to current dir
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "telegram_notifications_enabled": True,
    "telegram_bot_enabled": True,
    "instagram_username": "",
    "instagram_proxy": ""
}

def load_config():
    """Loads settings from config.json, falling back to environment variables if missing or empty."""
    config = dict(DEFAULT_CONFIG)
    
    # 1. Try to load from the JSON config file
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r") as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception:
            pass
            
    # 2. Fall back to environment variables for empty/missing values
    env_mappings = {
        "telegram_token": "TELEGRAM_TOKEN",
        "telegram_chat_id": "TELEGRAM_CHAT_ID",
        "instagram_username": "INSTAGRAM_USERNAME",
        "instagram_proxy": "INSTAGRAM_PROXY"
    }
    
    for config_key, env_var in env_mappings.items():
        if not config.get(config_key):  # If key is missing or empty string
            env_val = os.getenv(env_var)
            if env_val:
                config[config_key] = env_val
                
    # Boolean overrides from environment variables
    env_notifs = os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED")
    if env_notifs is not None:
        config["telegram_notifications_enabled"] = env_notifs.lower() in ("true", "1", "yes")
        
    env_bot = os.getenv("TELEGRAM_BOT_ENABLED")
    if env_bot is not None:
        config["telegram_bot_enabled"] = env_bot.lower() in ("true", "1", "yes")
        
    return config

def save_config(config):
    """Saves settings to config.json."""
    try:
        # Load current config (which includes file + env merges)
        current = load_config()
        current.update(config)
        
        # Ensure parent directories exist
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with CONFIG_FILE.open("w") as f:
            json.dump(current, f, indent=4)
        return True
    except Exception:
        return False

