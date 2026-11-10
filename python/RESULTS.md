# Selected experiments: results and interpretation

Run `python -m grn_memory.suite` from this directory to regenerate these results.
The exact inputs, simulator versions, tolerances and numerical summaries are
recorded in [results/report.json](results/report.json).

| Example | Result | Interpretation |
|---|---|---|
| [No memory](results/no_memory.png), model 31 | Retained fraction 0.173 | Down-regulating `Mp` affects `Mpp`, but fails the 50% retention criterion. |
| [Retained response](results/retained_response.png), model 31 | Retained fraction 1.811 | Up-regulating `Mpp` leaves `Mp` elevated over the test window. |
| [Associative recall](results/associative_recall.png), model 26 | Pretest, association and long-recall criteria pass | Paired training makes the neutral cue effective; its probe trajectory differs from the matched sham. |
| [Drift control](results/drift_control.png), model 26 | Paper-style association passes; sham test fails | Continuing dynamics produce almost the same response without the cue. |
| [Transfer](results/transfer.png), model 26 | Transfer criterion passes | UCS-only training is sufficient; pairing is not required by the test. |
| [Habituation](results/habituation.png), model 10 | Mean pulse response declines 23.84 → 3.26 | Reproduces the declining response shape; untreated dynamics and local baselines matter. |
| [Sensitization](results/sensitization.png), model 27 | Mean pulse response rises 3,257 → 57,622 | Reproduces accumulation; increasing pulse duration and injected material are confounds for sensitivity. |
| [Breaking habituation](results/breaking_habituation.png), model 29 | Rechallenge shift +1.975 with intervention, −1.481 with sham | A second input reverses the sign of the observed response relative to the preceding rest. |

Concentrations above are in each SBML model's native concentration units. The
breaking intervention uses the same model and species roles as Figure 9, with a
fully specified sequence after six pulses and a matched sham intervention. It
is a controlled reproduction of the intended effect, not a point-for-point copy
of the figure's selected time windows.

For associative recall, the response is `Mp_MAPKK`; UCS is `M_MKP3` up and the
candidate CS is `M` down. The mean response during the recall probe is approximately
0.0001103 after paired training, versus 0.0001824 in the paired/sham continuation.
During the following relaxation it remains approximately 0.00007034. The same
cue is neutral under the initial twofold pretest. UCS-only training narrowly
misses the 1.5-fold recall threshold: this particular classification is therefore
threshold-dependent, not evidence that UCS-only training has literally no effect.

The drift example corresponds to another saved associative row in `ODE_New.mat`.
Its probe means are 63.197487 with the cue and 63.197501 without it. A label based
only on change since the wash window misses this distinction. This is why the
notebook includes the sham continuation alongside the original operational test.

The retained-response example remains different from its untreated control after
an additional 500 time units (late means about 127.82 versus 24.98). That still
does not prove indefinite memory, nor bistable switching at a fixed molecular
total: the input changes conserved pools.

## Validation

- **26 tests pass**, including analytic decay in a two-litre compartment,
  exact reset timing, failure sentinels, saved MATLAB initial states, and the
  positive/negative memory examples.
- **44 complete trajectory comparisons pass** across all eight experiments.
  Every species and output time is compared, including the intervention species.
  Each engine independently simulates and calibrates its own untreated baseline.
- All reported Boolean classifications agree between engines. Solver tolerances
  are relative `1e-9`, absolute `1e-11`. Cross-engine acceptance is
  `|a-b| <= 1e-7 + 2e-5 * max(|a|, |b|)`. The largest normalized error is about
  **0.112**, where 1 would be the failure boundary. The largest absolute error,
  about 0.00472, occurs in the large accumulating-response experiment.
- Versions: libRoadRunner 2.11.0, COPASI 4.48.311 through BasiCO 0.92,
  libSBML 5.21.2. `uv.lock` captures the environment.

This validates the selected implementation numerically. It does not reproduce
all 35 biological networks, random-network distributions, perturbation robustness,
serial/parallel memory counts, or the original population-level statistics.
No positive consolidation example is claimed. The [guide](README.md) describes
the deliberate corrections and remaining differences from the MATLAB scripts.
