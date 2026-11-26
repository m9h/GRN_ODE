# Assemble all Rohwer checkpoint generations for the complete case audit

Rohwer's model has 123 original failed memory-breaking cases requiring 11,674
diagnostic and control branches. Earlier checkpoint continuations restored and
extended the 750 first-stage diagnostics, but the original full-case entry point
accepted only the initial run. The new `audit_rohwer_generation_cases.py` connects
those later generations to the same complete-case analysis. Its scope, branch
store, case scoring and conditional replay functions are identical to the prior
auditor at revision `762d8812b516c10e90892a230a0baee3423988b6`.

## Evidence selection

`collect_rohwer_diagnostic_generations.py` validates every actual job in each
32-partition generation, the successful Linux gate, original ZIP identities,
producer revisions and recursive checkpoint ancestry. The first supplied
generation must be generation 2 with all 32 original outputs available.
Subsequent generations must be consecutive and bound to the preceding actual
run and complete parent selection. For each original partition, the newest
terminal job with an uploaded artifact is selected. A newer pending job keeps
its earlier verified parent; a corrupt uploaded result is an error and never
silently falls back to older data.

The captured generation-3 snapshot contains 17 available archives. Together with
the other 15 generation-2 archives it covers all 32 partitions and all 750
first-stage branches, including unfinished branches and terminal failures.
These are API/selection counts, not claims that every diagnostic is complete.

Five original checkpoint/array validators are copied byte-for-byte from
`fcf7fd8cf975bc9171370e05789661d9da4d35b4` and their hashes are checked before use.
The original numerical code, models, requests, grids, dependencies and acceptance
rules remain frozen. The adapter only adds the wrapper-status field needed by
the combined collector; branch comparisons and response windows remain those
computed by the frozen independent array auditor. Each selected ZIP is rehashed,
its full extracted inventory is compared with the ZIP, all checkpoint lineage
is checked, and the original branch arrays are independently reaudited.

The previous `audit_rohwer_full_cases.py` remains unchanged: ongoing later-control
jobs are bound to that exact source. This separate entry point also supports the
already implemented `--controls-recovery` and repeatable
`--controls-continuation` options. The separate workflows remain independently
auditable; no computation is relaunched by the combined auditor.

## Reproduction

Obtain the pinned scientific-input release
`kinetics-rohwer-full-controls-20261118` and the retained original computation
ZIPs. Prepare the ordinary two-stage `sources.json` descriptor required by the
[original full-case guide](../catalog-breaking-rohwer-full-case-audit-20261118/README.md).
Both complete original first-stage and later-stage selections remain mandatory.

Copy `diagnostic-generations.example.json` and set its `cache` paths to the
verified generation-2 and generation-3 caches. Cache layout is
`RUN_ID/attempt-1/artifact-ARTIFACT_ID/download.zip` with the extracted files in
the adjacent `evidence/` directory. Selection and snapshot paths are relative to
the descriptor; binding paths are relative to the repository's `python/` folder.
Keep full `run.json`, `jobs.json` and `artifacts.json` API snapshots. Updating a
snapshot must preserve the complete original selection and all earlier evidence.

From `python/`:

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/audit_rohwer_generation_cases.py audit \
  --inputs /path/to/released-inputs \
  --sources /path/to/sources.json \
  --diagnostics-generations /path/to/diagnostic-generations.json \
  --output /path/to/new-audit
```

The output must be new and outside every input/cache directory. It records the
original stage snapshots, every generation's snapshots, the selected generation
and actual producer for each partition, frozen-validator hashes, independent
branch windows and hashes, and all missing/error states. It checks snapshot
immutability again after collection. No case replay occurs until all 11,674
required branch outcomes are available and verified. A completed numerical
failure remains a failure; an unfinished trajectory remains incomplete.

## Checks and limitations

Tests cover full ancestry and job-page completeness, changes to source/attempt
identity, pending-child retention, archive selection, changed lineage and arrays,
and the separate diagnostic response-window format. They also compare the scope
and case-math functions structurally with the unchanged original auditor.
Synthetic test arrays do not count as scientific results. The Linux workflow
checks the released full scope and frozen runtime without performing numerical
integrations or launching any computation jobs.

The combined audit still requires the remaining cloud outputs and complete
case/control validation. Connecting existing evidence does not by itself add a
new trajectory, recovered case or passing whole-model result.
