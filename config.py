import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".wordpress-migration"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "bookstack": {
        "url": "https://wiki.yourdomain.com",
        "token_id": "",
        "token_secret": ""
    },
    "wordpress": {
        "url": "https://yourblog.com",
        "username": "",
        "app_password": ""
    },
    "api": {
        "endpoint": "https://api.bluesminds.com/v1",
        "key": ""
    },
    "models": {
        "text": "openai/gpt-oss-120b",
        "image": "grok-imagine-image-lite"
    }
}

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CONFIG.copy()

def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def get_config():
    return load_config()