import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .constants import (
    DEFAULT_CONNECTION_NAME,
    DEFAULT_CONNECTION_URI,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    SECTION_CONTAINERS,
)


import os


config_home = os.environ.get("XDG_CONFIG_HOME")
if config_home:
    CONFIG_DIR = Path(config_home) / "docks"
else:
    CONFIG_DIR = Path.home() / ".config" / "docks"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
CONNECTIONS_FILE = CONFIG_DIR / "connections.json"



class ConfigManager:
    def __init__(self) -> None:
        self._settings = self._load_json(
            SETTINGS_FILE,
            {
                "window_width": DEFAULT_WINDOW_WIDTH,
                "window_height": DEFAULT_WINDOW_HEIGHT,
                "last_view": SECTION_CONTAINERS,
                "last_connection_id": "local",
                "dark_theme": False,
                "language": "auto",
                "color_scheme": "system",
            },
        )

    def get(self, key: str, default=None):
        return self._settings.get(key, default)

    def set(self, key: str, value) -> None:
        self._settings[key] = value
        self._write_json(SETTINGS_FILE, self._settings)

    def default_connections(self) -> list[dict]:
        return [
            {
                "id": "local",
                "name": DEFAULT_CONNECTION_NAME,
                "uri": DEFAULT_CONNECTION_URI,
                "kind": "local",
                "tls": False,
            }
        ]

    def _load_json(self, path: Path, default):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._write_json(path, default)
            return default.copy() if isinstance(default, dict) else list(default)

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._write_json(path, default)
            return default.copy() if isinstance(default, dict) else list(default)

    def _write_json(self, path: Path, payload) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as tmp_file:
            json.dump(payload, tmp_file, indent=2)
            temp_name = tmp_file.name
        Path(temp_name).replace(path)
