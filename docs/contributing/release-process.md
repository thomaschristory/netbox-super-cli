# Release process

`nsc` follows [Semantic Versioning](https://semver.org/) from v1.0.0 onward.
Releases are tag-driven: `release.yml` fires on `v*.*.*` tag pushes and
publishes to PyPI via trusted publishing (no API tokens).

## Normal release checklist

1. Full unit suite green: `just test`.
2. Lint clean: `just lint`.
3. Bench median <300 ms: `just bench`.
4. E2E green (requires Docker): `just e2e`.
5. Roll `CHANGELOG.md`: move `[Unreleased]` to `[vX.Y.Z] — YYYY-MM-DD`.
6. Bump `pyproject.toml` `[project].version` and `nsc/_version.py` `__version__`
   to match the tag.
7. Close the matching [GitHub milestone](https://github.com/thomaschristory/netbox-super-cli/milestones)
   and verify all tracked issues are resolved or deferred.
8. Commit: `git commit -m "chore(release): X.Y.Z"`.
9. Annotate and push: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin main vX.Y.Z`.
10. Watch `release.yml` publish the wheel and create the GitHub Release.

## GitHub milestones convention

Each planned release has a milestone named after its version (e.g., `v1.1.0`).
Issues and PRs are triaged to a milestone when they are scoped to a specific
release. Milestones are purely organizational — they don't trigger anything.

- Milestone name: `vX.Y.Z` (matches the git tag exactly).
- An open milestone with no due date means "planned but not scheduled".
- The `main` branch is always releasable; milestones are a planning aid, not a gate.

**When a release ships, open the next milestone.** A milestone is considered
closed once its release is published to PyPI and tagged on GitHub. As part
of finalizing the release:

1. Close the milestone:
   ```sh
   gh api repos/:owner/:repo/milestones/<N> -X PATCH -f state=closed
   ```
2. Open the next one:
   ```sh
   gh api repos/:owner/:repo/milestones -f title='v<next>' -f state=open
   ```
   For a patch release, increment the patch number; for a minor/major,
   pick whatever's next based on what's queued.
3. Bump or close any open issues left in the just-closed milestone — either
   move them to the next milestone or drop them to the backlog.
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

Never amend a tagged commit. Cut a `vX.Y.Z+1` patch release with the fix
and document it in `CHANGELOG.md` under a new `[vX.Y.Z+1]` entry.

## Versioning policy

From v1.0.0 onward:

- `PATCH` — backwards-compatible bug fixes.
- `MINOR` — new backwards-compatible features or CLI commands.
- `MAJOR` — breaking changes to the error envelope, exit codes, or config schema.

The version in `pyproject.toml`, `nsc/_version.py`, and the git tag must
always agree. `release.yml` validates the tag against `nsc/_version.py`
before publishing; `pyproject.toml` is not currently checked, so keep it
in sync manually as part of the release commit.
