from ..core.config import CONNECTIONS_FILE, ConfigManager
from ..models.connection import Connection


class ConnectionRepository:
    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def load_all(self) -> list[Connection]:
        payload = self._config._load_json(CONNECTIONS_FILE, self._config.default_connections())
        return [Connection(**item) for item in payload]

    def save_all(self, connections: list[Connection]) -> None:
        payload = [
            {
                "id": connection.id,
                "name": connection.name,
                "uri": connection.uri,
                "kind": connection.kind,
                "tls": connection.tls,
            }
            for connection in connections
        ]
        self._config._write_json(CONNECTIONS_FILE, payload)
