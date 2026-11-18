# Complete Marhl breaking recovery scope

The twelve failed Marhl breaking cases require **380 distinct trajectories**
when every potential later trial and the full untreated control are included.
This inventory preserves their original schedules, amplitudes, sample times,
five observable columns and acceptance thresholds. It performs no integration
and claims no recovered case.

This is network 30, BioModel 39. The earlier paired-learning experiment runs
to time 300; its completed high-precision recovery cannot validate breaking
trajectories that run to 1410, 1810 or 2210. The original Linux breaking audit
passes 26 of 38 cases. The separate macOS result passes 27; this selection
retains all twelve Linux failures, including `CaM__up--CaPr__up`, which passed
on macOS.

## Why the missing controls matter

The source protocol decides whether to continue after each trial. Changing a
numerically uncertain trajectory can change that decision. Validating only the
branches reached by the original search could therefore leave a new later trial
without its required controls. Each potential trial needs the history/no-history,
breaker/no-breaker and cue/sham combinations: eight arms, with shared identical
specifications computed once. Later sham arms retain the earlier rechallenges.

The new inventory reconstructs all six potential trials for seven selected
cases and all eight for the other five. It includes 292 specifications already
observed somewhere in the original four partitions, represented by 346 separate
records, and **88 potential specifications absent from every original partition**.
Those generated controls have no fabricated original outcome or window summary.

| Original failed case | Potential controls missing from its original partition |
|---|---:|
| `CaER__down--CaM__down` | 20 |
| `CaER__up--CaM__down` | 20 |
| `CaM__down--Pr__down` | 20 |
| `CaM__up--Ca_cyt__down` | 8 |
| `Ca_cyt__up--CaM__down` | 20 |
| Other seven selected cases | 0 |

| Full horizon | Samples per trajectory | Required trajectories |
|---|---:|---:|
| 1410 | 141,001 | 59 |
| 1810 | 181,001 | 68 |
| 2210 | 221,001 | 253 |
| Total | | 380 |

The last group includes the untreated 0–2210 control. All five original
observables are retained in SBML order: `Ca_cyt`, `CaER`, `CaM`, `CaPr`, `Pr`.
The 0.01 grid retains the original post-reset offsets of 1e-5. Original
integration settings remain in each specification to preserve branch identity;
this inventory does not declare new solver requests.

## Relationship to the published diagnostics

The [completed Radau/RoadRunner diagnostic](../catalog-breaking-marhl30-radau-20261114/README.md)
preserves all 120 arrays for 30 original failed records, representing 29 distinct
specifications. The shared failed control in partitions 0 and 3 remains two
separate original records. Three records, or two distinct specifications, pass
all six comparisons. Twenty-seven records retain numerical disagreements.

All 29 diagnostic specifications are included here, together with 351 other
required specifications. Passing diagnostics alone cannot establish recovery
of a complete case. The original 26 passing cases are outside this selected
recovery scope; this inventory is not a whole-model recovery audit.

The next useful numerical experiment is to apply the two independent
high-precision implementations already used in the paired study—Heyoka and
the model-specific mpmath transcription—to these full breaking horizons.
Checking all 29 failed specifications plus the untreated baseline would test
30 distinct trajectories. Both precisions and both implementations would be
required; agreement between two precisions of one implementation alone would
not resolve disagreement with independent solvers. The existing native arrays
must remain available for comparison. The other 350 controls would still be
needed before replaying all twelve complete conditional searches.

That precision producer, its full-array auditor and cloud execution are **not
implemented or dispatched by this change**. The 380-specification inventory
provides their complete scope. Numerical failures must remain explicit without
shortening horizons, clipping resets or relaxing the `2e-5/1e-7` comparison rule.

## Reproduce the inventory

All source inputs are already tracked in Git at
`079e35d8bc0795f427b6cb5b8514f35830f01909`; no new data release is needed.
The [adapter](../../scripts/prepare_marhl_full_controls.py) checks those exact
file hashes, re-audits all 783 original branch records and all 38 cases, and
reconstructs the complete potential scope. It independently checks the published
diagnostic selection against the original archives. Each selected original
record retains its partition and fingerprint; missing controls are identified
separately. No original evidence is overwritten.

From this branch's `python/` directory, in an isolated checkout:

```bash
uv sync --locked --extra test
uv run --locked --extra test python scripts/prepare_marhl_full_controls.py check \
  --inventory results/catalog-breaking-marhl-full-controls-20261118/inventory.json
```

To write a fresh independent inventory, use `capture --inventory NEW_FILE.json`
instead. Existing paths are rejected. The checked inventory SHA-256 is
`a17f4c58c46e11aa890521874dd2dfb821f40dfacc3446bf0ba695e20afeaa42`.

The check validates original reports, archived comparisons and window summaries;
it does not reread the 120 diagnostic trajectory arrays. Their prior independent
array audits and release remain linked above. Neither a successful scope check
nor passing software tests changes the original 26/38 numerical result.

[Local verification](verification.json) records 25 new scope tests and 66
combined targeted tests passing. All 66 also pass with imports of the optional
JAX and arbitrary-precision libraries blocked. The workflow definition passes
actionlint; its separate Linux validation remains pending.
