"""Direction-gated, constrained documentation patch generation."""

from __future__ import annotations

import re
from difflib import unified_diff
from pathlib import Path

from spec_sentinel.models import (
    Claim,
    Direction,
    EvidenceKind,
    PatchProposal,
    Verdict,
    VerificationResult,
)

DANGEROUS_ADDITIONS = ("<script", "curl |", "curl -", "wget |", "javascript:")


def generate_doc_patch(
    root: Path,
    claim: Claim,
    result: VerificationResult,
    docs: list[Path],
) -> PatchProposal | None:
    if (
        result.verdict is not Verdict.DIVERGED
        or result.direction is None
        or result.direction.direction is not Direction.DOCS_STALE
    ):
        return None
    root = root.resolve()
    allowed = {path.resolve().relative_to(root).as_posix(): path.resolve() for path in docs}
    source = claim.source_locations[0]
    path = allowed.get(source.file)
    if path is None:
        return None
    original_text = path.read_text(encoding="utf-8")
    original = original_text.splitlines(keepends=True)
    if source.line > len(original):
        return None
    replacement = _replacement_line(claim, result, original[source.line - 1])
    if replacement is None:
        return None
    revised = original.copy()
    if replacement == "":
        del revised[source.line - 1]
    else:
        revised[source.line - 1] = replacement
    diff = "".join(
        unified_diff(
            original,
            revised,
            fromfile=f"a/{source.file}",
            tofile=f"b/{source.file}",
            lineterm="\n",
        )
    )
    quarantine_reason = _quarantine_reason(original_text, "".join(revised), diff)
    return PatchProposal(
        claim_id=claim.id,
        file=source.file,
        unified_diff=diff,
        rationale=result.direction.rationale,
        quarantined=quarantine_reason is not None,
        quarantine_reason=quarantine_reason,
    )


def _replacement_line(claim: Claim, result: VerificationResult, original: str) -> str | None:
    parameter = claim.normalized_assertion.qualifiers.get("parameter")
    if isinstance(parameter, str) and "does not declare parameter" in result.rationale:
        return ""
    expected_path = claim.normalized_assertion.qualifiers.get("path")
    if isinstance(expected_path, str):
        for evidence in result.evidence:
            alternative = evidence.snippet.strip().strip("'\"").removesuffix(":")
            if alternative.startswith("/") and alternative != expected_path:
                return original.replace(expected_path, alternative)
    expected_value = claim.normalized_assertion.object
    if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
        for evidence in result.evidence:
            if evidence.supports or evidence.kind not in {EvidenceKind.CODE, EvidenceKind.SPEC}:
                continue
            match = re.search(r"(?:=\s*|default:\s*)(\d+(?:\.\d+)?)", evidence.snippet)
            if match is None:
                continue
            replacement_value = match.group(1)
            if replacement_value == str(expected_value):
                continue
            replaced = re.sub(
                rf"(?<![\w.]){re.escape(str(expected_value))}(?!\.\d)(?!\w)",
                replacement_value,
                original,
                count=1,
            )
            if replaced != original:
                return replaced
    return None


def _quarantine_reason(before: str, after: str, diff: str) -> str | None:
    before_urls = {word for word in before.split() if word.startswith(("http://", "https://"))}
    after_urls = {word for word in after.split() if word.startswith(("http://", "https://"))}
    if after_urls - before_urls:
        return "patch introduces a URL not present in the source document"
    added = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    if any(token in added.casefold() for token in DANGEROUS_ADDITIONS):
        return "patch introduces executable or unsafe content"
    return None
