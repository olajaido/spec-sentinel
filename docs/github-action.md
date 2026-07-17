# GitHub Action design

## Event flow

On a default-branch `push`, the composite Action performs a complete scan and stores the report in the GitHub Actions cache under the exact commit SHA. On `pull_request`, it scans the current checkout, restores the base SHA's report, and performs a full base-revision scan when that cache entry is cold.

The `spec-sentinel delta` command accepts only complete schema `1.0` artifacts. It first matches stable claim IDs, then uses bounded source lineage matching for a claim whose documented value—and therefore stable ID—was edited. Existing divergences are omitted. A transition into `diverged` is newly broken; a previous divergence that becomes another verdict or is removed is resolved.

## Comment lifecycle

The Action renders one sanitized Markdown document beginning with `<!-- spec-sentinel-report -->`. Repository-derived claim text, paths, rationales, and evidence snippets are HTML-escaped and placed inside code elements. The comment step authenticates the token owner and updates only that owner's marked comment, preventing a repository contributor from planting a marker in a comment that the bot would try to overwrite.

The GitHub token is passed only to the comment step and to GitHub's own checkout/cache layers. It is never exported to the scanner or exposed to the agent's closed read-only tool interface. The final policy step runs after the comment and can fail the check only when `newly_broken` is non-empty.

## Untrusted checkout boundary

The included workflow checks the target revision into `target/` and checks executable Spec Sentinel code from the trusted base revision into `.spec-sentinel-action/`. It installs only the trusted checkout. The target project is read as evidence and is never imported, built, or executed.

CI disables dotenv loading. This prevents a committed `.env` in a pull request from supplying `OPENAI_BASE_URL` or other client settings. Only the workflow-provided `OPENAI_API_KEY` reaches model verification.

All third-party Actions are pinned to full release commit SHAs. The workflow intentionally uses `pull_request`, not `pull_request_target`; forked pull requests therefore do not receive repository secrets.

## Local delta check

```bash
spec-sentinel scan /path/to/base --agentic --format json --no-load-dotenv > baseline.json
spec-sentinel scan /path/to/current --agentic --format json --no-load-dotenv > current.json
spec-sentinel delta baseline.json current.json --format md
spec-sentinel delta baseline.json current.json --fail-on-new-divergence
```

The Action's generated report paths are exposed as `current-report`, `baseline-report`, `delta-json`, and `delta-markdown` outputs for optional artifact upload or downstream ingestion.
