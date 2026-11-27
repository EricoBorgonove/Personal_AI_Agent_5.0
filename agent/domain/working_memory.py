from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Draft:
    tool: str
    slots: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)


class DraftRepository(Protocol):
    def load(self, sender: str, role: str) -> Draft | None: ...
    def save(self, sender: str, role: str, draft: Draft) -> None: ...
    def clear(self, sender: str, role: str) -> None: ...
