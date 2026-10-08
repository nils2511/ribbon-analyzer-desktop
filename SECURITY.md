# Security

## Scope

Ribbon Analyzer is a local desktop application. Manual annotation does not require a key and makes no network requests. Optional Anthropic actions transmit images or research context only when the operator requests those actions. The README describes their payloads.

API keys are supplied through the optional masked entry or `ANTHROPIC_API_KEY`; they are not saved into project JSON or source files. Keep research projects, micrographs, review examples and exports private. Saved projects contain local image paths. Only source, documentation, tests and synthetic demonstration material belong in the public repository.

## Reporting a vulnerability

Use **Security → Advisories → Report a vulnerability** if private vulnerability reporting is available in the repository. If it is unavailable, ask the maintainer in an issue for a private reporting channel without posting vulnerability details, credentials or research data. Do not upload a real dataset to demonstrate a problem; provide a minimal synthetic reproduction.

## Checks and limits

Before publishing, run the test suite and `scripts/check_release.py`. The release check rejects unexpected files, common credential patterns, personal home paths and selected symlinks. It also checks reachable Git history; a shallow clone only provides partial history.

The CSV export prefixes formula-like text with an apostrophe. Excel stores formula-like notes as literal strings. Annotation text in project JSON remains unchanged. Do not remove those protections when opening or re-exporting an untrusted spreadsheet.

Keep Python dependencies updated and review Dependabot alerts. Automated scans cover known patterns and reported dependency vulnerabilities; they do not prove the absence of every vulnerability. Future public releases should be rechecked. A suspected exposed key must be revoked with its provider; removing it from the latest file alone does not revoke it.
