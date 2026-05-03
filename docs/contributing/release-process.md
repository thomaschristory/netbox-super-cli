# Release process

Releases are tag-driven. Each phase's sub-phases ship as `vX.Y.Z<a|b|c|d>`;
the final cut of a phase drops the suffix (e.g., `v0.5.0` is Phase 5d).

## Sub-phase release checklist

For a sub-phase tag like `v0.5.0b`:

1. Full unit suite green: `just test`.
2. Lint clean: `just lint`.
3. Bench median <300ms: `just bench`.
4. E2E green (against the live container): `just e2e` (requires Docker).
5. CHANGELOG `[Unreleased]` rolled to `[v0.5.0b] — YYYY-MM-DD`.
6. Tag annotated: `git tag -a v0.5.0b -m "Phase 5b: ..."`.
7. Push: `git push origin main && git push origin v0.5.0b`.
8. Watch CI: `gh run list --branch main --limit 4`.

## Final v1.0.0 release

Phase 5d cuts v1.0.0. The release pipeline:

1. `pyproject.toml` version bump from `0.0.1` to `1.0.0`.
2. Trusted publishing configured on PyPI (one-time, manual; see PyPI's
   "Publishing" tab).
3. `release.yml` workflow runs on `v*` tag push: `uv build` →
   `pypa/gh-action-pypi-publish` → `gh release create` with auto-generated
   notes from `CHANGELOG.md`.
4. `agents-md-sync.yml` regenerates `AGENTS.md` from `CLAUDE.md`.
5. Phase 6+ GitHub issues filed for every deferred item (keyring, dynamic
   completion, concurrency, multi-NetBox-version CI matrix, stricter
   redaction, singular aliases, Skill install drift).

## Hot-fixing a tagged release

Don't amend a tagged commit. Cut a fresh `vX.Y.Z<suffix>-fix1` tag with the
fix and document in the next sub-phase's plan.

## Versioning policy

Phase milestones are pinned by git tags rather than `pyproject.toml` version
bumps while pre-1.0. After v1.0.0, semver applies.
