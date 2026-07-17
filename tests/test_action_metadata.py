import re
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from spec_sentinel.cli import app

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
