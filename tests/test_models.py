import pytest
from pydantic import ValidationError

from spec_sentinel.models import (
    Claim,
    Direction,
    DirectionAssessment,
    Evidence,
    EvidenceKind,
    NormalizedAssertion,
    SourceLocation,
    Verdict,
    VerificationResult,
)


def test_claim_id_is_stable() -> None:
    assertion = NormalizedAssertion(
        subject="POST /v1/orders",
        predicate="endpoint",
        qualifiers={"method": "POST", "path": "/v1/orders"},
    )
    assert Claim.stable_id(assertion) == Claim.stable_id(assertion)
    assert Claim.stable_id(assertion).startswith("claim_")


def test_source_location_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError):
        SourceLocation(file="../outside.md", line=1)


def test_diverged_requires_direct_high_confidence_evidence() -> None:
    direction = DirectionAssessment(
        direction=Direction.DOCS_STALE,
        confidence=0.9,
        rationale="The endpoint was deliberately renamed in code.",
    )
    with pytest.raises(ValidationError):
        VerificationResult(
            claim_id="claim_0123456789abcdef",
            verdict=Verdict.DIVERGED,
            confidence=0.89,
            rationale="Contradiction is not confident enough.",
            evidence=[],
            direction=direction,
        )


def test_valid_divergence_has_contradictory_implementation_evidence() -> None:
    evidence = Evidence(
        kind=EvidenceKind.SPEC,
        location=SourceLocation(file="openapi.yaml", line=12),
        snippet="/v1/purchases:",
        supports=False,
    )
    result = VerificationResult(
        claim_id="claim_0123456789abcdef",
        verdict=Verdict.DIVERGED,
        confidence=0.99,
        rationale="The documented path is absent and the replacement is directly present.",
        evidence=[evidence],
        direction=DirectionAssessment(
            direction=Direction.DOCS_STALE,
            confidence=0.95,
            rationale="Code and specification agree on the newer name.",
            evidence=[evidence],
        ),
    )
    assert result.verdict is Verdict.DIVERGED
