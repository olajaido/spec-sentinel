"""Command-line interface."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from openai import OpenAIError
from rich.console import Console
from rich.table import Table

from spec_sentinel import __version__
from spec_sentinel.config import load_config
from spec_sentinel.delta import ScanArtifact, compare_artifacts, render_markdown
from spec_sentinel.pipeline import ProgressEvent, ScanArtifacts, run_scan

app = typer.Typer(no_args_is_help=True, help="Audit documentation claims against code.")
console = Console()
progress_console = Console(stderr=True)
error_console = Console(stderr=True)
SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _openai_error_summary(error: OpenAIError) -> str:
    """Return diagnostic metadata without echoing credentials from provider messages."""
    summary = type(error).__name__
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        summary += f" (HTTP {status_code})"
    code = getattr(error, "code", None)
    if isinstance(code, str) and SAFE_ERROR_CODE.fullmatch(code):
        summary += f" [{code}]"
    return summary


def version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """Spec Sentinel documentation drift scanner."""


def _execute_scan(
    path: Path,
    config_path: Path | None,
    env_file: Path | None,
    cache_dir: Path | None,
    *,
    agentic: bool,
    use_cache: bool,
    load_env: bool,
    show_progress: bool,
) -> ScanArtifacts:
    root = path.resolve()
    if load_env:
        load_dotenv(env_file.resolve() if env_file is not None else root / ".env", override=False)
    settings = load_config(root, config_path)
    try:
        return run_scan(
            root,
            settings,
            agentic=agentic,
            cache_dir=cache_dir,
            use_cache=use_cache,
            progress=_print_progress if show_progress else None,
        )
    except OpenAIError as error:
        error_console.print(
            f"[bold red]OpenAI request failed:[/bold red] {_openai_error_summary(error)}"
        )
        error_console.print(
            "Check OPENAI_API_KEY, model access, API quota, and network connectivity; "
            "or rerun with --no-agentic."
        )
        raise typer.Exit(code=2) from error
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--cache-dir") from error


def _print_progress(event: ProgressEvent) -> None:
    source = "cache" if event.cached else "model"
    progress_console.print(
        f"[{event.completed}/{event.total}] {event.result.verdict.value} "
        f"({source}) — {event.claim.text[:90]}"
    )


def _print_terminal_report(artifacts: ScanArtifacts) -> None:
    table = Table(title="Documentation claim audit")
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("Claim")
    table.add_column("Source")
    table.add_column("Verdict")
    results = {result.claim_id: result for result in artifacts.results}
    for claim in artifacts.claims:
        source = claim.source_locations[0]
        result = results.get(claim.id)
        verdict = result.verdict.value if result else "pending agentic path"
        table.add_row(
            claim.id,
            claim.type.value,
            claim.text,
            f"{source.file}:{source.line}",
            verdict,
        )
    console.print(table)
    console.print(
        f"[bold]{len(artifacts.claims)}[/bold] claims; "
        f"{artifacts.skipped_statements} non-testable statements skipped; "
        f"{artifacts.pending_claims} pending; {artifacts.elapsed_seconds:.2f}s"
    )
    if artifacts.cache_hits or artifacts.cache_misses:
        console.print(
            f"Cache: {artifacts.cache_hits} hits, {artifacts.cache_misses} misses; "
            f"{artifacts.agentic_requests} model requests"
        )
    if artifacts.patches:
        console.print(f"[bold green]{len(artifacts.patches)} safe patches[/bold green]")
    if artifacts.security_findings:
        console.print(f"[bold red]{len(artifacts.security_findings)} security findings[/bold red]")
    for warning in artifacts.warnings:
        console.print(f"[bold yellow]Warning:[/bold yellow] {warning}")


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False)] = Path("."),
    format: Annotated[str, typer.Option("--format", help="term or json")] = "term",
    config: Annotated[Path | None, typer.Option("--config")] = None,
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", exists=True, dir_okay=False, help="Explicit secrets file."),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", file_okay=False, help="Cache outside the scanned repository."),
    ] = None,
    use_cache: Annotated[
        bool,
        typer.Option("--cache/--no-cache", help="Reuse unchanged agentic verdicts."),
    ] = True,
    load_env: Annotated[
        bool,
        typer.Option(
            "--load-dotenv/--no-load-dotenv",
            help="Load a local .env file; disable this for untrusted CI checkouts.",
        ),
    ] = True,
    agentic: Annotated[
        bool,
        typer.Option(
            "--agentic/--no-agentic",
            help="Run bounded model verification for claims the mechanical path cannot represent.",
        ),
    ] = False,
) -> None:
    """Discover claims and verify them mechanically, with optional behavioural reasoning."""
    if format not in {"term", "json"}:
        raise typer.BadParameter("format must be 'term' or 'json'", param_hint="--format")
    if env_file is not None and not load_env:
        raise typer.BadParameter(
            "--env-file cannot be combined with --no-load-dotenv", param_hint="--env-file"
        )
    artifacts = _execute_scan(
        path,
        config,
        env_file,
        cache_dir,
        agentic=agentic,
        use_cache=use_cache,
        load_env=load_env,
        show_progress=agentic and format == "term",
    )
    if format == "json":
        typer.echo(json.dumps(artifacts.as_dict(), indent=2))
    else:
        _print_terminal_report(artifacts)


@app.command()
def fix(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False)] = Path("."),
    config: Annotated[Path | None, typer.Option("--config")] = None,
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", exists=True, dir_okay=False, help="Explicit secrets file."),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", file_okay=False, help="Cache outside the scanned repository."),
    ] = None,
    use_cache: Annotated[
        bool,
        typer.Option("--cache/--no-cache", help="Reuse unchanged agentic verdicts."),
    ] = True,
    load_env: Annotated[
        bool,
        typer.Option(
            "--load-dotenv/--no-load-dotenv",
            help="Load a local .env file; disable this for untrusted CI checkouts.",
        ),
    ] = True,
    agentic: Annotated[
        bool,
        typer.Option("--agentic/--no-agentic", help="Include behavioural verification."),
    ] = False,
    format: Annotated[str, typer.Option("--format", help="diff or json")] = "diff",
) -> None:
    """Print safe documentation patches without applying them."""
    if format not in {"diff", "json"}:
        raise typer.BadParameter("format must be 'diff' or 'json'", param_hint="--format")
    if env_file is not None and not load_env:
        raise typer.BadParameter(
            "--env-file cannot be combined with --no-load-dotenv", param_hint="--env-file"
        )
    artifacts = _execute_scan(
        path,
        config,
        env_file,
        cache_dir,
        agentic=agentic,
        use_cache=use_cache,
        load_env=load_env,
        show_progress=agentic,
    )
    safe = [patch for patch in artifacts.patches if not patch.quarantined]
    if format == "json":
        typer.echo(json.dumps([patch.model_dump(mode="json") for patch in safe], indent=2))
        return
    if not safe:
        console.print("No safe, patch-eligible documentation divergences were found.")
        return
    typer.echo("\n".join(patch.unified_diff.rstrip() for patch in safe))


@app.command()
def delta(
    baseline: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, help="Complete baseline scan JSON."),
    ],
    current: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, help="Complete current scan JSON."),
    ],
    format: Annotated[str, typer.Option("--format", help="json or md")] = "md",
    fail_on_new_divergence: Annotated[
        bool,
        typer.Option(
            "--fail-on-new-divergence/--no-fail-on-new-divergence",
            help="Exit with status 1 when the current scan introduces a divergence.",
        ),
    ] = False,
) -> None:
    """Compare complete scans and report only newly broken or resolved claims."""
    if format not in {"json", "md"}:
        raise typer.BadParameter("format must be 'json' or 'md'", param_hint="--format")
    try:
        report = compare_artifacts(ScanArtifact.load(baseline), ScanArtifact.load(current))
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error), param_hint="baseline/current") from error
    if format == "json":
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo(render_markdown(report), nl=False)
    if fail_on_new_divergence and report.newly_broken:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
