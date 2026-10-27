"""PaperHarvester — Production-quality academic paper downloader."""

from paperharvester.cli import main
from paperharvester.config import Config
from paperharvester.models import DownloadStatus, FailureCategory, PaperRecord, PaperResult
from paperharvester.pipeline import Pipeline

__version__ = "0.1.0"
__all__ = [
    "main",
    "Config",
    "Pipeline",
    "PaperRecord",
    "PaperResult",
    "DownloadStatus",
    "FailureCategory",
]
