# Continue the first Rohwer diagnostic inventory

The first diagnostic run, [44401097371](https://github.com/m9h/GRN_ODE/actions/runs/44401097371),
reached the execution limit in all 32 partitions. Its 750 fixed branches represent
the original failed branches of the 260-case Rohwer2000 inventory. The completed
parent audit verified 715 full trajectories and 166 terminal diagnostics:
134 confirmed branches, 12 numerical mismatches, and 20 diagnostics with explicit
integration failures. Another 32 diagnostics were interrupted and 552 had not
started. These are branch diagnostics, not recovered cases or a whole-model pass.

This continuation reuses that evidence. The numerical implementation, model,
four solver requests, complete observation grids, reset schedules, tolerances,
and 32 partition memberships are unchanged from producer
`40fe82344d8dacb2d79ebdc4087ee52beb90a091`. The parent collector remains unchanged
at `12c0693df1d68d1736b274a9364e1ef7b2533b06`.

## Preservation and scheduling

Each job downloads exactly its original artifact, verifies the API-bound ZIP
size and SHA-256, extracts only safe regular files, and independently reaudits
its whole original partition. The recorded API snapshots, all-32 selection,
and continuation requirements in this directory are byte-identical to the
21 November audit inputs. Their checksums are pinned in
[`continue_rohwer_first.py`](../../scripts/continue_rohwer_first.py).
The requirements file's `implementation_state` describes that earlier capture;
it is deliberately preserved rather than rewritten as implementation proceeds.

All terminal diagnostics stay byte-identical, including the 12 mismatches and
20 explicit failures. Every completed trajectory in an interrupted diagnostic
also stays byte-identical, with its original request metadata retained in
`lineage/`. The unchanged diagnostic child uses `--resume` to read those arrays.
It does not checkpoint inside an unfinished ODE integration: an unfinished
solver request starts again. The original ZIPs remain the parent evidence.

Within each unchanged partition, unattempted branches run first in their
original relative order; interrupted branches follow. This prevents the same
slow request from repeatedly preventing all untouched work from being attempted.
It changes scheduling only. The entire 750-branch inventory remains required.
A job has a 19,200-second computation budget and always attempts to upload its
output. A timeout, mismatch, or integration failure remains visible. A second
invocation against the same working output is rejected: another continuation
requires a separately verified parent and explicit selection.

The new collector binds all 32 actual job IDs after the Linux gate succeeds.
It keeps missing artifacts, pending jobs, incomplete diagnostics and failed
comparisons in its output. It reaudits every available full array and checks
preservation of all 715 parent arrays when all partitions have been collected.
It never turns branch agreement into a claim about a complete case.

## Reproduce validation and collection

Use a full Git clone, Python 3.12.13 and the locked uv environment:

```sh
cd python
uv sync --python python --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python scripts/continue_rohwer_first.py check
uv run --locked --extra test --extra jaxkineticmodel python -m pytest -q \
  tests/test_rohwer_first_continuation.py tests/test_rohwer_first_continuation_collection.py \
  tests/test_rohwer_breaking_collection.py tests/test_rohwer_breaking_diagnostics.py \
  tests/test_scipy_breaking_diagnostic.py tests/test_scipy_breaking_audit.py
```

The tests use synthetic full-grid arrays; they do not rerun the scientific
integrations. The separate `restore` command reaudits an actual parent ZIP
without performing integrations. For example, partition 4 contains confirmed,
mismatched, explicitly failed and interrupted diagnostics:

```sh
gh api repos/m9h/GRN_ODE/actions/artifacts/14508577237/zip > parent-4.zip
uv run --locked --extra test --extra jaxkineticmodel python scripts/continue_rohwer_first.py \
  restore --index 4 --archive parent-4.zip --output /tmp/rohwer-parent-4
```

The workflow defaults to validation; its explicit `compute` operation continues
all 32 partitions after the gate. Bind the actual dispatched run and all job
pages before collecting its outputs:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/collect_rohwer_first_continuation.py \
  bind --run snapshots/run.json --jobs snapshots/jobs.json \
  --revision PRODUCER_COMMIT --output selection.json
uv run --locked --extra test --extra jaxkineticmodel python scripts/collect_rohwer_first_continuation.py \
  collect --selection selection.json --snapshots snapshots --archives archives --output collected
```

`snapshots/` must contain the unmodified run API response and complete combined
job and artifact pages (`run.json`, `jobs.json`, `artifacts.json`). Preserve each
original ZIP as `archives/artifact-ID.zip`. The collector checks API identities,
job timing, ZIP checksums, extracted bytes, numerical sources, all selected
branch grids and completed parent provenance. It writes `collected/status.json`.

Finishing this first diagnostic inventory still leaves the separate 10,924
later-control branches and the full conditional replay of all 123 originally
failed Rohwer cases. A completed diagnostic with failed integrations is a
documented outcome, not a validated numerical trajectory.
