# Vilar: truncated trajectories and changed conserved pools

This is a diagnostic of three selected Vilar breaking-memory branches, not a
case recovery or a completed model audit. The original observation horizons,
reset schedules, values and numerical acceptance rule are retained.

An inventory of fifteen exported partitions contained 7,412 branch records,
including 300 incomplete records. Every incomplete record returned fewer
COPASI output rows than requested. One additional parent partition had no
exported branch archive, so this is explicitly not a complete model inventory.
The three diagnostic records are the first, middle and last after sorting the
300 incomplete records by returned row count, record ID and artifact ID.

## What the computation establishes

Each selected branch was run with RoadRunner and COPASI at three integration
settings: `(rtol, atol)` of `(1e-12, 1e-14)`, `(1e-13, 1e-15)` and
`(5e-14, 5e-16)`. COPASI retains its original 100,000-internal-step limit. All
comparisons retain `rtol=2e-5`, `atol=1e-7`; solver settings and acceptance
thresholds are separate quantities.

All nine COPASI integrations stopped early. Their saved Basico logs report
exhaustion of the internal-step budget before the next requested output and
warnings that the step is too small to advance the floating-point clock.
Basico consumes the solver exception and returns a partial array. The existing
adapter correctly rejects that array. No padding, truncation of the requested
grid, interpolation or missing-sample substitution is permitted.

RoadRunner completed all nine trajectories. Its original-to-tight and
tight-to-tighter comparisons pass for the first two selected branches. Both
comparisons fail for the third branch. Therefore these computations recover
**zero branches or cases**; they do not turn RoadRunner's completed output into
an independently validated reference.

The independent `audit.json` verifies producer source hashes, the model and
full sample grids, every saved trajectory and raw COPASI array, compressed
solver logs, integration requests and all reported comparisons. It recomputes
the comparisons directly from the full arrays. The initial capture is retained
separately in `catalog-breaking-vilar-short-output-20261113`; it lacks the
Basico solver-error logs. The logged repeat also shows that exact stopping
times can vary while the failure persists.

## Why the intervention changes the mathematical system's state

The [original SBML](../../models/BIOMD0000000035.xml) conserves both promoter
pools between external interventions:

$$P_A = DA + DAp,\qquad P_R = DR + DRp,\qquad \dot P_A=\dot P_R=0.$$

The audit verifies this directly: every reaction's stoichiometric change in
each pool is zero, both species share a constant compartment, and no original
rule or event changes either pool. These are properties of the unforced model;
the imposed reset protocol can change them.

For example, assigning `DA = 100` changes the total by

$$P_A^+ = P_A^- + (100 - DA^-).$$

Repeatedly setting the free promoter to 100 can add promoter material whenever
some of it has become bound. It does not merely redistribute a fixed promoter
pool. In the first two selected branches, the six initial training episodes
raise `DA + DAp` from 1 to about **450,506 model units** by time 1000. Their
RoadRunner trajectories then have activator `A` around **1.126 billion model
units**. These measurements are diagnostic outputs, not cross-simulator
validation. The original SBML's units are retained.

This supplies a concrete interpretation check for persistent responses: an
intervention can move the system to a different conserved total. Persistence
can therefore reflect material added or removed by the protocol. It does not,
by itself, establish a learning mechanism or explain every memory label in the
catalog. The large concentrations and separated time scales motivate further
stiff-solver investigation; the logs establish the termination reason, not a
proof of its unique mathematical cause.

A useful separate learning project would compare these resets with
interventions that preserve `DA + DAp` and `DR + DRp`. That is a proposed
control experiment. It has not replaced the original replication protocol.

## Reproduce and audit

The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-vilar-output-diagnostics-20261113)
contains the full arrays and raw partial outputs from both attempts, plus the
logged attempt's compressed solver errors. `release-manifest.json` gives every
archive member's size and SHA-256 checksum. Extract the logged archive into a
separate directory and run from `python/`:

```bash
uv run --locked python scripts/audit_copasi_short_output.py \
  --input /path/to/catalog-breaking-vilar-short-output-logged-20261113 \
  --output /tmp/vilar-short-output-audit.json
```

Expected: three records, nine recorded COPASI step-limit failures, full-array
comparisons recomputed, and no case-recovery claim. The auditor also verifies
the conserved pools directly from the model's reaction stoichiometry.

To repeat the integrations in a fresh directory:

```bash
uv run --locked python scripts/diagnose_copasi_short_output.py \
  --source-evidence results/catalog-breaking-vilar-short-output-logged-20261113/source-evidence.json \
  --output /tmp/vilar-short-output-repeat
```

`source-evidence.json` retains the exact original records and their parent
report/archive identities. `exported-short-output-inventory.json` documents the
selection population and its incomplete coverage. The instrumented wrapper
passes Basico's arguments and returned object through unchanged; three focused
tests cover partial arrays, exception preservation and error-log capture.
