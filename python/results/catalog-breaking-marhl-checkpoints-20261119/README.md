# Exact checkpoints for Marhl's long breaking protocols

The [complete Marhl inventory](../catalog-breaking-marhl-full-controls-20261118/README.md)
requires 380 distinct trajectories for twelve failed cases, with horizons up to
2210. The earlier 0–300 paired experiment cannot validate those trajectories.
Its independent mpmath calculations took hours, so a long-running worker needs
to preserve completed work before its cloud allocation ends.

The new [checkpoint adapter](../../grn_memory/marhl_checkpoints.py) wraps the
existing model-specific mpmath equations. The equations, model coefficients,
reset amplitudes and original observation grids are unchanged. This is a
prerequisite for the full breaking computation, not a completed numerical
recovery or a dispatched computation.

## What is preserved

Each physical interval between resets is divided into deterministic chunks of
at most one time unit by default. These boundaries only restart the numerical
integrator: they do not reset concentrations or introduce observations. Both an
uninterrupted execution and a resumed execution use the same chunks. The chunk
grid is part of the experiment identity; changing it prevents resumption.

At a checkpoint, each internal mpmath coordinate is converted to a decimal
string with enough digits and checked for an exact round trip at the requested
precision. The loader also requires the canonical representation. Observations
are saved separately as binary64 arrays; they are never used as restart state.
The original binary64 coefficients, reset values and absolute times are promoted
exactly. See mpmath's [conversion and printing documentation](https://mpmath.org/doc/current/general.html)
for the distinction between lossless float conversion and decimal-string
rounding at the current working precision.

The NPZ file contains JSON metadata and numeric observations, with no pickled
objects. It binds the original model hash, both implementation files, complete
reset schedule, observation and chunk grids, precision, tolerance, Taylor degree,
Python/runtime versions, system and architecture. It verifies the observation
prefix, internal state and all reset/segment counters before reuse. Atomic
replacement and a process lock protect the last completed checkpoint.

A checkpoint at a physical reset boundary contains the state **before** that
reset. Resuming applies the reset exactly once. Simultaneous disjoint resets and
empty sham trains retain their original semantics. Changes to execution budgets
or checkpoint frequency are allowed because they do not change the chunk grid
or integration requests.

## Validate in a separate uv environment

From `python/`, use Python 3.12.13 and the pinned requirements:

```bash
uv venv .venv-marhl --python 3.12.13
uv pip install --python .venv-marhl/bin/python -r environments/marhl-checkpoint-requirements.txt
uv run --no-project --python .venv-marhl/bin/python python -B -m pytest -q \
  tests/test_marhl_checkpoints.py tests/test_marhl_mpmath.py \
  tests/test_marhl_mpmath_audit.py tests/test_marhl_controls.py \
  tests/test_marhl_case_audit.py tests/test_marhl_full_controls.py
```

Tests compare resumed and uninterrupted execution at 128 and 192 bits, preserve
state below binary64 resolution, check an analytic time-dependent system and
real Marhl dynamics with resets, and compare short real trajectories with the
original unchunked adapter and published 192-bit Heyoka baseline. They reject
changed requests, schedules, grids, source/runtime identities, corrupt arrays,
inconsistent counters and malformed state. An interrupted atomic write preserves
the previous checkpoint. A separate full-inventory test checks all 380 original
grids, horizons and reset counts without integrating them.

These tests validate restart mechanics and short numerical regressions. They
do not establish convergence over 1410–2210, resolve any failed breaking branch,
or increase the original 26/38 passing-case result.

## Use in the full producer

The calling producer must supply the exact grid and reset trains from the
fixed inventory and retain the complete output. For example, its integration
call will have this shape:

```python
from grn_memory.marhl_checkpoints import trajectory, MarhlCheckpointStop

try:
    names, values = trajectory(
        model_path, original_times, original_reset_trains,
        precision=192, tolerance="1e-45", degree=48,
        checkpoint=checkpoint_path, resume=checkpoint_path.exists(),
        max_chunk_span=1.0, checkpoint_every=10, max_seconds=14400,
        evidence=integration_evidence,
    )
except MarhlCheckpointStop:
    # Preserve the checkpoint as incomplete work; do not classify the branch.
    pass
```

The time limit is cooperative and is checked after a chunk returns. A hard kill
can lose work since the last checkpoint; an exceptionally slow chunk can exceed
the requested budget. No horizon is shortened to make a job pass. The future
cloud restore step must also bind the parent artifact's original ZIP digest and
source identity before invoking this local checkpoint loader.

Full execution still needs the independently implemented Heyoka arm, both
precisions for both implementations, comparisons with retained native evidence,
all 380 required trajectories and replay of all twelve conditional searches.
Both arbitrary-precision implementations use Taylor methods, so agreement is
not evidence from different integrator families or proof of an exact solution.
The existing producers and environments used by stopped or live workers remain
unchanged. No full breaking computation is dispatched by this change.
