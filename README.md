# PaperHarvester

Production-quality academic paper downloader with multi-source fallback resolution, resumable execution, atomic persistence, live progress reporting, and PDF integrity validation.

---

## 1. Core Principles

- **Correctness Over Volume**: Never silently download an unrelated paper or corrupt file.
- **Strict Legal Compliance**: Does not bypass paywalls, solve CAPTCHAs, or access shadow libraries (Sci-Hub). All downloads use legitimate open-access repositories, preprints, publisher OA endpoints, and discovery APIs.
- **Recoverability & State Safety**: Downloads write atomically via `.part` files. Manifest and CSV logs are persisted immediately, making runs completely safe to interrupt with `Ctrl+C` and resume later.

---

## 2. Installation

Requires Python 3.10+.

### Using `uv` (Recommended)

```bash
# Clone or navigate to the repository
cd PaperHarvester

# Install dependencies into virtual environment
uv sync
```

### Using standard `pip`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 3. CLI Usage

The primary interface supports both `python main.py` and the installed CLI command `paperharvester`:

```bash
# Basic run with default 5 workers
python main.py /path/to/papers.csv

# Or using the package executable
paperharvester /path/to/papers.csv
```

### Command-Line Flags

| Flag | Default | Description |
|---|---|---|
| `csv_path` | *(required)* | Path to input CSV containing paper records |
| `--workers` | `5` | Maximum concurrent download workers |
| `--resume` | `True` | Resume prior run without re-downloading valid existing PDFs |
| `--no-resume` | `False` | Disable resume cache; reprocess all records |
| `--retry-failed` | `False` | Retry only records that previously failed or need review |
| `--dry-run` | `False` | Discover and validate candidate URLs without downloading files |
| `--timeout` | `30.0` | HTTP request and streaming download timeout (seconds) |
| `--max-retries` | `3` | Maximum retries with exponential backoff on transient errors |
| `--output-dir` | `papers/<stem>/` | Custom target directory for PDFs and reports |
| `-v, --verbose` | `False` | Enable detailed debug logs |

### Usage Examples

```bash
# Run with 8 workers and verbose logging
python main.py data/nlp_papers.csv --workers 8 --verbose

# Dry run to preview candidate URLs without saving PDFs
python main.py data/nlp_papers.csv --dry-run

# Resume an interrupted harvest
python main.py data/nlp_papers.csv --resume

# Retry only papers that failed on a previous attempt
python main.py data/nlp_papers.csv --retry-failed

# Save outputs to a custom destination
python main.py data/nlp_papers.csv --output-dir /Volumes/Research/nlp_papers
```

---

## 4. Input CSV Format

The parser handles standard academic export formats (Zotero, Mendeley, Google Scholar, Semantic Scholar). Column headers are matched flexibly and case-insensitively while preserving all original columns in order.

Expected columns:
```text
Cite Key, Title, Authors, Year, Publication Date,
Journal, Volume, Pages, Abstract, Citation Count,
Citations/Year, DOI, URL, Relevance Score
```

*Note: Only `Title` or an identifier (`DOI`, `URL`, `Cite Key`) is required to attempt resolution.*

---

## 5. Supported Sources & Resolvers

PaperHarvester resolves PDFs via an ordered adapter pipeline:

1. **Direct PDF**: Detects direct PDF links (`.pdf` URLs, printable formats).
2. **arXiv**: Canonical IDs from URLs (`abs/` or `pdf/`) and DOIs (`10.48550/arXiv.*`).
3. **ACL Anthology**: Canonical paper pages (`aclanthology.org/{id}`) to direct PDFs.
4. **bioRxiv / medRxiv**: Preprint landing pages and DOI prefix `10.1101/`.
5. **PubMed Central (PMC)**: Europe PMC API queries and official PMC full-text PDFs.
6. **OA Publishers**: Dedicated adapters for PLOS (`10.1371`), Frontiers (`10.3389`), MDPI (`10.3390`).
7. **Unpaywall API**: Resolves official OA locations and repository full-text links.
8. **OpenAlex API**: DOI lookup and normalized title search matching open-access locations.
9. **Semantic Scholar Graph API**: DOI and title search extracting `openAccessPdf`.
10. **Crossref API**: Official publisher landing pages and open-access links.
11. **Generic Landing Pages**: Discovers `<meta name="citation_pdf_url">`, `<meta name="eprints.document_url">`, and institutional repository links.

