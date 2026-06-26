from ..core.config import ConfigManager
from ..models.connection import Connection
from ..repositories.connection_repository import ConnectionRepository
from .docker_service import DockerService


class ConnectionService:
    def __init__(
        self,
        config: ConfigManager,
        repository: ConnectionRepository,
        docker_service: DockerService,
    ) -> None:
        self._config = config
        self._repository = repository
        self._docker_service = docker_service
        self._connections = self._repository.load_all()

    def all(self) -> list[Connection]:
        return list(self._connections)

    def active(self) -> Connection:
        last_connection_id = self._config.get("last_connection_id", "local")
        for connection in self._connections:
            if connection.id == last_connection_id:
                return connection
        return self._connections[0]

    def activate(self, connection_id: str) -> Connection:
        for connection in self._connections:
            if connection.id == connection_id:
                ok, _message = self._docker_service.ping(connection)
                connection.status = "active" if ok else "failed"
                self._config.set("last_connection_id", connection.id)
                return connection
        return self.active()
