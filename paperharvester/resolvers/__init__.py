"""Resolver registry and factory for PaperHarvester."""

from __future__ import annotations

from typing import TYPE_CHECKING

from paperharvester.resolvers.acl import AclResolver
from paperharvester.resolvers.arxiv import ArxivResolver
from paperharvester.resolvers.base import BaseResolver
from paperharvester.resolvers.biorxiv import BiorxivResolver
from paperharvester.resolvers.crossref import CrossrefResolver
from paperharvester.resolvers.direct import DirectResolver
from paperharvester.resolvers.generic import GenericResolver
from paperharvester.resolvers.open_publishers import OpenPublishersResolver
from paperharvester.resolvers.openalex import OpenAlexResolver
from paperharvester.resolvers.pubmed import PubmedResolver
from paperharvester.resolvers.semantic_scholar import SemanticScholarResolver
from paperharvester.resolvers.unpaywall import UnpaywallResolver

if TYPE_CHECKING:
    from paperharvester.config import Config


def get_default_resolvers(config: Config) -> list[BaseResolver]:
    """
    Return ordered list of resolvers for the pipeline:
    1. Direct resolution (Direct PDF, arXiv, ACL, bioRxiv, PubMed, OA Publishers)
    2. Primary aggregators (Unpaywall, OpenAlex, Semantic Scholar, Crossref)
    3. Generic HTML landing page metadata
    """
    return [
        DirectResolver(config),
        ArxivResolver(config),
        AclResolver(config),
        BiorxivResolver(config),
        PubmedResolver(config),
        OpenPublishersResolver(config),
        UnpaywallResolver(config),
        OpenAlexResolver(config),
        SemanticScholarResolver(config),
        CrossrefResolver(config),
        GenericResolver(config),
    ]


__all__ = [
    "BaseResolver",
    "DirectResolver",
    "ArxivResolver",
    "AclResolver",
    "BiorxivResolver",
    "PubmedResolver",
    "OpenPublishersResolver",
    "UnpaywallResolver",
    "OpenAlexResolver",
    "SemanticScholarResolver",
    "CrossrefResolver",
    "GenericResolver",
    "get_default_resolvers",
]
