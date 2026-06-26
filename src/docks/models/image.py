from dataclasses import dataclass


@dataclass(slots=True)
class Image:
    id: str
    full_id: str
    tags: list[str]
    size: str
    created_at: str

    @property
    def title(self) -> str:
        return self.tags[0] if self.tags else "<none>"

    @property
    def tags_text(self) -> str:
        return ", ".join(tag for tag in self.tags if tag != "<none>:<none>") or "No tags"
