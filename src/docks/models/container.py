from dataclasses import dataclass


@dataclass(slots=True)
class Container:
    id: str
    name: str
    display_name: str
    image: str
    image_id: str
    status: str
    created_at: str

    @property
    def short_id(self) -> str:
        return self.id[:12]
