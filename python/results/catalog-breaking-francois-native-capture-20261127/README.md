# François: capture all controls behind six unresolved third trials

The complete original audit of BioModel BIOMD0000000539 covers 118 cases:
80 pass and 38 retain failures. Six third-trial decisions in four cases could
not be scored because COPASI returned shortened output. Their sixteen affected
branches record a completed RoadRunner integration followed by a COPASI
`Unexpected output shape` error. The historical records omit the raw arrays
and COPASI's underlying solver messages, so the shape errors alone do not
identify why integration stopped.

This fixed experiment selects all forty distinct controls of those six trials
and the full untreated baseline: **41 branches and 82 native integrations**.
Every branch runs RoadRunner and COPASI at its original recorded tolerances,
on the original 221,001-sample grid through native time 2210, with identical
reset schedules. It preserves all 118 original case outcomes. It adds no
threshold changes, solver refinements, model edits or new numerical packages.

The numerical modules, SBML, calibration, `pyproject.toml` and `uv.lock` are
checksummed against revision `cae38e9a6ec4c7567ea6cbf2908778f409a1ebb0`.
The COPASI observer is copied verbatim from the previously tested Vilar
instrumentation at `30eb1e29442748c4fcf443777841537b71e5e8d9`. It forwards the
original call arguments and returns the original object. It additionally saves
raw output, compressed solver logs and messages before the unchanged adapter
accepts or rejects the result. Complete arrays retain their actual returned
timestamps; the original native clock tolerance of 1e-9 remains unchanged.

`plan.json` is reproduced from the complete [published original evidence
bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-francois-inventory-20261125).
All sixteen ZIPs and every bundle member are checksummed during preparation.
Its SHA-256 is
`5e3eb51414365a40ee550e66cc2f034396589614cb708b1a9227eddd90a6a2c8`.
The plan retains original reports, cases, branch provenance and the complete
118-case audit. Shared controls are identified by their original specification
hash; every contributing original occurrence is retained.

## Execute and audit

Use the **Capture unresolved Francois native controls** workflow. Its validation
gate checks the frozen inputs, source and Linux package environment before the
fixed 41-job matrix starts. At most four branches run concurrently. Each job
uploads its complete or interrupted output, including negative results, for
90 days. A green workflow job means the attempt and its evidence were audited;
it does not mean that the two solvers agreed.

For a single branch in the same Linux x86_64/Python 3.12.13 environment:

```sh
cd python
uv sync --python python --locked --extra test --extra delay
uv run --locked --extra test --extra delay python scripts/run_francois_native_capture.py --validate --validate-runtime
uv run --locked --extra test --extra delay python scripts/run_francois_native_capture.py --index 0 --output results/francois-native-parts/branch-0
uv run --locked --extra test --extra delay python scripts/run_francois_native_capture.py --index 0 --audit results/francois-native-parts/branch-0 --output results/francois-native-parts/branch-0/audit.json
```

The independent array audit verifies the exact branch, source, settings,
sample inventory, input protocol, output checksums, raw/accepted COPASI values
and complete reset counters. It recomputes pointwise comparisons and window
summaries. The final trial replay requires all 41 branches and records each
of the six original-path decisions, including any remaining native failures.
It does not substitute these selected trials for a full conditional-case
recovery or add passing cases to the original 80/118 count.

The offline `scripts/collect_francois_native_capture.py` first binds all 41
actual job IDs after the Linux gate passes. Given complete saved `run.json`,
`jobs.json` and `artifacts.json` API snapshots, it checks original ZIP sizes
and SHA-256 digests, rejects unsafe archive members, and independently audits
every available output. Pending jobs, missing artifacts, interrupted attempts
and numerical failures remain distinct. It replays the six trials only after
all 41 selected native attempts have independently auditable terminal records.
The collector does not download, dispatch, retry or integrate anything.

All nine local production workers remain outside this cloud experiment.
