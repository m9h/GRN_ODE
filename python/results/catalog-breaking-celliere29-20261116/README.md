# Cellière TGF-β model: complete conditional breaking audit

On 16 November 2026 UTC, network 29, **BIOMD0000000600**, completed its
original sixteen-partition inventory. All **1,088 initial cases** pass the
whole-model audit, including **34,816 conditional trials**, **297,063
response-trials**, and the full untreated controls. There are no unresolved
conditional decisions. The evidence contains 139,280 branch records across
partitions, representing 138,586 distinct branch specifications.

This raises the original catalog to **34 complete initial-case inventories and
26 passing whole-model audits**. [The rebuilt index](coverage-index.json)
retains all failed original results and subsequent complete-model recoveries.
Tyson (network 5) is the only unfinished initial inventory. Networks 3, 8, 11,
25, 28, 30, 32 and 35 retain complete initial inventories with numerical failures.
Four passing models (6, 14, 17 and 33) have no eligible breaking cases; their
passing untreated controls are not evidence of learning. The 35-model goal
remains incomplete.

## What the computation demonstrates

The model describes TGF-β signalling. Our protocol perturbs its biochemical
state, compares trained and matched control histories, and tests whether a
later intervention changes the measured history effect. These interventions
are computational experiments on the model, not biological observations.
The protocol uses the unchanged three-trial conditional search and the
controls described in [CATALOG_BREAKING.md](../../CATALOG_BREAKING.md).

For each history condition, let `E = mean(rechallenge) - mean(sham)`.
The history effect before a breaker is `H_before = E_history - E_none`;
afterwards it is `H_after = E_history+breaker - E_breaker`. This subtracts a
direct breaker effect shared by trained and untrained controls. Half
restoration requires `|H_after| < 0.5 |H_before|` by more than the propagated
numerical resolution, with a resolved original history effect. The exact
classification order is in [breaking_scores.py](../../grn_memory/breaking_scores.py).

Numerical agreement is distinct from the presence of a history effect:

| Controlled response-by-trial classification | Count |
| --- | ---: |
| No resolved history effect at rechallenge | 178,088 |
| No resolved breaker effect on history | 22,599 |
| History effect changed without half restoration | 25,651 |
| History effect amplified | 22,273 |
| Half-restoration threshold unresolved | 20,692 |
| History effect reduced by half | 20,796 |
| History effect reversed | 6,964 |
| **Total** | **297,063** |

[response-summary.json](response-summary.json) binds these counts to the audit.
About 60% show no resolved history effect. A numerically validated trajectory
can still leave a classification threshold unresolved. Literal MATLAB
direction labels agree between the two engines in this model's response-trials.
The trials reuse species and histories, so these counts are not independent
samples or an estimate of how commonly biochemical networks learn. They
illustrate controlled history dependence in a particular dynamical model;
they do not establish cognition or the broader *Ingressing Minds* thesis.

For a concrete example, the first case in the audit,
`CoSmad_N__down--CoSmad__down`, spans 32 conditional trials and 330
response-trials. Of those, 118 have no resolved history effect, 105 meet the
half-restoration criterion and 63 leave its threshold unresolved. The remaining
44 include amplification, reversal and other changes. Even a single initial
intervention pair therefore has several outcomes across responses and later
conditional interventions; calling the whole case simply “learning” loses
that distinction.

## Evidence and its limits

[audit.json](audit.json) verifies every original case and conditional decision.
[selection-plan.json](selection-plan.json) fixes all sixteen partition indices,
workflow runs, jobs and producer revisions. [status.json](status.json) records
the original ZIP hashes and a verified inventory of every extracted file.
Partitions keep separate branch records even when a specification repeats.
The auditor verifies historical producer code against Git, model and
calibration hashes, full controls, pointwise comparison records and window
summaries, then recomputes the conditional classifications.

The original producers retained comparison results and window summaries,
**not complete raw trajectory arrays**. Reproduction checks this saved
evidence; it does not independently recalculate missing pointwise errors.
No ODE integrations are performed by the reproduction script. Full-array
Radau and Heyoka diagnostics elsewhere remain separate evidence.

The observation spacing remains 0.01, with the original post-reset samples,
full protocol through time 2210 and comparison tolerances of relative 2e-5
and absolute 1e-7. No horizon, case, control, conditional trial or tolerance
was changed to obtain a passing result.

## Reproduce

The [release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-celliere-20261116)
preserves all sixteen original artifact ZIPs, totaling 4,580,129,594 bytes.
Each ZIP is below GitHub's per-asset limit. [release-assets.json](release-assets.json)
records names, sizes and SHA-256 hashes. `SHA256SUMS` also covers the audit,
provenance, reproducer and verification record distributed with the release.

Use a full clone with the historical producer commits available. From the
repository's `python` directory at this release tag:

```sh
uv sync --locked --extra test --extra delay
gh release download kinetics-celliere-20261116 --repo m9h/GRN_ODE --dir /tmp/celliere-assets
uv run --locked python results/catalog-breaking-celliere29-20261116/reproduce.py \
  --assets /tmp/celliere-assets --output /tmp/celliere-reproduced
```

The output directory must be new. The script verifies and freshly extracts
all sixteen ZIPs, rechecks every extracted file, and reruns the whole-model
audit. Its result must equal the saved audit exactly, allowing only different
extraction-directory paths. [reproduction-verification.json](reproduction-verification.json)
records the successful fresh-extraction check.

## Continuing work

The local numerical workers and coordinator remain stopped at the user's
request. Cloud continuations preserve the original scope and checkpoints:
Tyson partitions [14](https://github.com/m9h/GRN_ODE/actions/runs/43907657248)
and [15](https://github.com/m9h/GRN_ODE/actions/runs/43907660865), and the
separate François Linux partitions
[14](https://github.com/m9h/GRN_ODE/actions/runs/43907665080) and
[15](https://github.com/m9h/GRN_ODE/actions/runs/43907668110).
The new fixed sixteen-partition plans are saved alongside this report;
dispatching a continuation is not a completion claim.

The separate Vilar precision work continues
[partition 6](https://github.com/m9h/GRN_ODE/actions/runs/43907356005) and
[partitions 8, 9, 11 and 16](https://github.com/m9h/GRN_ODE/actions/runs/43907358618)
with verified checkpoints. Its remaining native solver disagreements do not
change the paired-screen result of 4,205/4,208 validated cases.
