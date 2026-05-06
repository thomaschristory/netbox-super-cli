# Branching and merging

`netbox-super-cli` follows trunk-based development with short-lived
feature branches. There is exactly one long-lived branch — `main` —
and it is always releasable.

## The branches

- **`main`** — the integration branch. Every accepted change lands here.
  Each commit on `main` is a candidate for the next release.
- **Feature branches** — short-lived, named for the change they carry.
  Created from `main`, deleted on merge.
- **Tags** (`vX.Y.Z`) — the release artifact. A tag points at a commit
  on `main`; `release.yml` builds and publishes from the tagged commit.

There is no separate "release branch". A release is a *tagged commit
on `main`*, not a branch. Multiple unreleased commits accumulate on
`main` between tags; tagging snapshots them into a release.

## Naming convention

Feature branches use a `<type>/<short-slug>` prefix matching the
[Conventional Commit](https://www.conventionalcommits.org/) types:

- `feat/<slug>` — new feature.
- `fix/<slug>` — bug fix.
- `docs/<slug>` — documentation only.
- `refactor/<slug>` — internal restructure, no behaviour change.
- `chore/<slug>` — tooling, dependency bumps, release prep.
- `ci/<slug>` — workflow / CI changes.
- `test/<slug>` — test-only changes.

Agent-generated branches may use the existing `claude/issue-<n>-<date>`
pattern; the prefix isn't load-bearing as long as the branch is
short-lived.

## Lifecycle of a change

1. Branch from latest `main`:
   ```sh
   git checkout main && git pull
   git checkout -b fix/<slug>
   ```
2. Commit using Conventional Commits (`fix(scope): subject`).
3. Push and open a PR against `main`. CI runs.
4. Once green and (if applicable) reviewed, **squash-merge** to `main`.
   Squashing keeps `main` one-commit-per-PR — easy to scan, easy to
   revert.
5. Delete the feature branch (`gh pr merge --delete-branch`, or the
   "Delete branch" button on the PR).

The squashed commit subject follows `<type>(scope): subject (#N)` —
matching the existing convention seen on PRs #8, #10, #26.

## Branch protection on `main`

`main` is protected. The exact rules are configured via the GitHub
branch-protection API; the current policy is:

- **No direct pushes.** Every change goes through a pull request.
- **Required status checks** must pass before merge:
  - `lint`
  - `test (ubuntu-latest, 3.12)`
- **Force pushes blocked.**
- **Branch deletion blocked.**
- **Administrators are not exempt.** Even repo owners go through PRs.

To inspect or change the rule:

```sh
gh api repos/:owner/:repo/branches/main/protection
gh api repos/:owner/:repo/branches/main/protection -X PUT --input rules.json
```

If a status-check job is renamed in CI, update `contexts` in the
protection rule the same day — otherwise PRs will hang waiting for a
check that no longer runs.

## Releases vs. branches

Releases are a *separate* concern from branching:

- Release prep (CHANGELOG roll, version bumps in `pyproject.toml` and
  `nsc/_version.py`) happens on a `chore/release-X.Y.Z` branch.
- Open a PR for the release prep, merge to `main`, **then** tag the
  resulting merge commit:
  ```sh
  git checkout main && git pull
  git tag -a vX.Y.Z -m "vX.Y.Z"
  git push origin vX.Y.Z
  ```
- The tag triggers `release.yml`, which builds the wheel + sdist and
  publishes to PyPI.
- See [`release-process.md`](release-process.md) for the full checklist.

We do **not** maintain release branches (`release/v1.x`) at this time.
Milestones (e.g. `v1.0.2`, `v1.1.0`) track *what's planned* for which
release without forking the codebase.

## Why no long-lived release branches?

For a single-trunk project, release branches add merge overhead
(every fix needs two homes) without benefit. A milestone tells us
"this issue is scoped to v1.0.2"; the actual code change lives on
`main` and ships when we tag.

The day we need to support v1.x and v2.x simultaneously, we'll cut
`release/v1.x` from the last v1.* tag and start cherry-picking
qualifying fixes into it. Until then, `main` is the only place code
lives.
