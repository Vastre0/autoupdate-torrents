import json
import os
from typing import Any

class ConfigManager:
    USER_CONFIG_FILE = 'user-config.json'
    DEFAULT_USER_CONFIG = {
        'theme': 'light',
        'logs_expanded': True,
        'window_geometry': {'x': 100, 'y': 100, 'width': 800, 'height': 700},
        'minimize_to_tray': True,
        'close_to_tray': True,
        'show_tray_notifications': True,
        'torrent_columns_width': [300, 100, 400]
    }

    def __init__(self):
        self.config = self._load_user_config()

    def _load_user_config(self) -> dict:
        if not os.path.exists(self.USER_CONFIG_FILE):
            self._save_user_config(self.DEFAULT_USER_CONFIG)
            return self.DEFAULT_USER_CONFIG.copy()
        try:
            with open(self.USER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Добавляем новые ключи из дефолтного конфига, если их нет
            for key, value in self.DEFAULT_USER_CONFIG.items():
                config.setdefault(key, value)
            return config
        except (json.JSONDecodeError, TypeError):
            self._save_user_config(self.DEFAULT_USER_CONFIG)
            return self.DEFAULT_USER_CONFIG.copy()

    def _save_user_config(self, config_data: dict):
        with open(self.USER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        self.config[key] = value

    def save(self):
        self._save_user_config(self.config)