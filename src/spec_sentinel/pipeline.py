"""End-to-end orchestration shared by CLI commands and CI adapters."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from spec_sentinel.agentic import SYSTEM_INSTRUCTIONS, AgenticVerifier, RepositoryTools
from spec_sentinel.cache import ResultCache, default_cache_dir, result_cache_key, scope_digest
from spec_sentinel.config import SentinelConfig
from spec_sentinel.direction import assess_mechanical_direction
from spec_sentinel.discovery import discover_docs, discover_scope
from spec_sentinel.extractor import extract_claims
from spec_sentinel.models import Claim, PatchProposal, SecurityFinding, VerificationResult
from spec_sentinel.openapi import OpenApiDocument, OpenApiVerifier
from spec_sentinel.patches import generate_doc_patch
from spec_sentinel.security import scan_injection_attempts


@dataclass(frozen=True)
class ScanArtifacts:
    repository: Path
    claims: list[Claim]
    results: list[VerificationResult]
    mechanical_claim_ids: frozenset[str]
    patches: list[PatchProposal]
    security_findings: list[SecurityFinding]
    skipped_statements: int
    cache_hits: int = 0
    cache_misses: int = 0
    agentic_requests: int = 0
    elapsed_seconds: float = 0

    @property
    def pending_claims(self) -> int:
        return len(self.claims) - len(self.results)

    def as_dict(self) -> dict[str, Any]:
        mechanical = [
            result for result in self.results if result.claim_id in self.mechanical_claim_ids
        ]
        agentic = [
            result for result in self.results if result.claim_id not in self.mechanical_claim_ids
        ]
        return {
            "schema_version": "1.0",
            "repository": str(self.repository),
            "claims": [claim.model_dump(mode="json") for claim in self.claims],
            "mechanical_results": [result.model_dump(mode="json") for result in mechanical],
            "agentic_results": [result.model_dump(mode="json") for result in agentic],
            "results": [result.model_dump(mode="json") for result in self.results],
            "patches": [patch.model_dump(mode="json") for patch in self.patches],
            "security_findings": [
                finding.model_dump(mode="json") for finding in self.security_findings
            ],
            "skipped_statements": self.skipped_statements,
            "pending_claims": self.pending_claims,
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "agentic_requests": self.agentic_requests,
            },
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass(frozen=True)
class ProgressEvent:
    completed: int
    total: int
    claim: Claim
    result: VerificationResult
    cached: bool


ProgressCallback = Callable[[ProgressEvent], None]


def run_scan(
    root: Path,
    config: SentinelConfig,
    *,
    agentic: bool,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    progress: ProgressCallback | None = None,
) -> ScanArtifacts:
    started_at = perf_counter()
    root = root.resolve()
    docs = discover_docs(root, config)
    scope = discover_scope(root, config)
    extraction = extract_claims(root, docs)
    scan_files = sorted(set(docs + scope))
    security_findings = scan_injection_attempts(root, scan_files)

    results_by_claim: dict[str, VerificationResult] = {}
    mechanical_claim_ids: set[str] = set()
    openapi_path = next(
        (
            candidate
            for candidate in (root / "openapi.yaml", root / "openapi.yml")
            if candidate.exists()
        ),
        None,
    )
    if openapi_path is not None:
        verifier = OpenApiVerifier(OpenApiDocument.load(root, openapi_path))
        for claim in extraction.claims:
            result = verifier.verify(claim)
            if result is None:
                continue
            result = assess_mechanical_direction(claim, result, root, scope)
            results_by_claim[claim.id] = result
            mechanical_claim_ids.add(claim.id)

    cache_hits = 0
    cache_misses = 0
    agentic_requests = 0
    if agentic:
        pending_claims = [claim for claim in extraction.claims if claim.id not in results_by_claim]
        repository_tools = RepositoryTools(root, scan_files, config.max_file_bytes)
        cache = None
        keys: dict[str, str] = {}
        if use_cache:
            cache = ResultCache(cache_dir or default_cache_dir(root), root)
            evidence_digest = scope_digest(root, scan_files)
            prompt_digest = sha256(SYSTEM_INSTRUCTIONS.encode()).hexdigest()
            keys = {
                claim.id: result_cache_key(claim, config, evidence_digest, prompt_digest)
                for claim in pending_claims
            }
        misses: list[Claim] = []
        completed = 0
        for claim in pending_claims:
            cached = cache.get(keys[claim.id]) if cache is not None else None
            if cached is None or cached.claim_id != claim.id:
                cache_misses += 1
                misses.append(claim)
                continue
            cache_hits += 1
            completed += 1
            results_by_claim[claim.id] = cached
            if progress is not None:
                progress(
                    ProgressEvent(
                        completed=completed,
                        total=len(pending_claims),
                        claim=claim,
                        result=cached,
                        cached=True,
                    )
                )
        if misses:
            agentic_requests = len(misses)
            workers = min(config.max_concurrent_claims, len(misses))
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="sentinel-claim"
            ) as pool:
                futures = {
                    pool.submit(AgenticVerifier(repository_tools, config).verify, claim): claim
                    for claim in misses
                }
                for future in as_completed(futures):
                    claim = futures[future]
                    result = future.result()
                    results_by_claim[claim.id] = result
                    if cache is not None:
                        cache.put(keys[claim.id], result)
                    completed += 1
                    if progress is not None:
                        progress(
                            ProgressEvent(
                                completed=completed,
                                total=len(pending_claims),
                                claim=claim,
                                result=result,
                                cached=False,
                            )
                        )

    results = [
        results_by_claim[claim.id] for claim in extraction.claims if claim.id in results_by_claim
    ]
    claims_by_id = {claim.id: claim for claim in extraction.claims}
    patches = [
        patch
        for result in results
        if (patch := generate_doc_patch(root, claims_by_id[result.claim_id], result, docs))
        is not None
    ]
    return ScanArtifacts(
        repository=root,
        claims=extraction.claims,
        results=results,
        mechanical_claim_ids=frozenset(mechanical_claim_ids),
        patches=patches,
        security_findings=security_findings,
        skipped_statements=extraction.skipped_statements,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        agentic_requests=agentic_requests,
        elapsed_seconds=perf_counter() - started_at,
    )
