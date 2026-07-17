from pathlib import Path

from spec_sentinel.config import load_config
from spec_sentinel.discovery import discover_docs, discover_scope
from spec_sentinel.security import scan_injection_attempts

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "drifted-shop"


def test_demo_canaries_are_reported() -> None:
    config = load_config(DEMO)
    files = sorted(set(discover_docs(DEMO, config) + discover_scope(DEMO, config)))
    findings = scan_injection_attempts(DEMO, files)
    locations = {finding.location.file for finding in findings}
    assert locations == {"README.md", "app/inventory.py"}
    assert {finding.rule for finding in findings} >= {
        "instruction-override",
        "secret-exfiltration",
    }
