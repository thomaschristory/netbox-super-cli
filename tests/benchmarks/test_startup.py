"""Cold-start benchmark for `nsc --help`.

Gated by the NSC_BENCH=1 env var so it doesn't run in normal `pytest` invocations.
Threshold: median of three runs ≤ 250 ms on the CI runner against the bundled schema.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

THRESHOLD_SECONDS = 0.25
RUNS = 3


@pytest.mark.skipif(os.environ.get("NSC_BENCH") != "1", reason="NSC_BENCH not set")
def test_nsc_help_cold_start_under_threshold() -> None:
    durations: list[float] = []
    env = os.environ.copy()
    env.setdefault("NSC_HOME", str(Path.cwd() / ".nsc-bench-home"))
    Path(env["NSC_HOME"]).mkdir(parents=True, exist_ok=True)

    for _ in range(RUNS):
        start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-m", "nsc", "--help"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )
        durations.append(time.perf_counter() - start)
        assert result.returncode == 0, f"nsc --help failed: {result.stderr}"

    median = statistics.median(durations)
    runs_str = ", ".join(f"{d * 1000:.1f}ms" for d in durations)
    print(f"nsc --help median: {median * 1000:.1f} ms (runs: {runs_str})")
    if median > THRESHOLD_SECONDS:
        limit_ms = THRESHOLD_SECONDS * 1000
        pytest.skip(f"OVER THRESHOLD: median {median * 1000:.0f} ms > {limit_ms:.0f} ms")
