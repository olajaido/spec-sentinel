"""Safe, glob-scoped repository file discovery."""

from __future__ import annotations

from pathlib import Path

from spec_sentinel.config import SentinelConfig


def _discover(root: Path, patterns: list[str], config: SentinelConfig) -> list[Path]:
    root = root.resolve()
    discovered: set[Path] = set()
    for pattern in patterns:
        for candidate in root.glob(pattern):
            if candidate.is_dir() and not candidate.is_symlink():
                for child in candidate.rglob("*"):
                    if child.is_file():
                        discovered.add(child.resolve())
                continue
            if not candidate.is_file() or candidate.is_symlink():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                continue
            if resolved.stat().st_size > config.max_file_bytes:
                continue
            relative = resolved.relative_to(root)
            if any(relative.match(pattern) for pattern in config.ignore):
                continue
            discovered.add(resolved)
    bounded = []
    for resolved in discovered:
        if not resolved.is_relative_to(root) or resolved.is_symlink():
            continue
        relative = resolved.relative_to(root)
        if any(relative.match(pattern) for pattern in config.ignore):
            continue
        if resolved.stat().st_size <= config.max_file_bytes:
            bounded.append(resolved)
    return sorted(bounded, key=lambda path: path.relative_to(root).as_posix())


def discover_docs(root: Path, config: SentinelConfig) -> list[Path]:
    return _discover(root, config.docs, config)


def discover_scope(root: Path, config: SentinelConfig) -> list[Path]:
    return _discover(root, config.scope, config)
