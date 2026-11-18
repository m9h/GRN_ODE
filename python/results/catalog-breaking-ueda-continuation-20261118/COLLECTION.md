# Collect and audit the complete Ueda continuation

The producer is frozen at `b585ee97de7000c2ec1afe5454216629601eee87`.
[Run 44393623529](https://github.com/m9h/GRN_ODE/actions/runs/44393623529) must pass
validation job `135117575320` before creating its 32 computation jobs. At
**2026-11-18 20:51 UTC**, that gate is still queued. No cloud completion or
additional case recovery is claimed.

The separate collection branch adds `scripts/collect_ueda_continuation.py`.
Numerical sources, producer wrappers, dependency files, experiment plan and
complete-case auditor remain unchanged. Collection performs no integration,
network requests or workflow dispatch.

## Bind every job before collecting outcomes

Once the validation gate passes and all 32 jobs exist, capture the full run and
job API responses. Use `per_page=100`; the collector checks the returned total
against the number of records, so an incomplete page is rejected. Then, from
`python/` in this collection revision:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python scripts/collect_ueda_continuation.py bind \
  --inputs results/catalog-breaking-ueda-continuation-20261118 \
  --plan-sha256 4bdd6c344573dac23ba5007e3587c19a2fe6f2839f5972a68b0fd155ce3ba709 \
  --run /path/to/api/run.json --jobs /path/to/api/jobs.json \
  --output /path/to/fixed-selection.json
```

Binding verifies the successful gate's run, source revision and attempt. It
requires every predetermined partition exactly once and records immutable job
IDs, names, branch memberships and artifact names. This selection is never
rewritten to prefer successful outcomes. A queued gate cannot create a selection.

## Preserve original artifacts and verify their complete arrays

Save updated `run.json`, `jobs.json` and `artifacts.json` API responses in one
snapshot directory. Download each terminal selected job's original ZIP as
`artifact-ID.zip`, including artifacts from failed jobs. Retain incomplete
results and original ZIP bytes. The offline collector checks source/run/attempt
identities, artifact creation times, ZIP size and digest, safe extraction, and
every extracted file before reading numerical evidence:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/collect_ueda_continuation.py collect \
  --inputs results/catalog-breaking-ueda-continuation-20261118 \
  --selection /path/to/fixed-selection.json --snapshots /path/to/api \
  --archives /path/to/original-zips --output /path/to/collected
```

Each saved array must retain the expected time grid, all observables, all resets,
original requests and checksum. All six comparisons are recomputed from every
observation. A consistent numerical mismatch is retained as a mismatch; a
recorded solver failure remains incomplete. An interrupted active integration
cannot count as a finished attempt. A cache hit repeats the ZIP and extraction
verification. Nothing is downloaded, restarted or retried by this command.

`ready_for_case_audit` means every fixed integration attempt has finished with
an explicit result or failure. It does **not** mean the arrays agree or a case
has recovered. Partial attempts, missing artifacts and verification errors are
reported separately and prevent assembly.

## Assemble all 323 branches and replay the four complete cases

When the collection permits assembly, repeat the collection command with:

```sh
  --assemble /path/to/fresh-assembled-evidence \
  --preserved /path/to/observed-source \
  --restored /path/to/preparation/restored-imports
```

The original snapshot is checked against its complete manifest. Assembly uses
156 complete preserved branches, 24 published imports (ten overlap), and all
153 fixed new branches. It never substitutes an older favorable array for a
failed new calculation. New lineage records bind cloud outputs to their
original ZIPs; the historical report remains unchanged in a separate file.

The unchanged complete-case auditor then requires the full untreated baseline,
every original and potential control, all conditional decisions and consistent
controlled response classifications. Only its result can recover any of the
four cases. The original model result remains 298/302; selected-case recoveries
stay separate until incorporated into a whole-model audit. All original raw evidence and new ZIPs
must accompany the final reproducible release; the small report files alone
are not a substitute.

## Validation

**48 targeted local tests pass**, including 14 new collector tests, ten fixed
continuation tests and 24 existing complete-case audit tests. The collection
branch's Linux validation workflow also includes the new collector tests;
that cloud result is separate from the completed local checks.

The collector's tests cover missing jobs and controls, wrong source or attempt,
unsafe ZIP paths, altered extracted files, damage to the last observation,
retained numerical mismatches and failures, running checkpoints, and assembly
without fallback to an older success. Synthetic transport fixtures are not
experimental evidence. A separate real-data check reads four full preserved
trajectories with 221,001 observations and 13 observables and reproduces all six
comparisons exactly against the prior preservation audit, without integration.
Its recorded result is in `collector-real-branch-check.json`, which binds the
check to the collector source hash and preserved record hash.
