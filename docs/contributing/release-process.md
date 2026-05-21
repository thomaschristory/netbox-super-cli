# Release process

`nsc` follows [Semantic Versioning](https://semver.org/) from v1.0.0 onward.
Releases are tag-driven: `release.yml` fires on `v*.*.*` tag pushes and
publishes to PyPI via trusted publishing (no API tokens).

A release is a **tagged commit on `main`**, not a separate branch — see
[Branching and merging](branching.md) for the trunk-based workflow this
process assumes. Release prep (CHANGELOG roll + version bumps) happens
on a `chore/release-X.Y.Z` feature branch, gets PR-merged into `main`,
and only then is `vX.Y.Z` tagged on the resulting merge commit.

The same `v*` tag push also publishes the documentation site.
`docs.yml` runs build-only (`mkdocs build --strict`) on docs-touching
pull requests, but the GitHub Pages **deploy** job only runs on a `v*`
tag push — the live docs site updates on release, not on merge to
`main`.

## Normal release checklist

1. Full unit suite green: `just test`.
2. Lint clean: `just lint`.
3. Bench median <300 ms: `just bench`.
4. E2E green (requires Docker): `just e2e`.
5. Roll `CHANGELOG.md`: move `[Unreleased]` to `[vX.Y.Z] — YYYY-MM-DD`.
6. Bump `pyproject.toml` `[project].version` and `nsc/_version.py` `__version__`
   to match the tag.
7. Verify all issues attached to the matching
   [GitHub milestone](https://github.com/thomaschristory/netbox-super-cli/milestones)
   are resolved or deferred (don't close the milestone yet — that happens
   after publish, see below).
8. Commit: `git commit -m "chore(release): X.Y.Z"`.
9. Annotate and push: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin main vX.Y.Z`.
10. Watch `release.yml` publish the wheel and create the GitHub Release.
11. Once PyPI shows the new version and the GitHub Release is live, close
    the milestone and open the next one — see the next section for the
    exact `gh api` invocations.

## GitHub milestones convention

Each planned release has a milestone named after its version (e.g., `v1.1.0`).
Issues and PRs are triaged to a milestone when they are scoped to a specific
release. Milestones don't gate CI — they're a planning aid that surfaces
what's queued for which version.

- Milestone name: `vX.Y.Z` (matches the git tag exactly).
- An open milestone with no due date means "planned but not scheduled".
- The `main` branch is always releasable; milestones don't block merges.

**Once a release is published**, close its milestone and open the next one.
This is step 11 of the release checklist; the exact commands are:

1. Bump or close any open issues left in the just-shipped milestone —
   either move them to the next milestone or drop them to the backlog.
2. Close the milestone:
   ```sh
   gh api repos/:owner/:repo/milestones/<N> -X PATCH -f state=closed
   ```
3. Open the next one:
   ```sh
   gh api repos/:owner/:repo/milestones -f title='v<next>' -f state=open
   ```
   For a patch release, increment the patch number; for a minor/major,
   pick whatever's next based on what's queued.
4. Leave the new milestone otherwise empty — issues get attached as they're
   triaged.

This keeps a milestone always available to file new issues against without
having to think about it mid-bug-report.

## Patch releases (bug fixes)

Patch bumps (`Z` increment) follow the same checklist. Because they contain
only bug fixes, the E2E run can be skipped if the fix is confined to a code
path not exercised by the E2E suite — but running it is still recommended.

## Minor / major releases

Minor (`Y`) or major (`X`) bumps follow the full checklist. Before tagging,
open a tracking issue or milestone for any follow-on items deferred from the
release.

## Hot-fixing a tagged release

Never amend a tagged commit. Increment the patch component (e.g.,
`v1.0.1` → `v1.0.2`), cut a fresh patch release with the fix, and document
it in `CHANGELOG.md` under a new `[vX.Y.Z]` entry for the new version.

## Versioning policy

From v1.0.0 onward:

- `PATCH` — backwards-compatible bug fixes.
- `MINOR` — new backwards-compatible features or CLI commands.
- `MAJOR` — breaking changes to the error envelope, exit codes, or config schema.

The version in `pyproject.toml`, `nsc/_version.py`, and the git tag must
always agree. `release.yml` validates the tag against `nsc/_version.py`
before publishing; `pyproject.toml` is not currently checked, so keep it
in sync manually as part of the release commit.
