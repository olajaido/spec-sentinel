"""Baseline comparison and sanitized GitHub comment rendering."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from spec_sentinel.models import Claim, PatchProposal, Verdict, VerificationResult

COMMENT_MARKER = "<!-- spec-sentinel-report -->"


class ScanArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str
    claims: list[Claim]
    results: list[VerificationResult]
    patches: list[PatchProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pending_claims: int = 0

    @classmethod
    def load(cls, path: Path) -> ScanArtifact:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class DeltaFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["newly_broken", "resolved"]
    claim: Claim
    previous_verdict: Verdict | None
    current_verdict: Verdict | None
    result: VerificationResult | None = None
    patch: PatchProposal | None = None


class DeltaReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    newly_broken: list[DeltaFinding] = Field(default_factory=list)
    resolved: list[DeltaFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def compare_artifacts(baseline: ScanArtifact, current: ScanArtifact) -> DeltaReport:
    _require_complete(baseline, "baseline")
    _require_complete(current, "current")
    baseline_results = {result.claim_id: result for result in baseline.results}
    current_results = {result.claim_id: result for result in current.results}
    baseline_claims = {claim.id: claim for claim in baseline.claims}
    baseline_patches = {patch.claim_id: patch for patch in baseline.patches}
    current_patches = {patch.claim_id: patch for patch in current.patches}
    matched_baseline: set[str] = set()
    current_to_baseline: dict[str, str] = {}

    for claim in current.claims:
        if claim.id in baseline_claims:
            current_to_baseline[claim.id] = claim.id
            matched_baseline.add(claim.id)
            continue
        lineage = _lineage_match(claim, baseline.claims, matched_baseline)
        if lineage is not None:
            current_to_baseline[claim.id] = lineage.id
            matched_baseline.add(lineage.id)

    newly_broken: list[DeltaFinding] = []
    for claim in current.claims:
        result = current_results[claim.id]
        if result.verdict is not Verdict.DIVERGED:
            continue
        baseline_id = current_to_baseline.get(claim.id)
        previous = baseline_results.get(baseline_id) if baseline_id else None
        if previous is not None and previous.verdict is Verdict.DIVERGED:
            continue
        newly_broken.append(
            DeltaFinding(
                status="newly_broken",
                claim=claim,
                previous_verdict=previous.verdict if previous else None,
                current_verdict=result.verdict,
                result=result,
                patch=current_patches.get(claim.id),
            )
        )

    resolved: list[DeltaFinding] = []
    reverse_matches = {
        baseline_id: current_id for current_id, baseline_id in current_to_baseline.items()
    }
    for claim in baseline.claims:
        previous = baseline_results[claim.id]
        if previous.verdict is not Verdict.DIVERGED:
            continue
        current_id = reverse_matches.get(claim.id)
        current_result = current_results.get(current_id) if current_id else None
        if current_result is not None and current_result.verdict is Verdict.DIVERGED:
            continue
        current_claim = next((item for item in current.claims if item.id == current_id), None)
        resolved.append(
            DeltaFinding(
                status="resolved",
                claim=current_claim or claim,
                previous_verdict=previous.verdict,
                current_verdict=current_result.verdict if current_result else None,
                result=current_result,
                patch=baseline_patches.get(claim.id),
            )
        )

    return DeltaReport(
        newly_broken=newly_broken,
        resolved=resolved,
        warnings=current.warnings,
    )


def render_markdown(report: DeltaReport) -> str:
    lines = [COMMENT_MARKER, "## Spec Sentinel", ""]
    if report.warnings:
        lines.extend(["### ⚠️ Audit warning", ""])
        lines.extend(f"- <code>{_safe(warning)}</code>" for warning in report.warnings)
        lines.append("")
    if not report.newly_broken and not report.resolved:
        if report.warnings:
            lines.append("No documentation claim delta was evaluated.")
        else:
            lines.append("✅ No documentation claim regressions introduced by this change.")
        return "\n".join(lines) + "\n"
    if report.newly_broken:
        count = len(report.newly_broken)
        lines.extend([f"### ❌ {count} newly broken claim{'s' if count != 1 else ''}", ""])
        for finding in report.newly_broken:
            result = finding.result
            assert result is not None
            source = finding.claim.source_locations[0]
            lines.extend(
                [
                    f"<code>{_safe(finding.claim.text)}</code>",
                    "",
                    f"- Source: <code>{_safe(source.file)}:{source.line}</code>",
                    f"- Confidence: `{result.confidence:.2f}`",
                    f"- Rationale: <code>{_safe(result.rationale)}</code>",
                ]
            )
            if result.direction is not None:
                lines.append(f"- Direction: `{result.direction.direction.value}`")
            if result.evidence:
                lines.append("- Evidence:")
                for evidence in result.evidence[:5]:
                    location = evidence.location
                    lines.append(
                        f"  - <code>{_safe(location.file)}:{location.line}</code> — "
                        f"<code>{_safe(evidence.snippet[:240])}</code>"
                    )
            if finding.patch is not None and not finding.patch.quarantined:
                lines.append("- Safe documentation patch available in the scan artifact.")
            lines.append("")
    if report.resolved:
        count = len(report.resolved)
        lines.extend([f"### ✅ {count} resolved claim{'s' if count != 1 else ''}", ""])
        for finding in report.resolved:
            source = finding.claim.source_locations[0]
            lines.append(
                f"- <code>{_safe(finding.claim.text)}</code> "
                f"(<code>{_safe(source.file)}:{source.line}</code>)"
            )
    return "\n".join(lines).rstrip() + "\n"


def _require_complete(artifact: ScanArtifact, label: str) -> None:
    if artifact.schema_version != "1.0":
        raise ValueError(f"{label} artifact uses unsupported schema {artifact.schema_version!r}")
    result_ids = {result.claim_id for result in artifact.results}
    claim_ids = {claim.id for claim in artifact.claims}
    if len(result_ids) != len(artifact.results) or len(claim_ids) != len(artifact.claims):
        raise ValueError(f"{label} artifact contains duplicate claim IDs")
    if artifact.pending_claims or result_ids != claim_ids:
        raise ValueError(f"{label} artifact is incomplete; run a full agentic scan")


def _lineage_match(
    current: Claim, baseline: list[Claim], already_matched: set[str]
) -> Claim | None:
    current_source = current.source_locations[0]
    candidates: list[tuple[int, int, Claim]] = []
    for candidate in baseline:
        if candidate.id in already_matched or candidate.type is not current.type:
            continue
        candidate_source = candidate.source_locations[0]
        if candidate_source.file != current_source.file:
            continue
        distance = abs(candidate_source.line - current_source.line)
        if distance > 5:
            continue
        predicate_penalty = int(
            candidate.normalized_assertion.predicate != current.normalized_assertion.predicate
        )
        candidates.append((predicate_penalty, distance, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2].id))
    return candidates[0][2]


def _safe(value: str) -> str:
    return escape(value, quote=True).replace("`", "&#96;")
