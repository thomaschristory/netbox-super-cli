"""Dynamic shell completion (issue #2).

Reads ONLY the on-disk cache + config — never triggers a schema fetch — so
that TAB completion stays fast and side-effect-free. Every entry point
degrades to an empty list rather than raising, because a raised exception
during completion corrupts the user's shell line.

- `providers` — framework-free candidate generators (model/config in, str list out).
- `cache_probe` — cheap on-disk CommandModel + profile resolution.
- `callbacks` — Typer/Click `shell_complete` adapters wrapping the above.
"""
