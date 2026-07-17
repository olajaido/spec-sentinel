from pathlib import Path

import pytest
from typer.testing import CliRunner

from spec_sentinel.cli import app
from spec_sentinel.delta import ScanArtifact, compare_artifacts, render_markdown
from spec_sentinel.models import (
    Claim,
    ClaimType,
    Direction,
    DirectionAssessment,
    Evidence,
    EvidenceKind,
    NormalizedAssertion,
    SourceLocation,
    Verdict,
    VerificationResult,
)


def claim(
    value: str,
    *,
    line: int = 10,
    text: str | None = None,
    predicate: str = "equals",
) -> Claim:
    assertion = NormalizedAssertion(subject="page_size", predicate=predicate, object=value)
    return Claim(
        id=Claim.stable_id(assertion),
        type=ClaimType.LIMIT,
        text=text or f"The page size is {value}.",
        normalized_assertion=assertion,
        source_locations=[SourceLocation(file="README.md", line=line)],
        confidence=0.99,
    )


def result(item: Claim, verdict: Verdict) -> VerificationResult:
    if verdict is Verdict.DIVERGED:
        evidence = Evidence(
            kind=EvidenceKind.CODE,
            location=SourceLocation(file="src/settings.py", line=4),
            snippet="PAGE_SIZE = 25",
            supports=False,
        )
        return VerificationResult(
            claim_id=item.id,
            verdict=verdict,
            confidence=0.98,
            rationale="The implementation uses a different value.",
            evidence=[evidence],
            direction=DirectionAssessment(
                direction=Direction.DOCS_STALE,
                confidence=0.95,
                rationale="The implementation and tests agree.",
                evidence=[evidence],
            ),
        )
    return VerificationResult(
        claim_id=item.id,
        verdict=verdict,
        confidence=0.98,
        rationale="The implementation agrees.",
    )


def artifact(
    items: list[tuple[Claim, Verdict]], *, pending: int = 0, warnings: list[str] | None = None
) -> ScanArtifact:
    return ScanArtifact(
        schema_version="1.0",
        claims=[item for item, _ in items],
        results=[result(item, verdict) for item, verdict in items],
        pending_claims=pending,
        warnings=warnings or [],
    )


def test_existing_divergence_is_not_reported_as_new() -> None:
    item = claim("50")

    report = compare_artifacts(
        artifact([(item, Verdict.DIVERGED)]),
        artifact([(item, Verdict.DIVERGED)]),
    )

    assert report.newly_broken == []
    assert report.resolved == []


def test_verified_claim_becoming_diverged_is_newly_broken() -> None:
    item = claim("50")

    report = compare_artifacts(
        artifact([(item, Verdict.VERIFIED)]),
        artifact([(item, Verdict.DIVERGED)]),
    )

    assert [finding.claim.id for finding in report.newly_broken] == [item.id]
    assert report.resolved == []


def test_edited_claim_is_matched_by_source_lineage_and_resolved() -> None:
    old = claim("50", line=20)
    new = claim("25", line=22)

    report = compare_artifacts(
        artifact([(old, Verdict.DIVERGED)]),
        artifact([(new, Verdict.VERIFIED)]),
    )

    assert report.newly_broken == []
    assert [finding.claim.id for finding in report.resolved] == [new.id]


def test_incomplete_artifact_is_rejected() -> None:
    item = claim("50")
    baseline = artifact([(item, Verdict.VERIFIED)], pending=1)

    with pytest.raises(ValueError, match="baseline artifact is incomplete"):
        compare_artifacts(baseline, artifact([(item, Verdict.VERIFIED)]))


def test_unknown_artifact_schema_is_rejected() -> None:
    item = claim("50")
    baseline = artifact([(item, Verdict.VERIFIED)])
    baseline.schema_version = "2.0"

    with pytest.raises(ValueError, match="unsupported schema"):
        compare_artifacts(baseline, artifact([(item, Verdict.VERIFIED)]))


def test_markdown_escapes_repository_controlled_content() -> None:
    item = claim("50", text="<script>alert(`owned`)</script>")
    report = compare_artifacts(
        artifact([(item, Verdict.VERIFIED)]),
        artifact([(item, Verdict.DIVERGED)]),
    )

    markdown = render_markdown(report)

    assert markdown.startswith("<!-- spec-sentinel-report -->")
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "&#96;owned&#96;" in markdown


def test_markdown_warns_instead_of_showing_green_when_nothing_was_audited() -> None:
    warning = "No testable documentation found. Configure documentation paths."
    report = compare_artifacts(artifact([]), artifact([], warnings=[warning]))

    markdown = render_markdown(report)

    assert "⚠️ Audit warning" in markdown
    assert warning in markdown
    assert "No documentation claim delta was evaluated." in markdown
    assert "✅" not in markdown


def test_delta_cli_can_fail_on_new_divergence(tmp_path: Path) -> None:
    item = claim("50")
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(artifact([(item, Verdict.VERIFIED)]).model_dump_json(), encoding="utf-8")
    current.write_text(artifact([(item, Verdict.DIVERGED)]).model_dump_json(), encoding="utf-8")

    invocation = CliRunner().invoke(
        app,
        [
            "delta",
            str(baseline),
            str(current),
            "--format",
            "md",
            "--fail-on-new-divergence",
        ],
    )

    assert invocation.exit_code == 1
    assert "1 newly broken claim" in invocation.stdout
