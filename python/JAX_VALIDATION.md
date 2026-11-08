# Validating the Jaxkineticmodel migration

The optional backend uses the [modernized Jaxkineticmodel fork](https://github.com/m9h/jaxkineticmodel/tree/modern-jax-validation)
on JAX/JAXlib 0.12.0.1, Diffrax 0.7.2 and Equinox 0.13.8. Its source is pinned to
commit `2a5b4c255d2d250cdcd36d5abc2f7f992d3a24e6`. JAX dependencies are installed
through the `jaxkineticmodel` optional extra, with exact versions recorded in
the shared lockfile. The ordinary RoadRunner/COPASI workflow does not import JAX.

From this directory, with Python 3.12:

```sh
uv sync --locked --extra test --extra jaxkineticmodel
uv run --locked --extra test --extra jaxkineticmodel python -m pytest -q
MPLBACKEND=Agg JAX_PLATFORMS=cpu uv run --locked --extra jaxkineticmodel python -m grn_memory.suite --engine all --output results/jaxkineticmodel --no-traces
```

The adapter runs the existing experiment functions and reset schedules. It
converts the backend's species-symbol units to concentrations at its boundary,
retains fixed enzyme values, and reinitializes all dynamic species at resets.
Model checks restrict it to the same autonomous fixed-compartment reaction
models as the reference adapters. This does not implement SBML events.

## Results

[results/jaxkineticmodel/report.json](results/jaxkineticmodel/report.json) records
**44 full Jaxkineticmodel-versus-RoadRunner trajectory comparisons**, plus the
44 RoadRunner-versus-COPASI reference comparisons. All 88 pass. All reported
Boolean classifications agree across the three engines. The unchanged analytic
reset tests also pass for the JAX adapter; the local suite has **28 passing tests**.

Each comparison includes every species and time sample, not just the final
response. Each engine calibrates its own baseline and intervention levels.
Solver tolerances are `rtol=1e-9, atol=1e-11`; comparison acceptance is
`abs(a-b) <= 1e-7 + 2e-5 * max(abs(a), abs(b))`. The table shows the largest
tolerance-normalized error among the JAX/reference traces; values <= 1 pass.

| Experiment | Traces | Largest normalized error |
|---|---:|---:|
| No memory | 3 | 0.0133 |
| Retained response | 3 | 0.0223 |
| Associative recall | 9 | 0.0232 |
| Drift control | 9 | 0.0248 |
| Transfer | 9 | 0.00576 |
| Habituation | 3 | 0.1091 |
| Sensitization | 3 | 0.0149 |
| Breaking habituation | 5 | 0.0792 |

The [scientific interpretations and confounds](RESULTS.md) still apply. In
particular, accumulating material and continuing dynamics do not by themselves
establish learning. No broader SBML coverage, GPU speedup, full 35-network
replication or RNM transition-graph reconstruction is claimed.

## Why the dependency update includes loader fixes

The original Jaxkineticmodel package pinned JAX 0.4.35. After updating the stack,
our unchanged test cases exposed missing constant enzymes and incorrect
amount/concentration scaling in its existing SBML importer. The fork corrects
those issues, preserves units through SBML export/reimport, allows repeated
construction from the same symbolic model, and rejects unsupported rate rules
explicitly. The source XML files remain unchanged.

The fork's [validation guide](https://github.com/m9h/jaxkineticmodel/blob/modern-jax-validation/validation/README.md)
provides six analytic cases at two output grids, five biological baselines,
independent simulator comparisons, gradient checks and Optax tests. Its MAPK
example transfers material within a conserved pool, batches candidate pulse
fractions, and recovers a synthetic target fraction of 0.35 as approximately
0.34996. Gradients are checked against centered differences from both independent
simulators. It demonstrates differentiable intervention fitting, separately from
the threshold-based memory classifications here.
