# Rohwer diagnostic checkpoint generation 3

This selection continues the original 750 first-stage diagnostic branches in
all 32 partitions. Its parent is run [45335934693](https://github.com/m9h/GRN_ODE/actions/runs/45335934693),
produced at `607bac71ae98f78472457ed1d1c7a6a597f4b4a1`.

The parent audit verified 2,027 full trajectories and 477 terminal diagnostics:
384 agreements, 34 numerical mismatches, and 59 recorded integration failures.
Every completed trajectory and terminal outcome must be preserved exactly.
Generation 3 attempts the 193 unstarted branches and resumes 80 interrupted
branches. Numerical code, requests, grids, acceptance thresholds, and dependency
locks are unchanged. The workflow passes this binding explicitly; the runner's
generation-2 defaults remain available for historical reproduction.

`binding.json` pins the full job selection, original artifact metadata, and
per-file parent hashes. Its SHA-256 is
`700ff6ac98c8caf12111527e508b6cc8a0f803a2068f2eaa3cf22c714960bb76`.
The parent collection SHA-256 is
`cd7ddfd789c03e37daaba54875485605bba4b2d50e6ff80f20f2c642135436b1`.

From `python/`, validate the selection without numerical integration:

```sh
uv run --locked --extra test --extra jaxkineticmodel python scripts/continue_rohwer_checkpoint.py check \
  --bindings results/catalog-breaking-rohwer-checkpoint-continuation-20261125 \
  --binding-sha 700ff6ac98c8caf12111527e508b6cc8a0f803a2068f2eaa3cf22c714960bb76
```

Use these same two binding arguments for restore, compute, audit, and collection.
First-stage diagnostics do not establish a whole-model memory result: the
10,924 later-control branches and the full 123-case replay remain required.
