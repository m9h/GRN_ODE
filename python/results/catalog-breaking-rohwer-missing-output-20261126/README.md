# Recover Rohwer's missing partition 23

The hosted runner for [original job 135270755047](https://github.com/m9h/GRN_ODE/actions/runs/44419997278/job/135270755047)
lost communication before uploading an artifact. The saved annotation records
the infrastructure failure. Its numerical outcome is unknown.

This capture retains both original runs and all **512 partitions**, covering
10,924 later controls. The complete scientific audit still requires 11,674
branches and all 123 selected cases. The original archive inventory contains
232 ZIPs totaling 21,323,971,346 bytes. Archive availability is not evidence of
numerical agreement or completed case validation.

Only partition 23 may be retried. Its 22 original branches, complete sampling
grids, reset trains, requests, tolerances, solver versions, numerical producer
and locked environment remain unchanged. All other 511 selections are retained.
The original collector's source and default producer identities are unchanged;
an isolated instance handles the explicitly bound new run. Existing outputs and
numerical failures must remain in the final audit.

## Validate and execute

From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python scripts/rohwer_missing_output.py check
```

The `rohwer-missing-output-recovery.yml` workflow validates the frozen runtime,
full released inputs, original source hashes and both batches on Linux before
computation. Dispatch it once with `operation=compute` and `partitions=[23]`.
It invokes the unchanged original producer with batch 0, partition 23 and the
original 19,200-second budget. Save the accepted request; queued work does not
authorize a duplicate dispatch.

After the successful validation gate creates the actual compute job, capture
the full run and jobs API responses and bind the exact commit:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/rohwer_missing_output.py bind \
  --run recovery-api/run.json --jobs recovery-api/jobs.json \
  --revision FULL_COMMIT_SHA --output recovery-binding.json
```

## Preserve and audit the replacement

Keep complete `run.json`, `jobs.json` and `artifacts.json` snapshots. Verify the
original ZIP against GitHub's SHA-256 and size. Preserve it and its exact
extraction at:

```text
recovery-cache/RUN_ID/attempt-1/artifact-ARTIFACT_ID/download.zip
recovery-cache/RUN_ID/attempt-1/artifact-ARTIFACT_ID/evidence/
```

Use a descriptor with paths relative to that descriptor:

```json
{"binding":"recovery-binding.json","snapshots":"recovery-api","cache":"recovery-cache"}
```

Supply it as `--controls-recovery descriptor.json` to
`scripts/audit_rohwer_full_cases.py audit`, alongside the complete original
sources descriptor and input bundle. Both original batches and the replacement
provenance are retained. The audit rejects replacement if an original artifact
appears, checks every available array and outcome with the existing collector,
and runs the unchanged case mathematics only when complete coverage is present.

Synthetic tests cover both batches, exact run and gate identity, installed
dependency drift, source hashes, original output retention, missing checkpoints
and tampered ZIPs. Tests and orchestration add no scientific pass. Local
production integrations are not started by this recovery preparation.
