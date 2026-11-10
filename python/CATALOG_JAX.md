# Jaxkineticmodel coverage of the 35-model catalog

The pinned Jaxkineticmodel fork validates **32 of the 35 original baselines**
against both RoadRunner and COPASI. The other three are explicit unsupported
imports, not validated simulations. All 35 remain covered by the separate
[reference kinetics workflow](CATALOG_VALIDATION.md), including its delay solver.

This audit runs the unmodified SBML from its native initial conditions for
50 native time units, at 5,001 output times. It compares every original species
and additional rule/event target, not just independent ODE states. Assignment
rules are reconstructed from the evolving state; species amounts are converted
to concentrations only at the comparison boundary. A derived species remains
an observable without becoming an independently evolving state. The
[report](results/catalog-jax/report.json) records model and source hashes,
versions, settings and the largest discrepancies for every observable.
There are **96 passing pairwise comparisons** across 352 model observables;
the largest tolerance-normalized discrepancy is approximately **0.0194**,
against an acceptance limit of one.

## Explicit coverage gaps

| Network | BioModel | Semantics absent from this JAX backend |
|---|---|---|
| 1 | BIOMD0000000001, Edelstein ACh-event model | Event trigger and assignment execution |
| 6 | BIOMD0000000006, Tyson two-variable cell cycle | Rate-rule states |
| 14 | BIOMD0000000024, Scheper clock | Delayed state and retained history |

An earlier constructor-only audit accepted the event and delay models despite
not implementing their semantics. The converter turned `delay(x, tau)` into
`x - tau`, a different equation. The updated importer rejects both unsupported
features. Removing the event or replacing the delay with an ordinary ODE would
not validate these models.

## Corrections and numerical settings

The dependency is pinned to
[`0c16f6e`](https://github.com/m9h/jaxkineticmodel/commit/0c16f6ea145862ea0a3d9b1ef4368745e18028a5).
Besides explicit feature rejection, it preserves fractional stoichiometry,
sums repeated species references, excludes assigned species from the independent
state, resolves rule dependencies and function calls, and preserves assignments
through export/reimport. Its 43 tests include analytic solutions, both reference
simulators, JIT/vmap, gradients and training.

JAX uses CPU float64. The ordinary catalog setting is Kvaerno5 with
`rtol=1e-10`, `atol=1e-12` and initial step `1e-4`. RoadRunner and COPASI use
`rtol=1e-12`, `atol=1e-14`. Acceptance is unchanged for every model:

```text
abs(a - b) <= 1e-7 + 2e-5 * max(abs(a), abs(b))
```

Two explicit JAX solver exceptions are recorded:

- **Network 29, Cellière TGF-β signaling:** Tsit5 with the ordinary tolerances.
  Kvaerno5 rejected every attempted initial step in a diagnostic run; Tsit5
  completes the original equations and agrees with both reference engines.
- **Network 35, Rohwer phosphotransferase system:** Kvaerno5 with
  `rtol=1e-7`, `atol=1e-9`. Tighter requests exhausted the step budget.
  Both this setting and a looser `1e-6`/`1e-8` diagnostic agree with the tight
  reference trajectories under the same acceptance criterion. This verifies
  the stated output grid, not arbitrary sub-grid transients or interventions.

These are integration settings, not changes to acceptance or biological XML.
A baseline match does not establish correct gradients for every model, complete
SBML conformance, or memory-protocol validation across all 32. The separate
[three-engine memory suite](JAX_VALIDATION.md) retains the eight demonstrations
on its five selected models.

## Reproduce

From `python/`:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
MPLBACKEND=Agg JAX_PLATFORMS=cpu uv run --locked --extra test --extra jaxkineticmodel python -m pytest -q
MPLBACKEND=Agg JAX_PLATFORMS=cpu uv run --locked --extra jaxkineticmodel python -m grn_memory.catalog_jax --workers 2 --expect-unsupported 1 --expect-unsupported 6 --expect-unsupported 14
```

The coverage gate requires exactly these three unsupported networks and passing
comparisons for every other selected model. A rejection does not count as a
validated baseline; `all_models_validated` remains false. Without explicit
expected exclusions, the command exits nonzero while writing the complete report.
Unexpected exclusions and numerical failures always fail. Use a fresh `--output`
directory for CI; `--resume` requires matching provenance.
