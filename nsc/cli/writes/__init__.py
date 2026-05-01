"""Write pipeline (Phase 3b/3c).

Stages:
  input.collect()      → RawWriteInput
  preflight.check()    → PreflightResult
  apply.resolve()      → ResolvedRequest
  confirmation.*       → flag-conflict gating helpers
"""

from __future__ import annotations
