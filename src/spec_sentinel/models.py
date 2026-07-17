"""Schema-versioned data contracts for the complete scan pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimType(StrEnum):
    ENDPOINT = "endpoint"
    PARAMETER = "parameter"
    BEHAVIOUR = "behaviour"
    ERROR = "error"
    LIMIT = "limit"
    CONFIG = "config"
    EXAMPLE = "example"


class Verdict(StrEnum):
    VERIFIED = "verified"
    DIVERGED = "diverged"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


class Direction(StrEnum):
    DOCS_STALE = "docs_stale"
    CODE_SUSPECT = "code_suspect"
    UNDETERMINED = "undetermined"


class EvidenceKind(StrEnum):
    DOCUMENTATION = "documentation"
    CODE = "code"
    SPEC = "spec"
    TEST = "test"
    CHANGELOG = "changelog"
    SEARCH = "search"
    SECURITY = "security"


class SourceLocation(StrictModel):
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_location(self) -> SourceLocation:
        path = PurePosixPath(self.file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source paths must be repository-relative")
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("end_line cannot precede line")
        return self


class NormalizedAssertion(StrictModel):
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str | int | float | bool | None = None
    qualifiers: dict[str, str | int | float | bool] = Field(default_factory=dict)


class Claim(StrictModel):
    id: str = Field(pattern=r"^claim_[0-9a-f]{16}$")
    type: ClaimType
    text: str = Field(min_length=1, max_length=2000)
    normalized_assertion: NormalizedAssertion
    source_locations: list[SourceLocation] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @classmethod
    def stable_id(cls, assertion: NormalizedAssertion) -> str:
        payload = assertion.model_dump_json(exclude_none=False)
        return f"claim_{sha256(payload.encode()).hexdigest()[:16]}"


class Evidence(StrictModel):
    kind: EvidenceKind
    location: SourceLocation
    snippet: str = Field(min_length=1, max_length=2000)
    file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    supports: bool


class SearchStep(StrictModel):
    tool: str = Field(min_length=1, max_length=40)
    query: str = Field(min_length=1, max_length=500)
    result_summary: str = Field(min_length=1, max_length=1000)


class DirectionAssessment(StrictModel):
    direction: Direction
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(default_factory=list)


class VerificationResult(StrictModel):
    claim_id: str = Field(pattern=r"^claim_[0-9a-f]{16}$")
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(default_factory=list)
    search_trail: list[SearchStep] = Field(default_factory=list)
    direction: DirectionAssessment | None = None

    @model_validator(mode="after")
    def enforce_verdict_invariants(self) -> VerificationResult:
        implementation_kinds = {EvidenceKind.CODE, EvidenceKind.SPEC}
        direct_implementation = any(item.kind in implementation_kinds for item in self.evidence)
        contradictory = any(not item.supports for item in self.evidence)
        if self.verdict is Verdict.DIVERGED:
            if self.confidence < 0.9 or not direct_implementation or not contradictory:
                raise ValueError(
                    "diverged requires >=0.9 confidence and direct contradictory evidence"
                )
            if self.direction is None:
                raise ValueError("diverged requires a direction assessment")
        elif self.direction is not None:
            raise ValueError("direction assessment is valid only for diverged results")
        if self.verdict is Verdict.NOT_FOUND and not self.search_trail:
            raise ValueError("not_found requires a non-empty search trail")
        return self


class PatchProposal(StrictModel):
    claim_id: str = Field(pattern=r"^claim_[0-9a-f]{16}$")
    file: str = Field(min_length=1)
    unified_diff: str = Field(min_length=1, max_length=50_000)
    rationale: str = Field(min_length=1, max_length=2000)
    quarantined: bool = False
    quarantine_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_patch(self) -> PatchProposal:
        path = PurePosixPath(self.file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("patch paths must be repository-relative")
        if self.quarantined and not self.quarantine_reason:
            raise ValueError("quarantined patches require a reason")
        return self


class SecurityFinding(StrictModel):
    rule: str = Field(min_length=1, max_length=100)
    severity: str = Field(pattern=r"^(low|medium|high|critical)$")
    location: SourceLocation
    explanation: str = Field(min_length=1, max_length=2000)


class ScanSummary(StrictModel):
    claims: int = Field(ge=0)
    verified: int = Field(ge=0)
    diverged: int = Field(ge=0)
    not_found: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    skipped_statements: int = Field(ge=0)


class ScanReport(StrictModel):
    schema_version: str = SCHEMA_VERSION
    repository: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims: list[Claim]
    results: list[VerificationResult]
    patches: list[PatchProposal] = Field(default_factory=list)
    security_findings: list[SecurityFinding] = Field(default_factory=list)
    summary: ScanSummary
    metadata: dict[str, Any] = Field(default_factory=dict)
