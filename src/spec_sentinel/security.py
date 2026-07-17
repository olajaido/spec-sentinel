"""Static prompt-injection canary detection for untrusted repository text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spec_sentinel.models import SecurityFinding, SourceLocation


@dataclass(frozen=True)
class InjectionRule:
    name: str
    pattern: re.Pattern[str]
    severity: str
    explanation: str


RULES = (
    InjectionRule(
        name="instruction-override",
        pattern=re.compile(
            r"(?:ignore|disregard|override).{0,60}(?:instructions?|prompt)|"
            r"(?:mark|classify).{0,40}(?:claim|verdict).{0,30}(?:verified|diverged)",
            re.I,
        ),
        severity="high",
        explanation="Repository text attempts to override verifier instructions or verdicts.",
    ),
    InjectionRule(
        name="secret-exfiltration",
        pattern=re.compile(
            r"(?:print|read|show|emit|disclose|expose).{0,50}(?:github_token|api[_ -]?key|"
            r"environment variables?|\.ssh/|id_rsa|credentials?)",
            re.I,
        ),
        severity="critical",
        explanation="Repository text asks the verifier to disclose credentials or external files.",
    ),
)


def scan_injection_attempts(root: Path, files: list[Path]) -> list[SecurityFinding]:
    root = root.resolve()
    findings: list[SecurityFinding] = []
    seen: set[tuple[str, int, str]] = set()
    for file in files:
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        relative = file.resolve().relative_to(root).as_posix()
        for line_number, line in enumerate(lines, 1):
            for rule in RULES:
                if not rule.pattern.search(line):
                    continue
                identity = (relative, line_number, rule.name)
                if identity in seen:
                    continue
                seen.add(identity)
                findings.append(
                    SecurityFinding(
                        rule=rule.name,
                        severity=rule.severity,
                        location=SourceLocation(file=relative, line=line_number),
                        explanation=rule.explanation,
                    )
                )
    return findings
