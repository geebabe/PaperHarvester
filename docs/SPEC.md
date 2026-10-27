# PaperHarvester — Engineering Specification

## 1. Objective

Build a production-quality Python CLI tool that downloads academic papers from a CSV file containing bibliographic metadata and paper URLs.

The tool must support heterogeneous academic sources, multiple fallback strategies, resumable execution, detailed progress reporting, PDF validation, and structured failure exports.

Prioritize **correctness, reliability, and recoverability** over maximizing the download count. Never silently download a different paper.

## 2. CLI Interface

Primary usage:

```bash
python main.py /path/to/papers.csv
```

Optional flags:

```bash
python main.py papers.csv --workers 5
python main.py papers.csv --resume
python main.py papers.csv --retry-failed
python main.py papers.csv --dry-run
python main.py papers.csv --timeout 30
python main.py papers.csv --max-retries 3
python main.py papers.csv --verbose
```

The default output directory must be:

`papers/<csv_stem>/`

For example, `data/legal_nlp.csv` produces `papers/legal_nlp/`, relative to the current working directory.

Allow an optional `--output-dir` override.

## 3. Input Format

Expected columns:

```text
Cite Key, Title, Authors, Year, Publication Date,
Journal, Volume, Pages, Abstract, Citation Count,
Citations/Year, DOI, URL, Relevance Score
```

Only `Title` or another usable identifier (DOI, URL, Cite Key) is required to attempt resolution.

Requirements:

- Use Python's CSV parser or pandas with correct quoting and UTF-8 BOM handling.
- Preserve every original column and row.
- Handle empty fields, malformed DOI strings, duplicated records, missing URLs, Unicode titles, and quoted commas.
- Preserve CSV row order and stable row identifiers.
- Normalize DOI and URLs without altering the original metadata.

## 4. Supported Sources

Implement source-specific resolvers using a modular adapter architecture.

| Source | Strategy |
|---|---|
| arXiv | Parse paper ID, resolve version, download PDF |
| ACL Anthology | Parse Anthology ID and obtain PDF |
| Semantic Scholar | Academic Graph API, `openAccessPdf` |
| OpenAlex | Resolve DOI/title, use OA locations |
| Crossref | Resolve DOI and publisher landing page |
| Unpaywall | Find legal open-access PDF |
| PubMed Central | Official open-access full-text sources |
| bioRxiv / medRxiv | Recognize preprint landing and PDF links |
| PLOS / Frontiers / MDPI | Public full-text or PDF links |
| Springer / Nature / Elsevier / IEEE / ACM | Attempt publicly accessible PDFs and lawful OA alternatives |
| Direct PDF URLs | Download and validate directly |
| Generic landing pages | Extract PDF links using HTML metadata |

Do not bypass paywalls, CAPTCHAs, authentication, or anti-bot restrictions. Never use Sci-Hub or shadow libraries.

API keys and provider email addresses must be configured through environment variables when required.

## 5. Download Resolution Pipeline

For each CSV row, execute the following pipeline:

**Step 1 — Normalize identifiers**

Extract and normalize DOI, arXiv ID, ACL Anthology ID, Semantic Scholar ID, and URL. Detect the URL's provider.

**Step 2 — Direct resolution**

Attempt source-specific resolution first. Examples:

- arXiv abstract URL → arXiv PDF endpoint
- ACL Anthology paper page → corresponding PDF
- Semantic Scholar paper → `openAccessPdf`
- DOI URL → official metadata and OA discovery

**Step 3 — Metadata-based fallback**

If the primary URL fails, use the DOI with OpenAlex, Unpaywall, or Semantic Scholar. If DOI is unavailable, search by normalized paper title, optionally using author and year.

Use a confidence-based match to reject unrelated papers. Prefer exact DOI/identifier matches; ambiguous title matches should be reported for manual review.

**Step 4 — Download**

Download the most credible verified PDF candidate.

Requirements:

- HTTP redirects and timeouts
- Streaming downloads
- Rate limiting per provider
- HTTP 429 handling using `Retry-After`
- Exponential backoff with jitter
- Retry temporary network/server failures
- Realistic user-agent identification
- Safe URL validation to prevent SSRF
- Atomic file writes using `.part` files

**Step 5 — Validate**

Verify that the downloaded file:

- Is a genuine, readable PDF, not HTML or a CAPTCHA
- Is non-empty and structurally valid
- Matches the expected paper's identity where reasonably possible
- Is not an unrelated paper or supplementary file

Use PDF metadata or first-page extracted text as an additional title-verification signal where appropriate.

Quarantine suspicious files rather than counting them as successful.

**Step 6 — Record**

Persist the outcome immediately, including successful source, final URL, file path, attempts, and any errors.

## 6. Output Structure

```text
papers/
└── legal_nlp/
    ├── pdfs/
    │   ├── smith2024_policy_reasoning.pdf
    │   ├── nguyen2025_legal_agents.pdf
    │   └── ...
    ├── failed.csv
    ├── results.csv
    ├── manifest.jsonl
    ├── summary.json
    ├── download.log
    └── .cache/
```

Use `Cite Key` plus a sanitized short title for filenames. If the cite key is missing, generate a deterministic identifier using DOI or a stable hash.

Never overwrite distinct papers with colliding filenames.

### failed.csv

Include **all original CSV columns**, plus:

```text
download_status
failure_reason
failure_category
attempted_sources
attempted_urls
http_status
error_message
retry_count
suggested_manual_url
```

Failure categories should include:

- `NOT_FOUND`
- `PAYWALLED`
- `RATE_LIMITED`
- `TIMEOUT`
- `NETWORK_ERROR`
- `INVALID_PDF`
- `METADATA_MISMATCH`
- `ACCESS_BLOCKED`
- `AMBIGUOUS_MATCH`
- `UNSUPPORTED_SOURCE`
- `UNKNOWN_ERROR`

