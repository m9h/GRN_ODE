# Full Ciliberto case inputs, including unsaved controls

This adapter supplies the complete inputs for replaying **all 74 original failed
cases**. It reconstructs **7,334 branch specifications** from the unchanged
candidate plans and calibration. Of those, **7,134** have original saved records;
the other **200** are potential controls never saved by any original partition.
Those 200 are explicitly marked `generated_potential`, with
`original_record_available: false`. They have no invented result or pass flag.

The legacy adapter required every possible control to have an original record.
That invariant remains unchanged for its existing users. This separate adapter
supports the complete Ciliberto scope without editing the integrators, acceptance
thresholds, case scoring or conditional-search algorithm. The queued 260-branch
diagnostic producer also remains unchanged.

## Why the additional controls are necessary

Each candidate case has eight matched controls per trial: untreated, history,
breaker and history-plus-breaker, each with and without a cue. A later trial may
be selected conditionally from the earlier response. Repeating the experiment
with independent solvers can therefore require a control that the original path
never reached. The inventory enumerates every potential third-trial continuation
before looking at new outcomes. The full untreated baseline is also required.

The absent controls affect four cases:

| Original case | Unsaved potential branches |
|---|---:|
| `Kin_a__up--PCdk2_CycE__up` | 92 |
| `PCdk2_CycE__up--Kin_a__up` | 92 |
| `PCdk2_CycErem__up--Kin_a__up` | 8 |
| `Xic_PCdk2_CycE__up--Deg_a__up` | 8 |

The original paths, scores and failures remain separate from those generated
specifications. Both primary and refined solver pairs must eventually replay
their own conditional paths using the unchanged case auditor's scoring rules.
Every potential control must pass, including controls a new path does not reach.

## Authenticated input bundle

The [input release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-ciliberto-full-controls-20261118)
contains the canonical inventory, all 74 original case records and sixteen
compressed original-branch captures. It preserves **7,666 original records** for
the 7,134 observed specifications: repeated specifications from different
partitions retain their separate records. These are historical comparison and
window records, not original raw trajectories.

The 18 input files total **130,459,043 bytes**, plus a checksum manifest. Its
SHA-256 is `ab3b592ed1d25786ff22e4611331e633caf3d2ba0fa00907e4607d865d235857`.
Capture verifies the original partition metadata and compressed archive checksums,
then audits every selected original branch and case. Validation checks the pinned
manifest and every file, regenerates the complete inventory, checks each original
record against the fixed full inventory's fingerprint and repeats all 74 original
case audits. No original failed branch is promoted into a new successful control.

Use a full repository clone so the pinned source revisions are available. From
`python/` in this branch:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-ciliberto-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/fresh-full-control-inputs
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/prepare_ciliberto_full_controls.py check \
  --inputs /path/to/fresh-full-control-inputs \
  --manifest-sha256 ab3b592ed1d25786ff22e4611331e633caf3d2ba0fa00907e4607d865d235857
```

To reproduce the capture, use the original extracted sixteen-partition release
from the [full inventory preparation](../catalog-breaking-ciliberto-full-inventory-20261118/README.md):

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/prepare_ciliberto_full_controls.py capture \
  --original-root /path/to/extracted/catalog-breaking-linux-28 \
  --output /path/to/new-full-control-inputs
```

The capture uses deterministic JSON/gzip serialization. Existing output
directories are rejected. `prepare_inventory()` also provides the authenticated
inventory, model metadata and full 221,001-point grid for later execution and
audit adapters. All 20 observables and the original horizons/resets are retained.

## Validation and remaining work

All **58 targeted local tests pass**, including 20 new input/provenance tests.
The complete local input bundle validates all 7,666 saved records and 74 original
cases. Numerical sources and dependency files remain unchanged. Linux validation
is separate; this input capture performs zero integrations and claims no recovery.

The later **6,859 controls** still require their four requested trajectories,
followed by assembly with the 215 published branches and the 260 diagnostics.
A full-array auditor must consume this input format and replay all 74 cases.
This adapter removes the input-format obstacle; it does not complete that
computation or audit. The original whole-model result remains **548/622**.
