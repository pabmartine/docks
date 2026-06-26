from dataclasses import dataclass


@dataclass(slots=True)
class Connection:
    id: str
    name: str
    uri: str
    kind: str = "local"
    tls: bool = False
    status: str = "unknown"

    @property
    def subtitle(self) -> str:
        return self.uri
