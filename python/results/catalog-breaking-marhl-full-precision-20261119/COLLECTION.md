# Collecting and replaying the complete Marhl precision computation

This collector covers **all 1,520 tasks, 380 original branch specifications and
twelve failed Marhl cases**. The 88 generated potential controls, untreated
baseline, complete observation grids and original acceptance thresholds remain
required. The numerical producer is frozen at
`a3778b8cbb8bfdc16a9ddd4bbe84dd213fdf1022`. The collector adds no integrations and
does not alter its equations, protocols, tolerances, checkpoints or task plan.

The four requests are Heyoka at 128 and 192 bits and mpmath at 128 and 192 bits.
Every complete branch is compared across all six pairs at every original
observation. Both implementations use Taylor methods; these are not two
different integrator families. Saved observations are binary64. Internal restart
states retain their original precision.

## Preserve and bind the inputs

Keep the original GitHub artifact ZIPs and the complete API responses. For each
selected run and attempt, the input layout is:

```text
api/<run-id>/attempt-<attempt>/run.json
api/<run-id>/attempt-<attempt>/jobs.json
api/<run-id>/attempt-<attempt>/artifacts.json
archives/artifact-<artifact-id>.zip
```

`jobs.json` must contain every page from that exact attempt. `artifacts.json`
must contain every artifact page for that run. The collector requires the API
`total_count` to equal the complete unique row inventory. Download ZIP bytes
without terminal escape filtering; for example:

```sh
gh api --allow-escape-sequences \
  repos/m9h/GRN_ODE/actions/artifacts/ARTIFACT_ID/zip > archives/artifact-ARTIFACT_ID.zip
```

Create `batches.json` as a six-element JSON array, in batch order 0 through 5.
Each entry has integer fields `batch`, `run_id`, and `run_attempt`. The first five
batches contain 256 tasks and the last contains 240. Bind the selection after
the six Linux gates pass and their matrices exist. The computation jobs may
still be queued or running. Binding does not depend on which numerical tasks
succeed.

From `python/`, use an isolated uv environment:

```sh
uv venv /private/tmp/grn-marhl-audit --python 3.12.13
uv pip install --python /private/tmp/grn-marhl-audit/bin/python \
  -r environments/marhl-checkpoint-requirements.txt
/private/tmp/grn-marhl-audit/bin/python -B scripts/collect_marhl_precision.py check
/private/tmp/grn-marhl-audit/bin/python -B scripts/collect_marhl_precision.py bind \
  --batches batches.json --snapshots api --output selection.json
```

The plan SHA-256 is
`d5589646d0f6393eaf7a76635276e6ac585d949cc2718e52c1ccc7e3df83abb3`.
The original 380-branch inventory SHA-256 is
`a17f4c58c46e11aa890521874dd2dfb821f40dfacc3446bf0ba695e20afeaa42`.
The `check` command reconstructs all twelve original case records and controls
from the pinned source evidence; it does not run the differential equations.

## Collect evidence without promoting partial work

```sh
/private/tmp/grn-marhl-audit/bin/python -B scripts/collect_marhl_precision.py collect \
  --selection selection.json --snapshots api --archives archives \
  --output collection-new
```

Use a new output directory on each collection. The collector preserves the
selection, complete API snapshots, original ZIPs, and extracted bytes. It checks
run, attempt, job, artifact name, creation time, server size and SHA-256, frozen
producer source hashes, numerical request, runtime and full protocol identity.
The portable checkpoint checks verify payload checksums, finite observations,
precision and source identity. They do **not** claim an exact MPFR restart-state
validation in another runtime; the producer's matching Linux environment does
that before every resume.

Completed arrays must have the entire original grid, finite observations and
matching final checkpoints. Only four complete arrays can enter a branch's
six-way comparison and window summarization. A failure, interrupted checkpoint,
orphan trajectory, absent artifact or verification error remains visible and
cannot count as a complete branch. No alternative successful job is selected.

For continuation, keep every parent snapshot and ZIP. After the explicitly
submitted continuation matrix exists, replace only its declared terminal parent
tasks in a new selection:

```sh
/private/tmp/grn-marhl-audit/bin/python -B scripts/collect_marhl_precision.py rebind \
  --selection selection.json --snapshots api --run-id CONTINUATION_RUN_ID \
  --attempt 1 --indices '[0,2]' --output selection-next.json
```

This retains all 1,520 tasks and the full earlier selection for each resumed
task. Collection authenticates each ancestor ZIP, restoration history and
original report. Earlier observation prefixes must remain bit-for-bit unchanged;
a completed parent must remain unchanged in its entirety.

## Replay all twelve cases

```sh
/private/tmp/grn-marhl-audit/bin/python -B scripts/collect_marhl_precision.py audit \
  --selection selection.json --snapshots api --archives archives \
  --output complete-case-audit-new
```

The final audit reauthenticates the original archives and recomputes the array
comparisons before scoring. It reconstructs the original untreated baseline,
all eight controls per trial, repeated breakers, and every possible third
breaker. The original scoring and conditional-search code is reused unchanged,
with explicit aliases for the four high-precision input slots. The aliases do
not imply new RoadRunner or SciPy integrations.

The 128-bit and 192-bit conditional paths are both reported, alongside the
original path. Literal MATLAB zero-boundary path differences remain visible
even if controlled classifications agree. An unused possible control can still
prevent recovery; early stopping cannot hide a missing or disagreeing control.
Contradictions with earlier passing window summaries are recorded separately.

The 26 historical passing cases remain identified as historical and are not
rerun by this twelve-case audit. A passing selected-case audit requires all
1,520 full arrays, all twelve passing case replays, and no retained historical
window contradiction. It is not an automatic whole-model completion claim.

## Verification

The tests use synthetic full-grid arrays and invented control cubes for
transport and scoring checks. They are not biological results. They cover all
1,520 job bindings; incomplete API pages; changed source, runtime, artifact,
grid, final samples or checkpoints; retained failures; all twelve original
case records; baseline and unused-control requirements; missing precisions;
controlled threshold disagreements; and literal zero-boundary paths. Continuation
tests independently recheck parent archives and reject changed observation
prefixes, lineage, or completed evidence. Linux CI runs the portable collector
and case-audit suite in an isolated uv environment.
