"""Source protocol: anything that can fetch jobs for a search configuration."""

from typing import Protocol

from vagas_bot.config import SearchConfig
from vagas_bot.models import Job


class Source(Protocol):
    name: str

    def fetch(self, cfg: SearchConfig) -> list[Job]: ...
