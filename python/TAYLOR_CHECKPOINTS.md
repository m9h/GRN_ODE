# Resuming long precision checks

The paired-memory validation uses arbitrary-precision Heyoka integrations as an
additional reference when the native solvers disagree. Each failed Vilar branch
retains the original 300-unit protocol, 30,001 observations, every concentration
reset, and both 128-bit and 192-bit calculations. Finishing a branch does not
establish a memory case until its other controls and comparisons also pass.

Vilar partition 6 reached the same saved state in two consecutive cloud attempts:
490 of 500 protocol segments, 9,900 observations, last completed interval
98.9–99.0. The previous adapter saved only completed segments. Work inside the
following long segment could therefore be lost at the five-hour deadline.
This is an execution limit, not evidence that the mathematical solution ends.

The adapter now calls `propagate_grid` in chunks of at most 1,000,000 adaptive
steps. After an unfinished chunk it saves the exact MPFR state, both components
of Heyoka's compensated clock, the observation prefix and reset counters.
It can resume even when that chunk reached no new observation. A reset at the
start of an active segment is not repeated. At a completed segment boundary,
the adapter uses the dense-output endpoint before applying the next reset.

Checkpoint schema 2 contains numeric arrays and JSON, with atomic replacement
and checksums; it contains no pickle or compiled code. Resume checks the complete
model, protocol, precision, chunk size, numerical source hashes and environment.
The observation prefix and active-segment clock are checked against the actual
grid, rather than accepted from a reported count.

Heyoka's [grid implementation at version 7.13.0](https://github.com/bluescarni/heyoka/blob/v7.13.0/src/taylor_adaptive.cpp)
aligns its compensated clock with the first grid point using a tiny integration
step. Chunking can consequently change arithmetic rounding at MPFR precision.
The stored state and clock themselves round-trip exactly. Tests compare both
uninterrupted and repeatedly resumed chunked calculations, and compare chunked
and unchunked observations. Analytic decay, a direct time-dependent integrator
probe, and short Vilar/Marhl probes exercise both precisions. These short tests
validate the implementation; the full scientific protocols still need to finish.

## Run with uv

The Linux workflow uses Python 3.12.12, Heyoka 7.13.2, and pinned Python packages:

```sh
uv venv .venv-taylor --python 3.12.12
uv pip install --python .venv-taylor/bin/python heyoka==7.13.2 -r environments/heyoka-python-requirements.txt
uv run --no-project --python .venv-taylor/bin/python python -m pytest -q \
  tests/test_taylor_reference.py tests/test_taylor_checkpoints.py \
  tests/test_taylor_partitions.py tests/test_taylor_partition_resume.py \
  tests/test_taylor_checkpoint_migration.py
```

Existing local macOS validation uses an already provisioned Heyoka interpreter
through `uv run --no-project --python /path/to/interpreter`; this does not convert
that interpreter's environment into a uv-managed environment. Live calculations'
dependencies and source files remain unchanged.

Cloud runs check their four-hour cooperative budget after each chunk. A single
native chunk can exceed that budget; the five-hour external limit remains a
fallback. Checkpoints preserve progress rather than shortening the protocol or
loosening comparison thresholds.

## Migrate the stalled legacy checkpoint

Ordinary resume still rejects changed source code. An explicit
`--migrate-segments` option accepts only the pinned legacy implementation from
commit `50740779287606d05eae34b2197fc9cb27394fe6`, an unfinished Taylor128
integration, and the same runtime. It validates the original checkpoint before
conversion and retains `legacy-report.json`, `legacy-taylor128-checkpoint.npz`,
`segment-start-checkpoint.npz` and a checksummed migration manifest. The original
downloaded artifact remains intact. Every subsequent resume and audit verifies
this lineage and the unchanged legacy observation prefix.

The workflow has a corresponding `migrate_segments` input. The intended rescue
selects original Vilar partition `[6]`, with parent run `43556371440`. It does not
replace the other 16 required partitions. Later continuations of the converted
checkpoint use normal resume, with migration disabled. The existing whole-model
auditor deliberately rejects mixing different implementations; combining old and
new results requires an explicit provenance-aware audit before claiming coverage.

The migration is not a general converter for arbitrary source versions or
completed legacy solver arrays. Those require separate review. Both the saved
legacy prefix and the new continuation remain distinguishable in the evidence.
