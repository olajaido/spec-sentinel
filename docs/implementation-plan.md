# Spec Sentinel implementation plan

**Plan date:** 16 July 2026
**Submission deadline:** 21 July 2026, 5:00 PM PT
**Repository:** `/Users/olajideadeluwoye/Documents/New project`

## Delivery rule

The build advances through evidence-backed gates. Dashboard work does not begin until the CLI can deterministically catch all four seeded divergences with zero false `diverged` verdicts.

## Status snapshot — 17 July 2026

| Milestone | Status | Evidence |
| --- | --- | --- |
| M0–M2 | Complete | Stable contracts, 18-claim fixture, deterministic OpenAPI path, and model verdict firewall are covered by tests. |
| M3 | Complete | Live agentic scan returned 14 verified / 4 diverged / 0 ambiguous; unchanged rerun made zero model requests. |
| M4 | Complete | Direction gating produces three safe documentation patches and no patch for the `code_suspect` retry claim. |
| M5 implementation | Complete | Baseline/delta CLI and composite Action are implemented; 34 local tests pass. |
| M5 live gate | Complete | PR #1 produced exactly one newly broken claim with evidence while suppressing all four baseline divergences. |
| External validation | Pending | Two unrelated public repositories still need cold-start scans and threshold review. |
| M6 | Pending | Begins only after the live M5 gate. |

## Contract decisions

The following decisions resolve wording tensions in the PRD:

1. F6 is authoritative: documentation patches are generated only for `docs_stale` findings.
2. Patch coverage is measured over patch-eligible `docs_stale` divergences, not all divergences.
3. `not_found` requires the source claim, a complete bounded search trail, and any relevant negative evidence; it cannot require a nonexistent implementation line.
4. A generated OpenAPI document must be supplied by the target project's CI or committed to the repository. Spec Sentinel never imports or executes target application code to generate it.
5. The GitHub Action owns one persistent summary comment per PR. It updates that comment to show newly broken and resolved claims, avoiding comment spam.
6. Cache identity includes the schema version, claim hash, verifier version, configuration hash, relevant evidence hashes, and model/prompt version. The first implementation may conservatively fall back to a repository-tree hash.
7. All repository text is untrusted data. It cannot change instructions, tools, scan boundaries, or output constraints.

## Milestones and gates

### M0 — contracts and scaffold

- Define schemas for claims, evidence, verdicts, search trails, direction assessments, patches, security findings, and reports.
- Establish package layout, configuration contract, exit codes, and report schema versioning.
- Copy the PRD into the repository and document architectural decisions.

**Gate:** models validate invariants and round-trip to stable JSON.

### M1 — deterministic demo and extraction

- Build `drifted-shop` with 15–18 explicit claims and exactly four seeded divergences.
- Add endpoint rename, removed parameter, wrong retry count, and wrong default cases.
- Make retry count `code_suspect` by retaining a test that asserts the documented intent.
- Add README-comment and code-docstring prompt-injection canaries.
- Discover documentation safely and extract atomic claims with exact source lines.

**Gate:** at least 15 correctly typed claims; no marketing sentence extracted; stable IDs across repeated runs.

### M2 — mechanical verifier and verdict firewall

- Load committed OpenAPI and JSON Schema without executing the target.
- Check paths, methods, parameters, required status, response codes, and error shapes.
- Enforce direct-evidence and confidence requirements for `diverged`.

**Gate:** identical verdict JSON across repeated runs and zero model calls for schema-representable claims.

### M3 — bounded agentic verifier

- Plan, search, read, trace, and conclude through a closed read-only tool interface.
- Enforce per-claim step/token limits and attach the complete search trail.
- Validate cited files and line ranges before accepting a conclusion.
- Cache conclusions using claim and evidence identities.

**Gate:** all seeded behavioural outcomes are correct; budget exhaustion returns `ambiguous`, never `diverged`.

### M4 — direction gate, patches, and CLI

- Use code, tests, history, changelog, and specificity to classify direction of error.
- Produce patches only for `docs_stale`.
- Restrict patches to configured documentation files and quarantine unsafe output.
- Ship terminal, Markdown, and JSON reports through `scan`; ship gated diffs through `fix`.

**Gate:** at least 80% of patch-eligible demo findings apply with `git apply --check`; no `code_suspect` patch exists.

### M5 — GitHub Action and external validation

- Compare a PR scan with the default-branch baseline.
- Update one PR summary with newly broken and resolved findings.
- Add optional failure on new divergence and inline suggestions for safe patches.
- Validate on two public repositories.

**Gate:** one newly broken claim produces exactly one finding; false `diverged` count remains zero.

### M6 — P1 and submission

- Add the smallest dashboard that supports claim inventory, evidence drill-down, and run history.
- Add the percentage-only public badge, then fix-all PR mode if time remains.
- Complete hosting, README, architecture narrative, cold-start test, video, and submission checklist.

## Working schedule

| Date | Target |
| --- | --- |
| Thu 16 Jul | M0, demo fixture, extractor foundation |
| Fri 17 Jul | M1, M2, agent loop foundation |
| Sat 18 Jul | M3, M4 |
| Sun 19 Jul | M5 and external validation |
| Mon 20 Jul | Reliability fixes, then optional M6 product surface |
| Tue 21 Jul | Cold-start test, hosting, video, README, submission buffer |

## Definition of P0 done

- Four of four seeded divergences detected.
- Zero false `diverged` verdicts.
- No more than two ambiguous true demo claims.
- All evidence links resolve to exact repository locations.
- Injection canaries cannot influence verdicts and appear as security findings.
- Unsafe or directionally uncertain patches are never generated or applied.
- A fresh user can install and complete a scan in under ten minutes.
