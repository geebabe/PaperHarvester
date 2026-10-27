"""Tests for modular source-specific and fallback resolvers."""

from __future__ import annotations

import httpx
import pytest
import respx

from paperharvester.config import Config
from paperharvester.models import PaperRecord
from paperharvester.resolvers.acl import AclResolver
from paperharvester.resolvers.arxiv import ArxivResolver
from paperharvester.resolvers.biorxiv import BiorxivResolver
from paperharvester.resolvers.crossref import CrossrefResolver
from paperharvester.resolvers.direct import DirectResolver
from paperharvester.resolvers.generic import GenericResolver
from paperharvester.resolvers.open_publishers import OpenPublishersResolver
from paperharvester.resolvers.openalex import OpenAlexResolver
from paperharvester.resolvers.pubmed import PubmedResolver
from paperharvester.resolvers.semantic_scholar import SemanticScholarResolver
from paperharvester.resolvers.unpaywall import UnpaywallResolver


@pytest.mark.asyncio
async def test_direct_resolver(test_config: Config):
    resolver = DirectResolver(test_config)
    paper = PaperRecord(row_id=1, url="https://example.com/downloads/sample_paper.pdf")
    assert await resolver.can_resolve(paper) is True

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://example.com/downloads/sample_paper.pdf"
        assert candidates[0].confidence == 1.0


@pytest.mark.asyncio
async def test_arxiv_resolver(test_config: Config):
    resolver = ArxivResolver(test_config)

    p1 = PaperRecord(row_id=1, url="https://arxiv.org/abs/2301.00001v2")
    assert await resolver.can_resolve(p1) is True

    p2 = PaperRecord(row_id=2, doi="10.48550/arXiv.1706.03762")
    assert await resolver.can_resolve(p2) is True

    async with httpx.AsyncClient() as client:
        c1 = await resolver.resolve(p1, client)
        assert len(c1) == 1
        assert c1[0].url == "https://arxiv.org/pdf/2301.00001v2.pdf"

        c2 = await resolver.resolve(p2, client)
        assert len(c2) == 1
        assert c2[0].url == "https://arxiv.org/pdf/1706.03762.pdf"


@pytest.mark.asyncio
async def test_acl_resolver(test_config: Config):
    resolver = AclResolver(test_config)
    paper = PaperRecord(row_id=1, url="https://aclanthology.org/2020.acl-main.1/")
    assert await resolver.can_resolve(paper) is True

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://aclanthology.org/2020.acl-main.1.pdf"


@pytest.mark.asyncio
async def test_biorxiv_resolver(test_config: Config):
    resolver = BiorxivResolver(test_config)
    paper = PaperRecord(row_id=1, doi="10.1101/2021.01.01.123456")
    assert await resolver.can_resolve(paper) is True

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://www.biorxiv.org/content/10.1101/2021.01.01.123456.full.pdf"


@pytest.mark.asyncio
async def test_pubmed_resolver(test_config: Config):
    resolver = PubmedResolver(test_config)
    paper = PaperRecord(row_id=1, url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7610000/")
    assert await resolver.can_resolve(paper) is True

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7610000/pdf/"


@pytest.mark.asyncio
async def test_open_publishers_resolver(test_config: Config):
    resolver = OpenPublishersResolver(test_config)
    plos_paper = PaperRecord(row_id=1, doi="10.1371/journal.pone.0123456")
    frontiers_paper = PaperRecord(row_id=2, doi="10.3389/fneur.2021.00001")

    assert await resolver.can_resolve(plos_paper) is True
    assert await resolver.can_resolve(frontiers_paper) is True

    async with httpx.AsyncClient() as client:
        plos_cand = await resolver.resolve(plos_paper, client)
        assert len(plos_cand) == 1
        assert "journals.plos.org" in plos_cand[0].url

        frontiers_cand = await resolver.resolve(frontiers_paper, client)
        assert len(frontiers_cand) == 1
        assert "frontiersin.org" in frontiers_cand[0].url


@pytest.mark.asyncio
@respx.mock
async def test_unpaywall_resolver(test_config: Config):
    resolver = UnpaywallResolver(test_config)
    paper = PaperRecord(row_id=1, doi="10.1038/nature12345")

    respx.get("https://api.unpaywall.org/v2/10.1038/nature12345").respond(
        status_code=200,
        json={
            "is_oa": True,
            "best_oa_location": {
                "url_for_pdf": "https://repository.cam.ac.uk/paper.pdf",
                "url_for_landing_page": "https://repository.cam.ac.uk/paper",
            },
        },
    )

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://repository.cam.ac.uk/paper.pdf"
        assert candidates[0].source == "Unpaywall"


@pytest.mark.asyncio
@respx.mock
async def test_openalex_resolver_doi(test_config: Config):
    resolver = OpenAlexResolver(test_config)
    paper = PaperRecord(row_id=1, doi="10.1016/j.artint.2023.103980")

    respx.get("https://api.openalex.org/works/https://doi.org/10.1016/j.artint.2023.103980").respond(
        status_code=200,
        json={
            "id": "W123456789",
            "doi": "https://doi.org/10.1016/j.artint.2023.103980",
            "best_oa_location": {
                "pdf_url": "https://openaccess.ox.ac.uk/article.pdf",
                "landing_page_url": "https://openaccess.ox.ac.uk/article",
            },
        },
    )

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://openaccess.ox.ac.uk/article.pdf"
        assert candidates[0].source == "OpenAlex"


@pytest.mark.asyncio
@respx.mock
async def test_semantic_scholar_resolver_doi(test_config: Config):
    resolver = SemanticScholarResolver(test_config)
    paper = PaperRecord(row_id=1, doi="10.18653/v1/N19-1423")

    respx.get(url__startswith="https://api.semanticscholar.org/graph/v1/paper/DOI:").respond(
        status_code=200,
        json={
            "paperId": "abcdef123456",
            "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "isOpenAccess": True,
            "openAccessPdf": {
                "url": "https://aclanthology.org/N19-1423.pdf",
            },
        },
    )

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://aclanthology.org/N19-1423.pdf"
        assert candidates[0].source == "Semantic Scholar"


@pytest.mark.asyncio
@respx.mock
async def test_crossref_resolver(test_config: Config):
    resolver = CrossrefResolver(test_config)
    paper = PaperRecord(row_id=1, doi="10.1000/182")

    respx.get("https://api.crossref.org/works/10.1000/182").respond(
        status_code=200,
        json={
            "message": {
                "URL": "https://doi.org/10.1000/182",
                "link": [
                    {
                        "URL": "https://example.org/published/10.1000_182.pdf",
                        "content-type": "application/pdf",
                    }
                ],
            }
        },
    )

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://example.org/published/10.1000_182.pdf"


@pytest.mark.asyncio
@respx.mock
async def test_generic_resolver_meta_tags(test_config: Config):
    resolver = GenericResolver(test_config)
    paper = PaperRecord(row_id=1, url="https://university-repo.edu/items/12345")

    html_page = (
        "<!DOCTYPE html><html><head>"
        '<meta name="citation_pdf_url" content="https://university-repo.edu/files/paper.pdf">'
        "</head><body><h1>Academic Paper</h1></body></html>"
    )

    respx.get("https://university-repo.edu/items/12345").respond(
        status_code=200,
        text=html_page,
        headers={"content-type": "text/html"},
    )

    async with httpx.AsyncClient() as client:
        candidates = await resolver.resolve(paper, client)
        assert len(candidates) == 1
        assert candidates[0].url == "https://university-repo.edu/files/paper.pdf"
        assert candidates[0].source == "Landing Page Meta"
