"""Conservative, schema-validated cache for agentic verification results."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

from pydantic import Field

from spec_sentinel.config import SentinelConfig
from spec_sentinel.models import Claim, StrictModel, VerificationResult

CACHE_SCHEMA_VERSION = "1"


class CacheEntry(StrictModel):
    schema_version: str = CACHE_SCHEMA_VERSION
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: VerificationResult


def scope_digest(root: Path, files: list[Path]) -> str:
    """Hash paths and bytes for the complete allowlisted evidence scope."""
    root = root.resolve()
    digest = sha256()
    for file in sorted(files, key=lambda item: item.resolve().relative_to(root).as_posix()):
        resolved = file.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file() or file.is_symlink():
            continue
        relative = resolved.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = resolved.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def result_cache_key(
    claim: Claim,
    config: SentinelConfig,
    evidence_scope_digest: str,
    prompt_digest: str,
) -> str:
    payload = "\n".join(
        (
            CACHE_SCHEMA_VERSION,
            claim.model_dump_json(),
            evidence_scope_digest,
            prompt_digest,
            config.model,
            config.reasoning_effort,
            str(config.diverged_threshold),
            str(config.max_steps_per_claim),
        )
    )
    return sha256(payload.encode()).hexdigest()


def default_cache_dir(root: Path) -> Path:
    repository_id = sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "spec-sentinel-cache" / repository_id


class ResultCache:
    def __init__(self, directory: Path, scan_root: Path) -> None:
        self.directory = directory.resolve()
        scan_root = scan_root.resolve()
        if self.directory.is_relative_to(scan_root):
            raise ValueError("cache directory must be outside the untrusted scan root")

    def get(self, key: str) -> VerificationResult | None:
        path = self.directory / f"{key}.json"
        try:
            entry = CacheEntry.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if entry.key != key or entry.schema_version != CACHE_SCHEMA_VERSION:
            return None
        return entry.result

    def put(self, key: str, result: VerificationResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = CacheEntry(key=key, result=result)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{key}.", suffix=".tmp", dir=self.directory
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.directory / f"{key}.json")
        finally:
            temporary.unlink(missing_ok=True)
