# Recover sixteen Marhl tasks that never produced output

The full Marhl precision experiment contains 1,520 numerical tasks: four
implementation/precision combinations for each of 380 branches needed by the
twelve original failed cases. Its equations, reset protocols, observation
grids, arithmetic precision and acceptance criteria remain unchanged.

Sixteen original jobs were cancelled with no runner assignment, no recorded
steps and no artifact. Their task indices are 33, 34, 36, 287, 536, 537, 789,
1042, 1043, 1045, 1046, 1047, 1297, 1298, 1299 and 1302. They are unfinished
computations, not recorded numerical failures. The original checkpoint
continuation cannot restore them because no checkpoint exists.

This recovery starts exactly those sixteen original numerical tasks. It keeps
every other task in the complete collection selection, including the separate
56 checkpoint continuations. It never restarts the active original workflows.
Completed numerical failures elsewhere are retained as scientific outcomes.

## Evidence and unchanged numerical implementation

`binding.json`, SHA-256
`e83a84866d7cd5eefbdc1e2ac1c967fd2e98731dce2cd5753cb057c230d8ec0f`,
pins the complete original task selection, the sixteen missing-output records,
and all six original run/job/artifact API snapshots. The original producer is
`a3778b8cbb8bfdc16a9ddd4bbe84dd213fdf1022`.

The wrapper and collector check every original numerical and cloud-source file
against that producer. Only orchestration, collection and the separate audit
workflow change. The original numerical worker is called with the original
task index, full immutable plan, and four-hour cooperative execution budget.
Dependencies use the existing frozen uv requirements. Each job also has the
original five-hour hard timeout and an upload margin.

Before starting, a worker queries the exact cancelled parent job again. It
rejects active jobs, changed run attempts or sources, recorded execution steps,
runner assignments, or an existing parent artifact. Its output records the
original binding and observed API evidence, plus the actual new workflow,
job, source revision and complete source-file hashes.

The existing `marhl-precision-collection.yml` workflow gates computation on
Linux tests, the unchanged complete case inventory, and verification of all
sixteen original missing-output records. The default recovery matrix contains
all sixteen tasks. An explicit subset is permitted only for a later recovery
checkpoint continuation.

## Collection and subsequent checkpoints

The full selection retains 1,520 entries. A recovered task has an explicit
`recovery_revision` and `missing_output_parent`; its cancelled original job
and API records remain part of the collected provenance. The collector applies
the original full-array, protocol and runtime checks to the numerical payload.
It accepts neither a renamed historical result nor a dropped task.

If a recovery job reaches its time limit, its checkpoint can be continued with
this same runner and source revision. The original exact-state loader verifies
the checkpoint in the matching Linux runtime before any resumed integration.
The collector preserves all earlier attempts, original observation prefixes,
and completed arrays, and follows the explicit `previous` chain. A restored
complete trajectory is reused without another integration.

The unchanged complete-case auditor consumes the combined original,
checkpoint-continuation and recovery selections. Neither submission, software
tests nor a partial array count establishes a complete case or whole-model pass.

## Reproduction

From `python/`, use Python 3.12.13 and the existing frozen requirements:

```sh
uv venv .venv-marhl --python 3.12.13
uv pip install --python .venv-marhl/bin/python -r environments/marhl-full-precision-requirements.txt
.venv-marhl/bin/python -B scripts/run_marhl_missing_output.py check
.venv-marhl/bin/python -B scripts/collect_marhl_precision.py check
```

After the Linux gate passes and all actual recovery jobs exist, bind the full
selection using complete API snapshots and the exact published recovery commit:

```sh
.venv-marhl/bin/python -B scripts/run_marhl_missing_output.py bind \
  --selection existing-full-selection.json --snapshots api \
  --run-id RECOVERY_RUN --revision RECOVERY_COMMIT --output new-full-selection.json
.venv-marhl/bin/python -B scripts/collect_marhl_precision.py collect \
  --selection new-full-selection.json --snapshots api --archives archives --output collection
```

For a later checkpoint continuation, supply its exact parent run and original
task indices to both the workflow inputs and binding command using
`--resume-run PARENT_RUN --task-indices '[33,34]'`. Original parent and all
intermediate recovery snapshots and ZIPs remain required for collection.

## Validation on 24 November 2026

The nine-suite local gate passed **250 tests**, with six Heyoka-dependent checks
skipped because Heyoka is absent from the local audit environment. Linux
validation installs the existing full requirements and repeats every suite
before production recovery is allowed.

A fresh real-data collection with the updated collector verified all 222
available original archives. All 1,520 task judgments match the previous
collector; all nineteen completed branch-audit files are byte-identical.
The result remains 166 complete arrays, nineteen complete branches, and no
verification errors. This is compatibility evidence, not additional simulated
trajectories or recovered cases.
