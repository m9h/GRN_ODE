# Complete Rohwer case-control inputs

The complete input bundle preserves all **123 originally failed cases** of
network 35, BioModel **BIOMD0000000038**. The SBML model is named
`Rohwer2000_Phosphotransferase_System`; these experiments perturb its model
variables with the original repeated-reset protocol. They are computational
tests of the paper's memory and breaking criteria, not new biological observations.

The original native-solver audit remains **137/260 cases passing**, with 136
unresolved conditional decisions. Complete-case reanalysis requires **11,674
distinct branches**, including a full untreated baseline. The existing
[750-branch diagnostic run](https://github.com/m9h/GRN_ODE/actions/runs/44401097371)
is a subset of that inventory. The other **10,924 controls** remain required,
regardless of the diagnostic outcomes. At four solver requests per branch, these
later controls require 43,696 trajectories in addition to the queued 3,000.

## Observed records and generated controls

The adapter first verifies the 16 original artifact ZIPs and extracted files and
reproduces the complete original 260-case audit. It then selects original records
needed by the 123 failed cases and generates every possible first, second and
eligible third intervention using the unchanged case compiler.

| Scope | Count |
|---|---:|
| Original failed cases preserved and replayed | 123 |
| Required distinct branch specifications | 11,674 |
| Distinct specifications present in original saved evidence | 10,826 |
| Original records across partitions, including shared controls | 11,247 |
| Potential controls absent from every original saved path | 848 |
| Cases missing potential controls in their original partition | 15 |
| Already selected failed-branch diagnostics | 750 |
| Remaining controls, including all 848 generated specifications | 10,924 |

An observed branch retains its partition, original pass/failure flag and complete
record fingerprint. An unsaved potential control has
`kind: generated_potential` and `original_record_available: false`; it receives
no invented original result. Even partition 9, which has no selected failed
cases, contributes 29 observed shared-control records.

Both original engines agree on the source eligibility for all selected cases.
The adapter refuses to transfer ambiguous eligibility. Original solver settings,
declared per-case overrides, all eight history/intervention/rechallenge control
combinations, reset timing and observation horizons remain unchanged. The full
grid contains 221,001 samples through time 2,210 and all 17 observables; shorter
branches retain their original time 1,410 or 1,810 endpoints.

## Verify the public input bundle

The [input release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-rohwer-full-controls-20261118)
contains `inventory.json`, `original-cases.json`, 16 original-record gzip files,
`manifest.json` and the validation result. The 18 input files total
**150,923,578 bytes**. The manifest SHA-256 is:

```text
dd1f300d0fc760743a39d6360cb0aae19ff0ee69a3f6b991aada12493045fe0f
```

Use a full clone and an isolated environment. From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
gh release download kinetics-rohwer-full-controls-20261118 --repo m9h/GRN_ODE \
  --dir /path/to/rohwer-full-controls
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/prepare_rohwer_full_controls.py check \
  --inputs /path/to/rohwer-full-controls \
  --manifest-sha256 dd1f300d0fc760743a39d6360cb0aae19ff0ee69a3f6b991aada12493045fe0f \
  --check-runtime
```

Validation checks every input byte, reconstructs the full inventory independently
from the pinned original reports and calibration, audits all selected original
records and cases, and reproduces their origins. `--check-runtime` additionally
checks the numerical dependencies and installed implementation used by the queued
diagnostic producer. No ODE integrations are performed.

To reconstruct the bundle from the preserved original collection, use the same
fixed [selection plan](../catalog-breaking-completed-35-20261116/selection-plan.json):

```sh
uv run --locked --extra test --extra jaxkineticmodel python \
  scripts/prepare_rohwer_full_controls.py capture \
  --collection-root /path/to/original-rohwer-collection \
  --output /path/to/new-input-bundle
```

The collection must retain its `collection.json`, selected original ZIPs and
extracted evidence. Existing output directories are rejected. This input adapter
does not change the queued diagnostic source or any stopped local worker.

## Remaining computation and evidence

This release supplies inputs. It does not report new trajectories, convergence
or case recovery. The 10,924 later controls still need an execution plan and
computation, and all 11,674 branch outcomes must ultimately feed an independent
full-array case audit. That audit must retain the baseline, all original and
potential controls, original versus recomputed conditional paths, solver failures
and numerical disagreements. Diagnostic branch counts cannot establish recovered
cases or change whole-model coverage.

Local tests and the real input/runtime validation are recorded in
[local-validation.json](local-validation.json). The input manifest is also tracked
as [input-manifest.json](input-manifest.json); the large input files belong to the
release so they can be downloaded and verified independently.

All **24 new tests and 70 combined targeted tests pass** locally. The 24 new
tests also pass with optional JAX imports blocked. Workflow lint and real
complete-input validation with the pinned numerical runtime pass. Linux
validation remains pending.
