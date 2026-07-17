from pathlib import Path

from spec_sentinel.config import load_config
from spec_sentinel.direction import assess_mechanical_direction
from spec_sentinel.discovery import discover_docs, discover_scope
from spec_sentinel.extractor import extract_claims
from spec_sentinel.models import (
    Direction,
    DirectionAssessment,
    Evidence,
    EvidenceKind,
    SourceLocation,
    Verdict,
    VerificationResult,
)
from spec_sentinel.openapi import OpenApiDocument, OpenApiVerifier
from spec_sentinel.patches import generate_doc_patch

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "drifted-shop"


def _mechanical_divergences():
    config = load_config(DEMO)
    docs = discover_docs(DEMO, config)
    scope = discover_scope(DEMO, config)
    claims = extract_claims(DEMO, docs).claims
    verifier = OpenApiVerifier(OpenApiDocument.load(DEMO, DEMO / "openapi.yaml"))
    pairs = []
    for claim in claims:
        result = verifier.verify(claim)
        if result is not None and result.verdict is Verdict.DIVERGED:
            pairs.append((claim, assess_mechanical_direction(claim, result, DEMO, scope)))
    return docs, pairs


def test_route_and_spec_agreement_marks_docs_stale() -> None:
    _, pairs = _mechanical_divergences()
    assert len(pairs) == 2
    assert all(result.direction is not None for _, result in pairs)
    assert {result.direction.direction for _, result in pairs if result.direction} == {
        Direction.DOCS_STALE
    }


def test_mechanical_docs_stale_findings_get_safe_patches() -> None:
    docs, pairs = _mechanical_divergences()
    patches = [generate_doc_patch(DEMO, claim, result, docs) for claim, result in pairs]
    assert all(patch is not None and not patch.quarantined for patch in patches)
    combined = "\n".join(patch.unified_diff for patch in patches if patch)
    assert "/v1/purchases" in combined
    assert "currency" in combined


def test_agentic_numeric_docs_stale_finding_gets_replacement_patch() -> None:
    config = load_config(DEMO)
    docs = discover_docs(DEMO, config)
    claim = next(
        claim
        for claim in extract_claims(DEMO, docs).claims
        if "defaults to a page size" in claim.text
    )
    evidence = Evidence(
        kind=EvidenceKind.CODE,
        location=SourceLocation(file="app/settings.py", line=5),
        snippet="DEFAULT_PAGE_SIZE = 25",
        supports=False,
    )
    result = VerificationResult(
        claim_id=claim.id,
        verdict=Verdict.DIVERGED,
        confidence=0.99,
        rationale="The implemented default is 25.",
        evidence=[evidence],
        direction=DirectionAssessment(
            direction=Direction.DOCS_STALE,
            confidence=0.99,
            rationale="Code, schema, and tests agree on 25.",
            evidence=[evidence],
        ),
    )
    patch = generate_doc_patch(DEMO, claim, result, docs)
    assert patch is not None
    assert "page size of 25" in patch.unified_diff
    assert not patch.quarantined
