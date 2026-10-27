"""Live progress reporting using Rich."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from paperharvester.models import DownloadStatus


def format_duration(seconds: float) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    secs = int(max(0, seconds))
    mins, s = divmod(secs, 60)
    hrs, m = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


@dataclass
class ProgressStats:
    total: int = 0
    completed: int = 0
    downloaded: int = 0
    failed: int = 0
    duplicates: int = 0
    needs_review: int = 0
    skipped: int = 0
    current_identifier: str = ""
    current_source: str = ""


class ProgressReporter:
    """Displays a rich, live console interface of harvesting progress."""

    def __init__(self, filename: str, total_papers: int, verbose: bool = False) -> None:
        self.filename = filename
        self.total = total_papers
        self.verbose = verbose
        self.stats = ProgressStats(total=total_papers)
        self.start_time = time.monotonic()
        self.console = Console(file=sys.stderr)
        self._is_tty = self.console.is_terminal and not verbose
        self._live: Optional[Live] = None

    def start(self) -> None:
        if self._is_tty:
            self._live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=4,
                transient=False,
            )
            self._live.start()
        else:
            self.console.print(f"[bold cyan]PaperHarvester — {self.filename}[/bold cyan] ({self.total} papers)")

    def stop(self) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.stop()
            self._live = None

    def record_completed(
        self,
        status: DownloadStatus,
        identifier: str,
        source: str,
    ) -> None:
        """Update progress metrics."""
        self.stats.completed += 1
        self.stats.current_identifier = identifier
        self.stats.current_source = source

        if status == DownloadStatus.SUCCESS:
            self.stats.downloaded += 1
        elif status == DownloadStatus.FAILED:
            self.stats.failed += 1
        elif status == DownloadStatus.DUPLICATE:
            self.stats.duplicates += 1
        elif status == DownloadStatus.NEEDS_REVIEW:
            self.stats.needs_review += 1
        elif status == DownloadStatus.SKIPPED:
            self.stats.skipped += 1

        if self._live:
            self._live.update(self._render())
        elif self.verbose or self.stats.completed % 5 == 0 or self.stats.completed == self.total:
            pct = (self.stats.completed / max(1, self.total)) * 100
            self.console.print(
                f"[{self.stats.completed}/{self.total} {pct:.0f}%] "
                f"Downloaded: {self.stats.downloaded} | Failed: {self.stats.failed} | "
                f"Current: {identifier} ({source})"
            )

    def _render(self) -> Panel:
        elapsed = time.monotonic() - self.start_time
        completed = self.stats.completed
        speed = (completed / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, self.total - completed)
        eta_seconds = (remaining / speed) if speed > 0 else 0.0

        percent = (completed / max(1, self.total)) * 100
        bar_width = 24
        filled = int((percent / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Header & progress bar
        text = Text()
        text.append(f"PaperHarvester — {self.filename}\n\n", style="bold cyan")
        text.append("Overall   ", style="bold")
        text.append(f"{bar}  ", style="green")
        text.append(f"{percent:3.0f}%  {completed}/{self.total}\n\n", style="bold white")

        # Stats grid
        table = Table.grid(padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_column("Key2", style="bold")
        table.add_column("Value2")

        table.add_row("Downloaded:", f"[green]{self.stats.downloaded}[/green]", "Current:", self.stats.current_identifier or "—")
        table.add_row("Failed:", f"[red]{self.stats.failed}[/red]", "Source:", self.stats.current_source or "—")
        table.add_row("Duplicates:", f"[yellow]{self.stats.duplicates}[/yellow]", "Speed:", f"{speed:.1f} papers/s")
        table.add_row("Needs review:", f"[magenta]{self.stats.needs_review}[/magenta]", "Elapsed:", format_duration(elapsed))
        table.add_row("Remaining:", f"[white]{remaining}[/white]", "ETA:", format_duration(eta_seconds))

        outer_grid = Table.grid()
        outer_grid.add_row(text)
        outer_grid.add_row(table)

        return Panel(
            outer_grid,
            border_style="blue",
            padding=(1, 2),
        )
