"""Command-line interface for PaperHarvester."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from paperharvester.config import Config
from paperharvester.pipeline import Pipeline


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="paperharvester",
        description="Download academic papers from CSV files with multi-source fallback resolution.",
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the CSV file containing bibliographic paper records.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Maximum concurrent download workers (default: 5).",
    )
    parser.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=True,
        help="Resume prior run without re-downloading valid existing PDFs (default: True).",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Disable resume; reprocess all entries.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        default=False,
        help="Retry only papers that previously failed or need review.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Resolve candidates without downloading or saving PDF files.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP request and download timeout in seconds (default: 30.0).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries for transient HTTP/network failures (default: 3).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Custom output directory (default: papers/<csv_stem>/).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose debug logging.",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.csv_path.exists():
        Console(file=sys.stderr).print(f"[bold red]Error:[/bold red] CSV file not found: {args.csv_path}")
        return 1

    config = Config(
        csv_path=args.csv_path,
        output_dir=args.output_dir,
        workers=args.workers,
        timeout=args.timeout,
        max_retries=args.max_retries,
        resume=args.resume,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    pipeline = Pipeline(config)
    try:
        summary = asyncio.run(pipeline.run())
    except KeyboardInterrupt:
        Console().print("\n[bold yellow]Harvester interrupted by user.[/bold yellow]")
        return 130
    except Exception as exc:
        Console(file=sys.stderr).print(f"[bold red]Harvester encountered a fatal error:[/bold red] {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    console = Console()
    console.print("\n")

    table = Table(title="[bold green]PaperHarvester Summary[/bold green]", show_header=True)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Total CSV Rows", str(summary.get("total_rows", 0)))
    table.add_row("Successfully Downloaded", f"[green]{summary.get('success', 0)}[/green]")
    table.add_row("Failed / Unresolved", f"[red]{summary.get('failed', 0)}[/red]")
    table.add_row("Duplicates Linked", f"[yellow]{summary.get('duplicates', 0)}[/yellow]")
    table.add_row("Skipped (Existing)", f"[blue]{summary.get('skipped', 0)}[/blue]")
    table.add_row("Needs Review", f"[magenta]{summary.get('needs_review', 0)}[/magenta]")
    table.add_row("Elapsed Time", f"{summary.get('elapsed_seconds', 0):.1f}s")
    table.add_row("Output Directory", str(pipeline.storage.base_dir))

    console.print(table)
    console.print(f"[dim]Results saved to {pipeline.storage.results_csv_path} and {pipeline.storage.failed_csv_path}[/dim]\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
