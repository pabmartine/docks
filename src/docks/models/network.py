from dataclasses import dataclass


@dataclass(slots=True)
class Network:
    id: str
    name: str
    stack: str
    driver: str
    ipv4: str
    ipv6: str
