# Testing current code against historical evidence

The original simulations, their source hashes and their saved trajectories are
immutable evidence. Improving an adapter does not make older evidence invalid,
but auditing that evidence requires identifying the source that actually matches
its recorded hashes. Comparing every old report with today's adapter incorrectly
rejects valid archives as soon as the adapter changes.

The Marhl Taylor archive now has a separate `source-provenance.json` file. It
identifies publication revision `4a43d8d3ed3ad777aab173eaa672306691ce9d6d`, whose
four implementation files exactly match the hashes already present in the
original report. This identifies matching source bytes; it does not establish
the runtime's original Git HEAD. The report and trajectory files are unchanged.

`audit_taylor_paired.py` verifies every historical implementation file against
that Git object, then reads every saved sample and recomputes the comparisons.
The reset and comparison helpers must also match the current reader. Missing
Git history, mismatched hashes, changed source inventories, conflicting explicit
revisions and changed interpretation helpers are rejected. Without a provenance
file, an explicit full `--source-revision` is required when current sources differ.

The mpmath audit preserves its original `reference-audit.json` and checks its
recorded checksum. It recognizes only the current auditor or the auditor whose
bytes are verified in the historical revision. Every scientific result in the
saved reference audit must reproduce; only auditor identity and additional
source-verification metadata can differ. Tests alter these fields and rebuild
their checksums to ensure a consistent-looking record cannot bypass the audit.

## Run the two test configurations with uv

From `python/`, use a full Git checkout. The two full-suite CI jobs use
`actions/checkout` with `fetch-depth: 0` because some tests reconstruct original
case plans from historical producer code.

Native dependencies and the test tools:

```sh
uv sync --locked --extra test
uv run --locked --extra test python -m pytest -q
```

The optional JAX backend, with a separate environment if the native environment
is in use:

```sh
UV_PROJECT_ENVIRONMENT=.venv-jax uv sync --locked --extra test --extra jaxkineticmodel
UV_PROJECT_ENVIRONMENT=.venv-jax uv run --locked --extra test --extra jaxkineticmodel python -m pytest -q
```

The SciPy/JAX breaking-array audit verifies source files from the installed
Jaxkineticmodel package. Its tests require that optional package and run in the
second configuration. The native-only configuration skips them explicitly.
The lightweight mpmath dependency is included in the locked test extra.

Delay-engine checks additionally require `--extra delay`:

```sh
uv run --locked --extra test --extra delay python -m pytest -q tests/test_native_kinetics.py tests/test_delay_kinetics.py
```

The delay test decodes captured compiler diagnostics as UTF-8 with replacement
for malformed bytes. Native libraries can change the process locale; decoding
their diagnostic text should not fail an otherwise successful numerical test.
The child process return code and analytic trajectory comparison still must pass.

## Re-audit the archived Marhl trajectories

These commands perform no integrations and write new audit reports:

```sh
uv run --locked --extra test python scripts/audit_taylor_paired.py \
  --input results/catalog-paired-taylor-marhl \
  --output results/re-audit-marhl/taylor.json
uv run --locked --extra test python scripts/audit_marhl_mpmath.py \
  --input results/catalog-paired-mpmath-marhl \
  --output results/re-audit-marhl/mpmath.json
```

Both retain the distinction between high-precision agreement and agreement with
the native solver. Neither branch-level audit, on its own, establishes complete
memory-case recovery or whole-catalog validation.
