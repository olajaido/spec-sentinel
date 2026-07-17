from pathlib import Path

from spec_sentinel.cache import ResultCache, result_cache_key, scope_digest
from spec_sentinel.config import SentinelConfig
from spec_sentinel.models import (
    Claim,
    ClaimType,
    NormalizedAssertion,
    SourceLocation,
    Verdict,
    VerificationResult,
)


def _claim() -> Claim:
    assertion = NormalizedAssertion(subject="requests", predicate="behaviour", object=3)
    return Claim(
        id=Claim.stable_id(assertion),
        type=ClaimType.BEHAVIOUR,
        text="Failed requests are retried 3 times.",
        normalized_assertion=assertion,
        source_locations=[SourceLocation(file="README.md", line=1)],
        confidence=0.9,
    )


def test_scope_digest_changes_with_evidence(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 2\n", encoding="utf-8")
    first = scope_digest(tmp_path, [source])
    source.write_text("RETRIES = 3\n", encoding="utf-8")
    second = scope_digest(tmp_path, [source])
    assert first != second


def test_result_cache_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cache = ResultCache(tmp_path / "cache", root)
    claim = _claim()
    result = VerificationResult(
        claim_id=claim.id,
        verdict=Verdict.AMBIGUOUS,
        confidence=0,
        rationale="Budget exhausted.",
    )
    key = result_cache_key(claim, SentinelConfig(), "a" * 64, "b" * 64)
    assert cache.get(key) is None
    cache.put(key, result)
    assert cache.get(key) == result


def test_cache_must_be_outside_scan_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    try:
        ResultCache(root / ".cache", root)
    except ValueError as error:
        assert "outside" in str(error)
    else:
        raise AssertionError("cache inside scan root should be rejected")