---

## 6. Output Directory Structure

For an input file `data/legal_nlp.csv`, the output directory defaults to `papers/legal_nlp/`:

```text
papers/
└── legal_nlp/
    ├── pdfs/
    │   ├── smith2024_policy_reasoning.pdf
    │   ├── devlin2019_bert_pretraining.pdf
    │   └── ...
    ├── results.csv       # Complete row-by-row harvest log
    ├── failed.csv        # Detailed failure export with manual access URLs
    ├── manifest.jsonl    # Line-delimited audit trail
    ├── summary.json      # Aggregated run metrics & source distributions
    ├── download.log      # Execution and diagnostic logs
    ├── .quarantine/      # Rejected corrupt or mismatched files
    └── .cache/
```

### `results.csv`
Contains **all original input columns** plus 10 standardized harvest columns:
- `download_status`: `SUCCESS`, `FAILED`, `SKIPPED`, `DUPLICATE`, `NEEDS_REVIEW`
- `local_pdf_path`: Absolute or relative path to downloaded file
- `source_used`: The specific adapter or provider utilized
- `resolved_pdf_url`: The verified URL from which the PDF was downloaded
- `matched_identifier`: DOI, arXiv ID, or paper ID matched
- `match_confidence`: Match score (0.0 to 1.0)
- `file_size`: Final size on disk in bytes
- `sha256`: SHA-256 hash of the downloaded file
- `attempt_count`: Number of download attempts
- `last_attempt_at`: ISO 8601 UTC timestamp

### `failed.csv`
Contains **all original input columns** plus diagnostic columns:
- `download_status`: `FAILED` or `NEEDS_REVIEW`
- `failure_reason`: Human-readable explanation of why download could not complete
- `failure_category`: Machine-readable category:
  `NOT_FOUND`, `PAYWALLED`, `RATE_LIMITED`, `TIMEOUT`, `NETWORK_ERROR`, `INVALID_PDF`, `METADATA_MISMATCH`, `ACCESS_BLOCKED`, `AMBIGUOUS_MATCH`, `UNSUPPORTED_SOURCE`, `UNKNOWN_ERROR`
- `attempted_sources`: Semicolon-separated list of adapters queried
- `attempted_urls`: Semicolon-separated list of download endpoints attempted
- `http_status`: Last HTTP status code returned
- `error_message`: Underlying error string
- `retry_count`: Total retry attempts
- `suggested_manual_url`: Best available official landing page for manual access

---

## 7. Environment Configuration

Copy [.env.example](file:///.env.example) to `.env` to configure optional provider credentials:

```bash
# Contact email sent in User-Agent header for polite API access
HARVESTER_EMAIL=researcher@university.edu

# Optional Semantic Scholar API Key (increases rate limits from 1 req/s to 100 req/s)
SEMANTIC_SCHOLAR_API_KEY=your_key_here
```

---

## 8. Validation & Safety Architecture

- **SSRF Prevention**: All candidate URLs are verified to prevent requests to loopback (`127.0.0.1`, `localhost`), link-local, private LAN subnets (`10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`), or non-HTTP schemes.
- **Magic Byte & PDF Structure Check**: Verifies `%PDF-` header bytes and parses structure with `pypdf`.
- **HTML Masquerade Detection**: Detects paywall portals, Cloudflare challenges, and access denied messages returned with `.pdf` file extensions.
- **Metadata Title Verification**: Checks extracted first-page text and PDF metadata against expected paper title to catch mismatched downloads.
- **Atomic File Writing**: Files are streamed into `<filename>.pdf.part` and renamed via `os.replace` only upon complete, error-free validation.
- **Deduplication**: Identical papers (by DOI, arXiv ID, normalized title, or SHA-256) appearing across multiple rows are downloaded only once and linked.

---

## 9. Testing

Run the test suite with `pytest`:

```bash
uv run pytest
```

The test suite covers:
- Direct arXiv & ACL resolution
- Unpaywall, OpenAlex, Semantic Scholar, and Crossref fallback resolution
- HTML paywall / challenge detection
- PDF structural validation & title mismatch checks
- SSRF and private network blocking
- Streaming downloads, rate limiting, and HTTP 429 backoff
- End-to-end pipeline execution with mocked APIs
- Deduplication and resume logic

To run the optional live integration test against public servers:

```bash
uv run pytest -m live
```
