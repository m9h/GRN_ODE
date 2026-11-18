# Validate the collector without changing live experiments

The terminal collector's first ordinary CI run failed because the two full-suite
jobs used shallow Git checkouts. Provenance tests require historical producer
objects. The native job also omitted the locked test extra when running pytest,
and a source-verification test required the optional JAX backend without
declaring that requirement.

The repaired jobs fetch full history, retain the test extra, and include pinned
mpmath in that extra. JAX-specific array-auditor tests run in the JAX job; the
native configuration explicitly skips them. Captured delay-compiler diagnostics
are decoded as UTF-8. Numerical source files, auditors, evidence, models and
acceptance settings are unchanged from `f71fc05a9a355dcfa992b29a21dfc15f4e140222`.
Live collector processes continue to use their original checkout and environment.

Both full test configurations pass locally using unchanged, separate existing
environments through `uv run --no-project`:

- Native: **311 passed, 11 skipped**.
- JAX: **330 passed, 3 skipped**.
- Workflow syntax passes `actionlint`.

An explicit dispatch can run the two affected full-suite jobs and their
five-model replication checks:

```sh
gh workflow run python-replication.yml --repo m9h/GRN_ODE \
  --ref kinetics-collector-ci-repair -f validation_scope=tests
```

This mode does not dispatch the separate catalog calculations. Normal pushes,
pull requests and the default `validation_scope=full` retain the full validation
workflow. Explicit breaking-model dispatches retain their original scope and
independent concurrency groups. Test-only CI success is not a claim that the
35-model scientific computation has finished.
