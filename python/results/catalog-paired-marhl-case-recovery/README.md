# Complete Marhl paired-case recovery

The full-array audit validates both formerly unresolved paired cases in
`BIOMD0000000039`, the Marhl calcium-oscillation model. Marhl now has **26/26
validated paired cases**: 24 original passes plus two separately recovered
cases. No original passing case is contradicted by a newly checked shared arm.
Across the catalog, the separate recoveries bring paired validation to
**4,205/4,208 cases in 34 fully passing models**. Three Vilar cases remain.
This result does not complete Marhl's separate breaking-memory screen.

## Evidence and numerical scope

Each case uses twelve arms: untreated, UCS-only, CS-only and paired training,
each followed by sham, ordinary-cue and delayed-cue protocols. The two cases
share some arms, so their union contains 18 distinct trajectories. All retain
the original resets and all 30,001 observations over time 0–300.

Every arm was computed using Heyoka and an independent, model-specific mpmath
implementation at both 128- and 192-bit precision, plus RoadRunner. The audit
recomputes all ten pairwise comparisons per arm from the full arrays, checks
source/model hashes and reset coverage, and reconstructs the case scores from
the same two 192-bit implementations across all twelve arms. The acceptance
rule remains `rtol=2e-5`, `atol=1e-7`. Integration tolerances are `1e-30` at
128 bits and `1e-45` at 192 bits; mpmath uses Taylor degrees 32 and 48.

All 18 arms pass the six comparisons among the four high-precision runs.
Fifteen also agree with RoadRunner at `rtol=1e-13`, `atol=1e-15`. The three
originally failed arms retain their RoadRunner disagreement. The untreated
baseline passes, and controlled classifications agree for both recovered cases.
Literal paper-style labels are retained separately and also agree here.

Both independent implementations use Taylor methods. This is evidence from
independent implementations and precision refinement, not agreement across
different integrator families or a proof of the exact solution. The original
native-solver failures remain part of the record.

## What the cases demonstrate

| Training inputs | Response | Controlled ordinary and delayed cue result |
|---|---|---|
| `CaM` up, `CaER` down | `Pr` | Joint-exposure candidate; retains at least half of the measured cue increment after withdrawal |
| `Ca_cyt` up, `CaER` down | `CaM` | Cue response without joint specificity; below half retention |
| `Ca_cyt` up, `CaER` down | `Pr` | Cue response without joint specificity; at least half retention |

For a response variable, let `E(h)` be the cue-window mean minus the matched
sham-window mean after history `h`. The factorial interaction is

$$I=E(\mathrm{paired})-E(\mathrm{UCS})-E(\mathrm{CS})+E(\mathrm{none}).$$

It measures the contribution beyond the sum of separate training histories.
The joint-exposure classification additionally requires the paired response
to exceed each simpler history by a resolved amount. A positive interaction
alone is insufficient: the second case has positive ordinary-cue interactions,
yet its paired responses do not exceed every simpler-history control.
Numerical validation means that the simulated trajectories and these operational
classifications reproduce; it does not mean that every tested pair exhibits
associative learning or establish a biological learning mechanism.

## Reproduce the audit

The [evidence release](https://github.com/m9h/GRN_ODE/releases/tag/kinetics-marhl-paired-recovery-20261114)
contains all four evidence directories: the 15 new controls, the earlier Heyoka
and mpmath diagnostics, and this complete-case report. Its manifest records
archive and member sizes and SHA-256 checksums. Extract into a separate
directory, then run from this revision's `python/` directory:

```bash
uv run --locked python scripts/audit_marhl_cases.py \
  --controls /path/to/evidence/catalog-paired-marhl-controls \
  --mpmath /path/to/evidence/catalog-paired-mpmath-marhl \
  --reference /path/to/evidence/catalog-paired-taylor-marhl \
  --output /tmp/marhl-case-audit.json
```

Expected: 18 high-precision-agreeing branches, two recovered cases, 26 combined
passes and no original cases requiring revalidation. This audit performs no new
integration and does not require Heyoka to be installed. The original case
inventory and branch archives are retained in the repository. See
[`PRECISION_DIAGNOSTICS.md`](../../PRECISION_DIAGNOSTICS.md) for the integration
commands and the validation of the independent model equations.
