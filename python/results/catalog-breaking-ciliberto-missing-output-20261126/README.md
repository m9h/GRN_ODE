# Recover the missing Ciliberto partition

The original later-control run, [44412503884](https://github.com/m9h/GRN_ODE/actions/runs/44412503884),
lost its hosted runner for partition 43 before uploading an artifact. The saved
GitHub annotation reports lost communication; this is missing computational
evidence, not a numerical failure or a passing result.

The captured complete API inventory contains 195 original archives totaling
478,646,175,890 bytes. All 256 original job selections remain pinned. The recovery
workflow can request **only partition 43**, whose original 27 branches, sample
grids, requests, model, solver versions, producer code and locked environment
remain unchanged. The other 255 selections are retained exactly. Other original
jobs are still running or queued; their outputs must be collected from that run.

Full completion still requires 6,859 later controls, 7,334 total branches and the
74 selected-case replays. This orchestration does not add a recovered case or a
whole-model pass. Numerical disagreements and integration failures must remain
in the final scientific results.

## Validation and execution

From `python/`, use the frozen environment:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python scripts/ciliberto_missing_output.py check
```

The workflow `.github/workflows/ciliberto-missing-output-recovery.yml` has a
Linux validation gate before computation. It checks installed dependency source
hashes and versions as well as repository sources, verifies the complete input
release, and runs transport, array-audit and case-replay tests. Computation calls
the unchanged original producer with the original 19,200-second budget.

Dispatch `operation=compute`, `partitions=[43]` once. Preserve the accepted
request and actual run identity; do not repeat a dispatch merely because its
jobs are queued. Once the gate passes and GitHub creates the compute job, save
the complete run/jobs API responses and bind them to the exact source commit:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/ciliberto_missing_output.py bind \
  --run recovery-api/run.json --jobs recovery-api/jobs.json \
  --revision FULL_COMMIT_SHA --output recovery-binding.json
```

Binding retains the full original selection and records the replaced job as
`previous`. Original identity checks remain unchanged. An isolated instance of
the existing collector validates the replacement against its explicitly bound
new run, source revision, attempt and successful gate.

## Collect and audit

Preserve complete `run.json`, `jobs.json` and `artifacts.json` snapshots for the
replacement. Download its original ZIP, verify the GitHub SHA-256 and byte count,
and retain both ZIP and exact extracted payload at:

```text
recovery-cache/RUN_ID/attempt-1/artifact-ARTIFACT_ID/download.zip
recovery-cache/RUN_ID/attempt-1/artifact-ARTIFACT_ID/evidence/
```

Create a descriptor with paths relative to that descriptor:

```json
{"binding":"recovery-binding.json","snapshots":"recovery-api","cache":"recovery-cache"}
```

Pass it as `--controls-recovery descriptor.json` to the existing complete case
auditor, alongside the full original sources descriptor. Its normal collection
path and bounded archive provider are unchanged for the other partitions. The
replacement uses its separate checksum-bound cache. The audit saves both sets
of provenance, checks full arrays and integration outcomes using the original
collector, and replays the original case mathematics only when full coverage
is available. It rejects a replacement if the original output has appeared.

Tests use explicitly synthetic arrays, not new numerical integrations. They
cover unchanged scope, exact run/gate binding, dependency drift, retained
original output, interrupted replacement output, ZIP tampering and isolation
from the original collector. Local numerical workers remain stopped.
