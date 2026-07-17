"""Repository configuration with safe, bounded defaults."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SentinelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    docs: list[str] = Field(default_factory=lambda: ["README.md", "docs/**/*.md"])
    scope: list[str] = Field(default_factory=lambda: ["src/**", "app/**", "openapi.*"])
    ignore: list[str] = Field(default_factory=list)
    include_docstrings: bool = False
    model: str = Field(default="gpt-5.6", min_length=1)
    reasoning_effort: str = Field(default="medium", pattern=r"^(low|medium|high|xhigh)$")
    diverged_threshold: float = Field(default=0.9, ge=0.9, le=1)
    max_steps_per_claim: int = Field(default=12, ge=1, le=50)
    max_concurrent_claims: int = Field(default=4, ge=1, le=8)
    max_scan_tokens: int = Field(default=250_000, ge=1_000)
    max_file_bytes: int = Field(default=1_000_000, ge=1_024)
    fail_on_new_divergence: bool = False

    def digest(self) -> str:
        return sha256(self.model_dump_json().encode()).hexdigest()


def load_config(root: Path, config_path: Path | None = None) -> SentinelConfig:
    path = config_path or root / "spec-sentinel.yml"
    if not path.exists():
        return SentinelConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return SentinelConfig.model_validate(data)
