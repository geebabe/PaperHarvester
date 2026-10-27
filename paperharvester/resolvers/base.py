"""Base class and common interface for all paper resolvers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
    from paperharvester.config import Config
    from paperharvester.models import PDFCandidate, PaperRecord


class BaseResolver(ABC):
    """Abstract base resolver for discovering PDF candidates."""

    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the resolver."""
        ...

    @abstractmethod
    async def can_resolve(self, paper: PaperRecord) -> bool:
        """Check if this resolver is applicable for the given paper."""
        ...

    @abstractmethod
    async def resolve(
        self,
        paper: PaperRecord,
        client: httpx.AsyncClient,
    ) -> list[PDFCandidate]:
        """
        Discover and return candidate PDF URLs.
        Should return an empty list if no valid open-access candidate is found.
        """
        ...
