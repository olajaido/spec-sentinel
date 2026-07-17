import re
import subprocess
from pathlib import Path

import yaml
from openai import OpenAIError
from typer.testing import CliRunner

from spec_sentinel.cli import _openai_error_summary, app

ROOT = Path(__file__).parents[1]


def test_composite_action_is_pinned_and_disables_untrusted_dotenv() -> None:
    metadata = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))

    assert metadata["runs"]["using"] == "composite"
    steps = metadata["runs"]["steps"]
    external_uses = [step["uses"] for step in steps if "uses" in step]
    assert external_uses
    assert all(re.search(r"@[0-9a-f]{40}$", value) for value in external_uses)
    scan_commands = [step["run"] for step in steps if "Scan" in step["name"]]
    assert scan_commands
    assert all("--no-load-dotenv" in command for command in scan_commands)
    current_scan = next(step for step in steps if step["name"] == "Scan current checkout")
    assert "OPENAI_API_KEY is unavailable" in current_scan["run"]
    assert "could not complete the current scan" in current_scan["run"]
    setup_uv = next(step for step in steps if step["name"] == "Set up uv")
    assert setup_uv["with"]["cache-dependency-glob"] == "${{ github.action_path }}/uv.lock"
    comment_step = next(
        step for step in steps if step["name"] == "Update persistent pull-request comment"
    )
    assert "getAuthenticated" not in comment_step["with"]["script"]
    assert "github-actions[bot]" in comment_step["with"]["script"]
    for step in steps:
        if command := step.get("run"):
            subprocess.run(["bash", "-n", "-c", command], check=True)


def test_workflow_keeps_executable_action_on_trusted_revision() -> None:
    workflow = (ROOT / ".github" / "workflows" / "spec-sentinel.yml").read_text(encoding="utf-8")

    assert "github.event.pull_request.base.sha || github.sha" in workflow
    assert "uses: ./.spec-sentinel-action" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull_request_target" not in workflow


def test_explicit_env_file_cannot_be_combined_with_disabled_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=not-a-real-secret\n", encoding="utf-8")

    invocation = CliRunner().invoke(
        app,
        [
            "scan",
            str(ROOT / "examples" / "drifted-shop"),
            "--env-file",
            str(env_file),
            "--no-load-dotenv",
        ],
    )

    assert invocation.exit_code == 2
    assert "cannot be combined" in invocation.output


def test_openai_error_summary_never_echoes_provider_message() -> None:
    error = OpenAIError("secret-bearing provider message")

    summary = _openai_error_summary(error)

    assert summary == "OpenAIError"
    assert "secret-bearing" not in summary


def test_openai_error_summary_includes_only_safe_error_code() -> None:
    class CodedOpenAIError(OpenAIError):
        status_code = 429
        code = "insufficient_quota"

    summary = _openai_error_summary(CodedOpenAIError("private provider details"))

    assert summary == "CodedOpenAIError (HTTP 429) [insufficient_quota]"
    assert "private provider details" not in summary

    CodedOpenAIError.code = "unsafe secret with spaces"
    assert _openai_error_summary(CodedOpenAIError("private")) == "CodedOpenAIError (HTTP 429)"