If a paper has a valid landing page but no downloadable PDF, preserve its best manual-access URL.

### results.csv

Include every original row with additional information:

```text
download_status
local_pdf_path
source_used
resolved_pdf_url
matched_identifier
match_confidence
file_size
sha256
attempt_count
last_attempt_at
```

Statuses: `SUCCESS`, `FAILED`, `SKIPPED`, `DUPLICATE`, `NEEDS_REVIEW`.

### summary.json

Record total rows, successes, failures, duplicates, skipped records, unresolved papers, source distribution, elapsed time, and failure categories.

## 7. Live Progress Reporting

Use Rich or tqdm to display real-time progress.

Example:

```text
PaperHarvester — legal_nlp.csv

Overall   ███████████░░░░░░  65%  130/200

Downloaded:     112
Failed:          11
Duplicates:       5
Needs review:     2
Remaining:       70

Current: arXiv:2401.12345
Source:  arXiv
Speed:   2.3 papers/s
Elapsed: 01:12
ETA:     00:39
```

Progress should be based on completed CSV rows, not merely download attempts.

Support a clean terminal view and detailed `--verbose` logs.

## 8. Resume, Retries, and Deduplication

The process must be safe to interrupt with Ctrl+C.

- Persist state after each completed paper.
- Resume without downloading valid completed PDFs again.
- Revalidate existing files before skipping.
- `--retry-failed` retries only failed or unresolved records.
- Avoid duplicate downloads using DOI, arXiv ID, normalized title, and SHA-256.
- Keep separate CSV row records even when multiple rows resolve to the same paper.
- Handle stale `.part` files and interrupted downloads.
- Save state atomically to avoid corruption.

Apply bounded concurrency with `asyncio` + `httpx`, or another justified approach. Default to five workers, while enforcing conservative provider-specific limits.

## 9. Additional Edge Cases

Explicitly handle:

1. URL points to an abstract or landing page, not a PDF.
2. URL redirects to a publisher's paywall.
3. DOI and URL refer to different papers.
4. A URL is dead, but DOI or title resolution succeeds.
5. A paper has multiple arXiv versions.
6. A preprint and published paper have different titles.
7. One paper appears in multiple CSV rows.
8. Returned content is HTML with a `.pdf` filename.
9. A PDF is password-protected, corrupted, or incomplete.
10. A paper has no DOI and no URL.
11. Multiple title-search results are highly similar.
12. Provider returns 403, 404, 429, or 5xx.
13. Network connection drops mid-download.
14. A source links to supplementary materials instead of the main paper.
15. CSV contains invalid URLs or unsafe filename characters.
16. Publishers reject automated requests.
17. The process is interrupted and restarted.
18. A PDF already exists but belongs to a different paper.
19. There are non-English titles, Unicode characters, or very long filenames.
20. No legally accessible full-text copy exists.

Never treat an unverified or suspicious PDF as a successful download.

## 10. Architecture

Use a modular Python package, not a monolithic script.

Suggested structure:

```text
paperharvester/
├── main.py
├── pyproject.toml
├── README.md
├── .env.example
├── paperharvester/
│   ├── cli.py
│   ├── models.py
│   ├── pipeline.py
│   ├── downloader.py
│   ├── validators.py
│   ├── matcher.py
│   ├── storage.py
│   ├── progress.py
│   ├── config.py
│   └── resolvers/
│       ├── base.py
│       ├── arxiv.py
│       ├── acl.py
│       ├── semantic_scholar.py
│       ├── openalex.py
│       ├── unpaywall.py
│       ├── pubmed.py
│       └── generic.py
└── tests/
```

Each resolver should expose a shared interface and return structured PDF candidates with provenance and confidence scores.

Separate discovery, identity matching, download, validation, and persistence so additional providers can be added later.

Do not use an LLM for ordinary paper resolution. Prefer deterministic identifiers, APIs, and metadata matching.

## 11. Testing Requirements

Use pytest with mocked HTTP responses and temporary CSV fixtures.

Test direct arXiv/ACL downloads, Semantic Scholar and OpenAlex fallbacks, invalid PDFs, network failures, paywalls, duplicate rows, interrupted execution, CSV exports, and mismatched metadata.

Include an optional small live integration smoke test, clearly separated from deterministic automated tests.

Do not ship placeholder resolvers that silently claim success.

## 12. Acceptance Criteria

The implementation is complete when:

- A user can run the CLI using only a CSV path.
- PDFs are saved under `papers/<csv_stem>/pdfs/`.
- Progress displays live success/failure counts.
- Every input row appears in `results.csv`.
- Every unresolved paper appears in `failed.csv`.
- Failed entries retain original metadata and useful manual links.
- Successfully downloaded files pass PDF integrity checks.
- Re-running does not repeat completed work unnecessarily.
- Interrupted downloads can be recovered.
- Fallback resolution works for the major supported sources.
- Tests and README usage instructions are provided.

## 13. Implementation Instructions

Build a working end-to-end implementation, not merely an architectural proposal.

Implement in this order:

1. CLI, CSV ingestion, manifest, and output structure.
2. arXiv, ACL Anthology, and direct PDF downloading.
3. Semantic Scholar, OpenAlex, DOI, and Unpaywall fallbacks.
4. Generic landing-page detection and remaining providers.
5. Progress UI, resume, deduplication, PDF validation, and CSV reports.
6. Automated tests and realistic end-to-end validation.

Do not spend time building a GUI, dashboard, database server, or other unnecessary infrastructure.

Use clean, typed, documented code with minimal dependencies.

When finished, provide the exact installation command, CLI usage examples, tests run, supported sources, and any remaining limitations.
