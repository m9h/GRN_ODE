# Vilar paired-case controls: complete control batch, incomplete cases

All 23 complementary control trajectories completed in [run 43510523842](https://github.com/m9h/GRN_ODE/actions/runs/43510523842). Every control passed a fresh comparison of the saved RoadRunner, 128-bit Taylor and 192-bit Taylor arrays. The Linux validation job also passed its 102 tests.

These controls support the three unresolved paired cases in BioModels **BIOMD0000000035**, the Vilar genetic oscillator: `DAp__up--DR__up`, `DAp__up--DRp__up`, and `DAp__up--MR__up`. Twelve arms per case distinguish responses to a cue, training, their combination, and controls; shared arms reduce the total to 32 distinct trajectories. All trajectories retain the original 0–300 time interval, 30,001 samples, interventions, reset schedules, and acceptance thresholds.

The aggregate audit includes three completed stimulated trajectories from [run 43483480217](https://github.com/m9h/GRN_ODE/actions/runs/43483480217), partitions 5, 12 and 15. Their 128-bit and 192-bit Taylor solutions converge, but each still disagrees with RoadRunner under the declared criterion. Agreement at two precisions of one method does not constitute an independent-method validation.

| Evidence | Completed | Outcome |
| --- | ---: | --- |
| Complementary controls | 23/23 | All three integrations agree |
| Required stimulated trajectories | 3/9 | Taylor precision convergence; native mismatch |
| Distinct trajectories for the three cases | 26/32 | Six trajectories missing |
| Recovered cases | 0/3 | All three cases remain incomplete |

Vilar therefore remains **139/142 validated paired cases**; the catalog remains **4,205/4,208**. Successful control jobs do not establish case recovery or provide a biological conclusion about the unresolved cases.

## Evidence and provenance

`partial-case-audit.json` was recomputed from all 78 complete arrays using `audit_cases(..., allow_partial=True)`. It checks the complete requested grids, model and intervention identity, source hashes, producer environment, and numerical comparisons before scoring cases. It names all six missing branches and every remaining mismatch. The `allow_partial` option records missing coverage explicitly and does not relax numerical acceptance.

`sources.json` records the original run, producer revision, artifact ID, ZIP digest, member hashes and portable archive path for every trajectory. The `run-*/partition-*` directories retain the original reports, executions and individual array audits. Original collector paths are retained as provenance; they are not needed for reproduction. Checkpoint files are preserved unchanged, but this completed-array audit does not restore or validate the serialized checkpoint state.

The [release bundle](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-vilar-controls-20261114) contains these metadata and all 26 unchanged workflow ZIP archives, including the complete numerical arrays. `release-manifest.json` records the outer archive digest and every packaged file hash.

The case plan file SHA-256 is `d58efc2322d6c5821869d80173955bea9a2e7a598ef92045e408f2abaa9b555f`. Its canonical JSON signature, used by the auditor, is `e76cf0e0333503fe59aed85164658f5ee29ffec38a3b2000cb8a54f45fac8f0e`; these are different hashing conventions for the same plan.

## Reproduce with uv

Use the `precision-case-controls` source revision pinned by this release, download and unpack the release bundle, then run from the repository's `python` directory:

```sh
uv sync --locked
uv run --locked python results/catalog-paired-vilar-controls-complete-20261114/reproduce_audit.py \
  --source . \
  --bundle /path/to/vilar-controls-20261114 \
  --output /path/to/fresh-vilar-audit
```

The script verifies archive and member hashes, extracts only the workflow's allowed file layout, recomputes the full-array audit, and compares it with the saved result. Only absolute evidence-directory paths are ignored in that comparison. A successful run prints 26 audited trajectories, six missing trajectories and zero recovered cases. The numerical integrations are not rerun.

The original producers used Linux x86-64, Python 3.12.12, Heyoka 7.13.2, NumPy 2.5.4, python-libsbml 5.21.2, libroadrunner 2.11.0 and pandas 3.1.1. Package and source provenance remain embedded in the reports. The project and Linux workers use uv. The separate macOS Heyoka environment uses micromamba to supply its compiled dependencies; it is not required merely to audit these saved arrays.
