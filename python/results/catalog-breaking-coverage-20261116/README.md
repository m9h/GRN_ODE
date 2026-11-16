# Breaking-screen coverage: 16 November 2026 UTC

The original 35-model inventory now has **33 complete initial-case inventories**
and **25 passing whole-model audits**. Networks 5 (Tyson, six variables) and 29
(Cellière, TGF-β signalling) still have unfinished partitions. The total remains
7,324 planned initial cases; no model, case, control, or late conditional trial
has been removed to obtain these counts.

The new complete inventories are:

| Network / BioModel | Model | Cases passing / attempted | Evidence |
| --- | --- | ---: | --- |
| 2 / 0002 | Edelstein ACh response, species formulation | 624 / 624 | All 16 Linux partitions |
| 15 / 0026 | Markevich MAPK cascade | 398 / 398 | All 16 Linux partitions; independent macOS execution also passes |
| 25 / 0539 | François mixed feedback loop | 79 / 118 | Complete macOS execution; Linux execution still needs two partitions |
| 32 / 0035 | Vilar oscillator | 103 / 204 | All 16 Linux partitions, including the documented repaired continuation |
| 35 / 0038 | Rohwer phosphotransferase system | 137 / 260 | All 16 Linux partitions |

The separate macOS Vilar run passes 107/204 cases. Both results are retained;
they are not combined by choosing whichever run passed an individual case.
The Linux Vilar and Rohwer runs respectively retain 94 and 136 unresolved
conditional decisions. These are completed initial inventories, **not complete
successful conditional searches**. François likewise retains incomplete
integrations and numerical mismatches.

Networks 3, 8, 11, 25, 28, 30, 32, and 35 have terminal inventories with failures.
The four passing models 6, 14, 17, and 33 have no eligible breaking cases under
the original calibration. Their untreated controls pass; this does not provide
positive evidence of memory breaking.

## What was verified

For the four newly collected Linux models, the continuation auditor checked
all 64 original artifact ZIPs and every extracted file against their hashes,
then reran the complete-model auditor. The predetermined partition plans fix
the run, job, producer revision and partition index. All original reports,
failed results, untreated controls and conditional histories remain separate.

The local audit covers the terminal Markevich, François and Vilar reports. It
checks model and calibration hashes, the actual historical Git source objects,
all archived branches and cases, the full control, and each conditional search.

These original producers saved pointwise comparison results and window
summaries, not the complete raw trajectories. The audits check their provenance
and recompute classifications from those summaries; they do not recreate
missing raw observations. Later Radau/Heyoka diagnostics that save full arrays
remain separate evidence and are not counted as whole-model recovery here.

The observation grid remains 0.01, the full horizon reaches 2210 where required,
and the comparison thresholds remain relative 2e-5 and absolute 1e-7. No
clipping, shortened simulation, or relaxed acceptance criterion was introduced.

## Reproduce from the release

The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-coverage-20261116)
contains five packages. `release-assets.json` records their sizes and SHA-256
hashes. Four preserve the original sixteen ZIPs per Linux model; the fifth
preserves the local model reports and every referenced evidence archive.

From this repository's `python` directory, using a full clone with the producer
commits available:

```sh
uv sync --locked --extra test --extra delay
gh release download kinetics-coverage-20261116 --repo m9h/GRN_ODE --dir /tmp/grn-coverage-assets
uv run --locked python results/catalog-breaking-coverage-20261116/reproduce.py \
  --assets /tmp/grn-coverage-assets --output /tmp/grn-coverage-reproduced
```

The output directory must be new. Each package and original ZIP is checked,
freshly extracted, and audited. The result must exactly reproduce the saved
audit, allowing only different extraction-directory names. `--network 2`,
`15`, `32`, or `35` selects a Linux package; `--network 0` selects the local
three-model package. Auditing performs no numerical integration.

`index.json` was rebuilt with the existing
[`build_index.py`](../catalog-breaking-coverage-20261114/build_index.py), which
counts complete-model audits, preserves failed originals, and excludes
branch-only diagnostics. The 35-model goal remains active.
