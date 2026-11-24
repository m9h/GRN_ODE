# Continue the full Rohwer diagnostic inventory from verified checkpoints

The first continuation of network 35, BioModel `BIOMD0000000038`, retained
all 750 diagnostic branches. Its completed array audit covers 1,369 full
trajectories across all 32 original partitions. It found 318 terminal
diagnostics: 255 agreements, 23 numerical mismatches and 40 explicit integration
failures. Another 61 diagnostics were interrupted and 371 were unstarted.

This generation resumes those 432 unfinished diagnostics. It preserves all
318 terminal outcomes, including failures, and all 1,369 completed parent
arrays. It does not change the model, integrators, requests, tolerances,
observation grids, partition membership or acceptance criteria. These are
diagnostic results; the full case controls and model audit remain separate
requirements, and this work claims no recovered case or whole-model pass.

## Pinned inputs and lineage

`binding.json` has SHA-256
`ac2be132f47739184dccdb9a6efcdeb8853710d8f8ac4390be231029296089f4`.
It pins every input file here, including complete GitHub run, job and artifact
metadata, the full 32-job selection, and the audited parent file inventories.
The parent is run `44950774489`, source revision
`5fcd8ee18170d9d9d404a84d3d7f7f4c74f4cec5`.

Before integration, the runner verifies the original ZIP size and server
checksum, every extracted byte, parent identity, complete branch membership,
full arrays and terminal diagnostic outcomes. The unchanged first-generation
auditor verifies this parent. Its original 715-array lineage remains intact.

The new output keeps earlier lineage unchanged and records its immediate
parent execution and partial branch records under `generations/2/`. After
computation, terminal diagnostic files must be byte-identical; each completed
partial array must retain its original checksum and request metadata.
Only unfinished requests may be attempted. Unstarted branches precede partial
branches within each original partition.
Attempts that stopped before writing a checkpoint or report retain their
distinct `no_checkpoint` or `no_report` statuses and remain in the resume set.

Later generations use the same runner and collector with an explicitly
hashed binding directory. A later binding names its parent binding by a path
within `python/` and an exact checksum. Generation numbers must be consecutive;
ancestry cycles, changed metadata, shortened selections and ambiguous jobs
are rejected. Historical runner hashes are checked against their recorded Git
revisions. Existing lineage files are retained rather than overwritten.

There is no intra-ODE restart state in this workflow. A completed trajectory
is reused; an interrupted solver request starts again with its original
settings. Calling `compute` twice on the same execution is rejected. Resume
through a new verified generation instead.

## Reproduce the checks

From `python/`, use the locked uv environment:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/continue_rohwer_checkpoint.py check
```

To restore a downloaded parent ZIP without running numerical integration:

```sh
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/continue_rohwer_checkpoint.py restore \
  --index 4 --archive artifact-14738525753.zip --output restored-partition-4
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/continue_rohwer_checkpoint.py audit \
  --index 4 --output restored-partition-4 --audit-output restored-audit.json
```

Production computation is gated by Linux validation in
`.github/workflows/rohwer-first-continuation.yml`. All 32 partitions remain in
the matrix. Each job verifies its parent before its 19,200-second computation
budget, then uploads the output even when numerical diagnostics fail or the
execution is incomplete. Artifact retention is 90 days.

The collector binds all 33 actual jobs, including the passing validation gate,
before accepting a scientific output. It verifies all 750 branches and checks
that all 1,369 parent arrays survive a complete collection. Pending jobs,
missing ZIPs, interrupted diagnostics, numerical failures and verification
errors remain explicit.

```sh
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/collect_rohwer_checkpoint.py bind \
  --run run.json --jobs jobs.json --revision PRODUCER_COMMIT --output selection.json
uv run --locked --extra test --extra jaxkineticmodel \
  python scripts/collect_rohwer_checkpoint.py collect \
  --selection selection.json --snapshots api --archives archives --output collection
```

Run the checkpoint tests alongside the original numerical and array-audit
regressions listed in the workflow. Their synthetic data retain the original
full observation grids; tests exercise terminal failures, completed-request
preservation, multiple generations, interrupted requests and deliberate
corruption without solving new differential equations.

The complete eight-file regression gate passed locally on 24 November 2026:
**152 tests passed**. The pinned source and runtime check also passed with all
750 branches, 318 terminal outcomes, 61 interrupted diagnostics, 371 unstarted
diagnostics and 1,369 parent arrays accounted for. The cloud workflow repeats
this gate on Linux before starting any production integration.
