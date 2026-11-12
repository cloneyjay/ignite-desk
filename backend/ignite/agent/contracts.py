"""Skills are fixed contracts, not model choices.

Each skill declares what it is for, which card scopes it reads, how many cards
it may carry, and how much prose it may return. The router is a pure function
over the request; the model never decides which task to run.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSpec:
    id: str
    title: str
    when: str
    scopes: tuple[str, ...]
    card_limits: tuple[tuple[str, int], ...]
    max_words: int = 140
    temperature: float = 0.2
    max_tokens: int = 320
    system: str = ""
    user_suffix: str = "Write the commentary now."

    def budget(self) -> int:
        return sum(limit for _, limit in self.card_limits)
