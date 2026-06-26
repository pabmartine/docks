from dataclasses import dataclass


@dataclass(slots=True)
class Volume:
    name: str
    driver: str
    mountpoint: str
    created_at: str
