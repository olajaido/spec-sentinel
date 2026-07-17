from pathlib import Path

import spec_sentinel.pipeline as pipeline
from spec_sentinel.config import SentinelConfig
from spec_sentinel.models import Verdict, VerificationResult


def test_second_agentic_scan_uses_cache(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(
        "Failed requests are retried up to 3 times.\n", encoding="utf-8"
    )
    (root / "app.py").write_text("RETRIES = 2\n", encoding="utf-8")
    config = SentinelConfig(docs=["README.md"], scope=["app.py"], max_concurrent_claims=2)
    calls: list[str] = []

    class FakeVerifier:
        def __init__(self, tools, settings) -> None:
            del tools, settings

        def verify(self, claim):
            calls.append(claim.id)
            return VerificationResult(
                claim_id=claim.id,
                verdict=Verdict.AMBIGUOUS,
                confidence=0,
                rationale="Test result.",
            )

    monkeypatch.setattr(pipeline, "AgenticVerifier", FakeVerifier)
    cache_dir = tmp_path / "cache"
    first = pipeline.run_scan(root, config, agentic=True, cache_dir=cache_dir)
    second = pipeline.run_scan(root, config, agentic=True, cache_dir=cache_dir)

    assert len(calls) == 1
    assert first.cache_hits == 0
    assert first.cache_misses == 1
    assert first.agentic_requests == 1
    assert second.cache_hits == 1
    assert second.cache_misses == 0
    assert second.agentic_requests == 0
    assert second.results == first.results
