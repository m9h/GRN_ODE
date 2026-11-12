# Intervening on acquired response histories

This stage extends the original MATLAB breaking-intervention search across the
35-model catalog. The selected-case [final pilot](results/catalog-breaking-pilot-final/report.json)
passes **119 branches across 24 conditional trials**, covering three initial
cases in networks 3, 26 and 35. Its largest normalized discrepancy is 0.58169
(acceptance limit 1), with one explicitly recorded solver retry. The pilot
revision passed 74 local tests. The full-catalog search is running; **full-catalog breaking results
are not yet available.** The [validated repeated-stimulation screen](CATALOG_REPEATED.md)
provides the initial histories, stimulus levels and candidate responses.

The initial inventory contains **7,324 ordered UCS/breaker combinations and
37,086 response assessments**. Later trial counts depend on earlier results.
Networks 6, 14, 17 and 33 have no eligible initial combinations under the
specified rule; they still receive independently compared untreated controls.
Zero eligible combinations do not establish an absence of learning capacity.

## Audited completed models from the original run

The [original-run snapshot](results/catalog-breaking-original-completed/audit.json)
contains **17 terminal model reports** from source revision
`70a3afad61357e94873ff62a7300c099b4c7ae3e`, copied on 11 November 2026 while
the other workers continued. Fourteen models pass their numerical checks.
Across these reports, **845 of 852 initial cases pass**, with 6,946 conditional
trials and 28,127 distinct branches within their respective models. There are
four incomplete integrations and 22 completed trajectory mismatches.

| Network | Model | Passing / initial cases | Branches | Result |
|---|---|---:|---:|---|
| 3 | Goldbeter 1991, reduced mitotic oscillator | 6 / 8 | 41 | Four incomplete branches leave two conditional decisions unresolved. |
| 4 | Goldbeter 1991, explicit inactive pools | 51 / 54 | 1,327 | Eight original mismatches; the separate full recovery below passes 54/54. |
| 6 | Tyson 1991, two-variable cell cycle | 0 / 0 | 1 | No eligible cases; untreated control passes. |
| 7 | Kholodenko 2000, oscillatory MAPK cascade | 220 / 220 | 11,742 | Passes. |
| 9 | Goldbeter 1995, circadian clock | 66 / 66 | 1,657 | Passes. |
| 13 | Rohwer 2001, sucrose metabolism | 78 / 78 | 2,304 | Passes. |
| 14 | Scheper 1999, delayed circadian clock | 0 / 0 | 1 | No eligible cases; untreated control and delay refinements pass. |
| 16 | Markevich 2004, ordered MAPK phosphorylation | 8 / 8 | 85 | Passes. |
| 17 | Cao 2008, toggle switch | 0 / 0 | 1 | No eligible cases; untreated control passes. |
| 18 | Markevich 2004, random MAPK phosphorylation | 40 / 40 | 703 | Passes. |
| 19 | Markevich 2004, ordered MAPK with two kinases | 14 / 14 | 137 | Passes. |
| 21 | Chickarmane 2006, reversible stem-cell switch | 24 / 24 | 542 | Passes. |
| 22 | Chickarmane 2006, irreversible stem-cell switch | 30 / 30 | 675 | Passes. |
| 23 | Chickarmane 2008, stem-cell lineage determination | 32 / 32 | 237 | Passes. |
| 24 | Chickarmane 2008, NANOG–GATA-6 switch | 138 / 138 | 6,010 | Passes. |
| 26 | Muller 2008, simplified MAPK activation | 116 / 118 | 2,404 | Fourteen completed mismatches; refinement evidence and run comparison below. |
| 27 | Goldbeter 2007, somitogenesis switch | 22 / 22 | 260 | Passes; independent distributed result below also passes. |

The [full-model auditor](scripts/audit_breaking_catalog.py) uses the same branch
and conditional-search checks as the partition audit. It verifies every
declared producer source file against Git, verifies model and calibration
hashes, recomputes all scores, and requires all initial candidates. It reports
initial-case coverage, conditional-search coverage and numerical validation
separately. In particular, attempting all eight initial cases in network 3 does
not settle the continuation choices after its failed integrations. Its
biological domain limitation is discussed below; its failures are preserved.
Network 4's original results are likewise retained independently of recovery.

```bash
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_catalog.py \
  --input results/catalog-breaking-original-completed \
  --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --network 3 --network 4 --network 6 --network 7 --network 9 --network 13 --network 14 \
  --network 16 --network 17 --network 18 --network 19 --network 21 \
  --network 22 --network 23 --network 24 --network 26 --network 27 \
  --output results/catalog-breaking-original-completed/audit.json
```

Without `--network`, the auditor requires all 35 models. A selected passing
subset cannot establish catalog completion. The producer revision must be in
local Git history, and this command checks saved evidence rather than rerunning
integrations. Nine further tests exercise complete and failed models, the
delay-model control, partial and running reports, missing controls, changed
producer sources, and the distinction between selected and catalog coverage.

## Restartable computation in complete-case partitions

The [shard runner](scripts/run_breaking_shard.py) divides the sorted initial-case
inventory into disjoint contiguous ranges. It invokes the existing worker for
each range: every selected case keeps its full conditional second/third-trial
search, all eight control arms, every original observation and the original
comparison thresholds. Tests verify that all **7,324 initial cases** appear
exactly once for partition counts 1, 4, 7, 8 and 16.

For example, the first of four partitions of network 19 contains three of its
14 cases. All three pass and match their entries in the locally completed
full-model report. Resuming reuses 36 unchanged atomic checkpoints without new
integration. An intentionally timed-out worker cannot promote a stale report;
a subsequent resume again reuses those checkpoints.

```bash
MPLBACKEND=Agg uv run --locked --extra delay python scripts/run_breaking_shard.py \
  --network 19 --shard-index 0 --shard-count 4 --timeout 18000 \
  --resume --output results/breaking-network-19-shard-0
```

Keep the entire output directory, including **`.evidence/`**, when resuming.
The runner uses a process lock to prevent concurrent writes to the same output.
It records the case selection and its hash, source revision, subprocess outcome,
and whether only the selected range or the entire model has passed. For a model
with no candidates, partition zero still validates its untreated trajectory;
the other empty partitions do not claim model validation.

The existing GitHub workflow also accepts `breaking_networks`, a JSON array of
catalog network numbers, and `breaking_shard_count`, a choice of 4, 8 or 16
partitions per model (default 4). It runs at most sixteen jobs concurrently,
subject to available GitHub runners, and gives each worker five hours
before preserving its checkpoints. Ordinary validation jobs are skipped for
this explicit computation dispatch. Artifact uploads include hidden checkpoints
and retain them for seven days, so download them before expiration.

```bash
gh workflow run 410775433 --repo m9h/GRN_ODE --ref kinetics-newton-reference \
  -f breaking_networks='[26,27,28,29,30,31,32,33,34,35]'
```

To continue an unfinished batch, repeat the dispatch with the same networks and
`-f breaking_resume_run=PREVIOUS_RUN_ID`. Set `breaking_resume_shard_count` to
the previous run's partition count (default 4). The new count must be the same
or an integer multiple of that count. The workflow restores the corresponding
parent artifact, validates its checkpoints, and runs the new selection with
`--resume`. For example, a stopped four-partition run can continue as eight
smaller partitions:

```bash
gh workflow run 410775433 --repo m9h/GRN_ODE --ref kinetics-newton-reference \
  -f breaking_networks='[28,29]' -f breaking_shard_count=8 \
  -f breaking_resume_run=PREVIOUS_RUN_ID -f breaking_resume_shard_count=4
```

The [checkpoint preparation tool](scripts/prepare_breaking_resume.py) requires
a stopped source partition and an unused destination. It checks the model,
calibration, complete case inventory, worker source hashes, installed package
versions, checkpoint identities, full observation horizons and control histories
before copying any evidence. It rejects an active source lock. Passing cached
records can then be reused; failed records may be recomputed by the worker.
The original artifact remains intact, including its failed observations.

For a local preparation followed by a resume:

```bash
uv run --locked --extra delay python scripts/prepare_breaking_resume.py \
  --source results/previous-network-27-shard-0 --network 27 \
  --shard-index 0 --shard-count 8 --output results/new-network-27-shard-0
MPLBACKEND=Agg uv run --locked --extra delay python scripts/run_breaking_shard.py \
  --network 27 --shard-index 0 --shard-count 8 --timeout 18000 \
  --resume --output results/new-network-27-shard-0
```

`resume-source.json` records the parent revision and manifest digest, the new
selection, and the digest of every copied checkpoint. Preparation performs no
integration and makes no model-completion claim.

A [complete local resume check](results/catalog-breaking-repartition-27/verification.json)
split all four original network-27 partitions into eight children. Every copied
checkpoint remained byte-for-byte unchanged after execution. The
[combined audit](results/catalog-breaking-repartition-27/audit.json) passes all
**22 cases, 57 conditional trials and 72 response-trials**, with every case summary
identical to its original apart from the partition index. The eight workers
reuse all 260 distinct branch specifications without new integration. Their
published archives contain 346 branch records, compared with 301 in the original
four partitions, because shared controls appear in more partitions. These
duplicate records do not represent additional scientific coverage.

The corresponding [eight-partition Linux resume](https://github.com/m9h/GRN_ODE/actions/runs/43168144204)
also completes at revision `a188face8e1b14383cf42c8e9fd148d6b4ee1360`.
Its [combined audit](results/catalog-breaking-repartition-27-linux/audit.json)
passes all 22 cases, 57 conditional trials and 72 response-trials. The
[checkpoint verification](results/catalog-breaking-repartition-27-linux/verification.json)
checks all 646 copied files across the eight children: every inventory and
checksum remains unchanged, and every case summary matches its original
apart from the partition index. This verifies the resume workflow on Linux
as well as locally; it does not add new model coverage.

An additional [sixteen-partition batch for networks 1, 2 and 5](https://github.com/m9h/GRN_ODE/actions/runs/43169085644)
was submitted at revision `1fc563a9db5370b15df8faf419cc12b205a64648`.
Its 48 jobs partition 1,210 initial cases and keep the original observation
horizons, conditional searches and comparison thresholds. Network 1's sixteen
partitions have stopped with 397/528 passing case results; networks 2 and 5
continue in that batch. The next dispatches below retain these independent
outputs separately from the original local calculations.

### Checkpoint continuations dispatched on 12 November

The [dispatch record](results/catalog-breaking-resume-20261112/dispatches.json)
records each parent artifact's checksum and reported progress. These are
partial worker results, not complete-model validation. All six networks now
have sixteen-partition continuations at revision
`e5ff9bb131b3a815feb584793b9f68dda53ce7a7`; no observation times, controls,
conditional branches or acceptance thresholds were removed.

| Network | Initial cases with a recorded result | Passing cases reported | Total initial cases | Continuation |
|---|---:|---:|---:|---|
| 1 | 397 | 397 | 528 | [Same sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273682876) |
| 28 | 228 | 201 | 622 | [Four to sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273574799) |
| 29 | 264 | 264 | 1,088 | [Four to sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273574799) |
| 31 | 232 | 232 | 728 | [Four to sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273680209) |
| 32 | 159 | 84 | 204 | [Four to sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273680209) |
| 35 | 87 | 49 | 260 | [Four to sixteen partitions](https://github.com/m9h/GRN_ODE/actions/runs/43273680209) |

Completed failures remain in the parent artifacts. Resuming can retry a failed
branch; it does not convert a failure into a pass or imply that a missing
conditional continuation has been resolved.

Keep artifacts from different
partitions in separate directories: shared branch identifiers alone do not
justify overwriting independently computed evidence. A successful partition
is not a complete-model result; complete coverage and numerical validation must
be audited across every partition before reporting a model as finished.

### Collecting completed batches

The [collector](scripts/collect_breaking_runs.py) saves artifacts as jobs finish,
including hidden checkpoints needed for later resumes. It verifies the downloaded
ZIP against GitHub's SHA-256, checks the producing revision and job attempt, and
keeps each attempt and artifact in a separate directory. Source Git objects must
be available locally for the subsequent evidence audit.

```bash
MPLBACKEND=Agg uv run --locked --extra delay python scripts/collect_breaking_runs.py \
  --run 43158961987 --run 43168144204 --run 43169085644 \
  --output results/catalog-breaking-collected --watch
```

Omit `--watch` for one collection pass. The watcher polls every 45 seconds and
writes `status.json` plus a `collection.json` for each workflow attempt. Once all
partitions for a model have complete selected-case coverage, it runs the full
combined auditor and saves its report. A completed job alone cannot establish
validation: missing artifacts remain pending, timed-out partitions are listed
under `needs_resume`, and completed numerical mismatches retain their failing
result. Computation and resume dispatches use the explicit commands above.
Cached audits are reused only for unchanged artifact evidence, model,
calibration and auditor source. The original failed observations remain in their
own artifacts throughout collection and subsequent recovery.

### First complete model from the distributed run

Network **27**, [BioModel 275](models/BIOMD0000000275.xml), now passes all
**22 initial cases and 57 conditional trials**, covering 72 response-trials.
The [combined evidence audit](results/catalog-breaking-linux-27/audit.json)
checks four disjoint Linux partitions produced at revision
`2e7327b0d273f4b33bdd8aa37601c1a497854a2a` in
[workflow run 43101294718](https://github.com/m9h/GRN_ODE/actions/runs/43101294718).
The partitions retain 301 validated branch records representing 260 distinct
branch specifications; repeated controls across partitions remain separate.

The [audit](scripts/audit_breaking_shards.py) verifies the model, calibration,
producer source and archive hashes; checks every original observable and full
branch horizon; reconstructs all eight control schedules, including earlier
rechallenge pulses; recomputes controlled and raw scores; and verifies the
complete conditional continuation tree. The partial worker reports retain
their partial-coverage status. The combined audit establishes full coverage
without overwriting their independent evidence.

```bash
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 27 \
  --input results/catalog-breaking-linux-27/shard-0 \
  --input results/catalog-breaking-linux-27/shard-1 \
  --input results/catalog-breaking-linux-27/shard-2 \
  --input results/catalog-breaking-linux-27/shard-3 \
  --output results/catalog-breaking-linux-27/audit.json
```

The producer revision must be available in local Git history. The audit checks
saved pointwise comparison results and recomputes scores from saved window
summaries; it does not rerun numerical integration. Nine focused tests check
all 22 published cases and reject missing third trials, missing controls, wrong
prior probe histories, altered scores, shortened horizons, dropped observables,
false pass flags and changed archives. Missing or duplicate partitions are also
rejected by the complete-model audit. Other model partitions remain in progress.

All 323 hidden atomic checkpoints in the downloaded Linux artifacts match the
published branch and case records. A local resume of the five-case first
partition reused its 50 unchanged checkpoints without new integration. The
public archives below contain the scientific evidence; resuming computation
requires the artifacts' hidden `.evidence` directory as well.

### Complete network 26 coverage with two remaining mismatches

The [network 26 audit](results/catalog-breaking-linux-26/audit.json) checks all
four partitions from the same distributed run. All **118 initial cases and
524 conditional trials** were evaluated; **116 cases pass**. The partitions
retain 2,168 branch records and 795 response-trials, with no unresolved
conditional decisions. The timed-drive encoding and untreated controls are
included in the audit.

Fourteen completed branches in the last partition exceed the comparison
threshold. They affect `MAPK__up--C_Raf_inactive__up` and
`MSH__down--C_Raf_inactive__up`; their controlled classifications agree, but
their full trajectories do not. The largest scaled discrepancy is 2.89774 in
`C_Raf` near time 1912.62. The failed job represents these numerical mismatches,
not a timeout or missing initial cases. The reports retain the original
`1e-12/1e-18` requests on those branches.

The [complete refinement diagnostic](results/catalog-breaking-muller26-refinement/report.json)
now confirms all 14 mismatches. All 84 integrations finish over the original
0–2210 interval, retaining 221,001 observations and all ten observables.
The two tighter requests are `1e-13/1e-19` and `5e-14/5e-20`; both native
cross-engine comparisons and both within-engine refinements pass on every
branch. The original timed-drive encoding and reset schedules are retained.
The separate [full recovery](results/catalog-breaking-muller26-full-recovery/audit.json)
now passes **all 118 cases**, recomputing every required conditional trial and
control with `rtol=1e-13` and `atol=1e-19` in both engines. Its four Linux
partitions were produced at revision `b0891863ffd90b3dfb5c944720f0512d81584167`
in [run 43158961987](https://github.com/m9h/GRN_ODE/actions/runs/43158961987).
The full audit covers **573 conditional trials, 836 response-trials and 2,360
branch records**, representing 2,312 distinct branch specifications. There are
no unresolved conditional decisions. Every branch comparison passes; the
largest scaled discrepancy is **0.51046**, below the acceptance limit of one,
for `C_Raf` at time 1912.62.

The original 116/118 results remain separate. The refined run has a different
trial inventory from either original run: the literal continuation rule can
change when small numerical residues change. Each inventory is audited against
its own complete conditional search; different trial counts are not treated as
equivalent coverage of identical trajectories.

The diagnostic now divides each branch's recorded relative and absolute
tolerances by 10 and 20. A fixed absolute setting of `1e-15` would have loosened
this model's original `1e-18` request. Ten focused tests check strict tightening,
the preserved Goldbeter requests, complete source-failure selection and rejection
of altered timed-drive encodings. That diagnostic revision passed 156 local
tests, with the optional Heyoka adapter skipped in the main environment.

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_breaking_refinement.py \
  --report results/catalog-breaking-linux-26/shard-3/BIOMD0000000664.json \
  --output results/catalog-breaking-muller26-refinement
MPLBACKEND=Agg uv run --locked python scripts/audit_breaking_shards.py --network 26 \
  --input results/catalog-breaking-muller26-full-recovery/shard-0 \
  --input results/catalog-breaking-muller26-full-recovery/shard-1 \
  --input results/catalog-breaking-muller26-full-recovery/shard-2 \
  --input results/catalog-breaking-muller26-full-recovery/shard-3 \
  --output results/catalog-breaking-muller26-full-recovery/audit.json
```

### Complete network 30 coverage with numerical mismatches

The [network 30 audit](results/catalog-breaking-linux-30/audit.json) covers
all four Marhl partitions: **38 initial cases, 171 conditional trials and
783 branch records**. All required conditional decisions were evaluated.
Twenty-six cases pass; 12 retain mismatches in 30 completed branches. All
integrations finish, with no missing branch output or unresolved continuation.
These full-horizon breaking mismatches are separate from the three shorter
paired-learning branches discussed in [the precision diagnostic](PRECISION_DIAGNOSTICS.md).
The precision results there do not validate these breaking trajectories.

Networks 28 and 29 first reached their five-hour partition budgets with
103 and 133 recorded case results respectively; 89 and 133 of those passed.
Their [first checkpoint continuation](https://github.com/m9h/GRN_ODE/actions/runs/43155055643)
also reached its budgets, increasing recorded results to 228/622 and 264/1,088,
with 201 and 264 passes reported. Hidden checkpoints from both generations
are retained. The sixteen-partition continuation above uses the newer artifacts;
these partial reports are not counted as completed models.

### Ciliberto partition-zero refinement

The first completed sixteen-way Ciliberto partition (network 28, BioModel 697)
contains **38 of the model's 622 initial cases**. Thirty-six pass; two retain
ten incomplete COPASI branches. The [source record](results/catalog-breaking-ciliberto28-shard0-refinement/source-partition.json)
identifies the workflow artifact and its checksums. This is partial model
coverage, separate from the complete-model totals below.

The [completed refinement diagnostic](results/catalog-breaking-ciliberto28-shard0-refinement/report.json)
reruns all ten failed branches at three requests, retaining the full 0–2210
interval, 221,001 observations and original reset schedules. RoadRunner
completes all 30 integrations. COPASI completes none at `1e-12/1e-14` or
`1e-13/1e-15`, and six of ten at `5e-14/5e-16`. Each of those six agrees with
RoadRunner at the matching request, but **zero branches pass the complete
refinement gate**, which also requires the preceding request and its
within-engine comparison. No cases are recovered.

The [verification record](results/catalog-breaking-ciliberto28-shard0-refinement/verification.json)
checks the captured original failure inventory against the source archives,
source hashes, all integration requests and the recorded comparison outcomes.
This producer saves window summaries and comparison records, not full raw
diagnostic arrays; this verification is not an independent pointwise rerun.
Reproduce the integrations in a fresh output directory with:

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_breaking_refinement.py \
  --evidence results/catalog-breaking-ciliberto28-shard0-refinement/source-evidence.json \
  --output results/reproduced-ciliberto28-shard0-refinement
```

The [Radau diagnostic](scripts/diagnose_scipy_breaking.py) provides a second
route for these failed native branches. It compares two SciPy Radau requests,
using the guarded Jaxkineticmodel equations and Jacobian, with two refined
RoadRunner requests. All six pairwise full-trajectory comparisons must pass.
It saves every raw array, observable and reset count, and preserves the distinct
trained/untrained and cue/sham schedules. Its twelve tests check the source
inventory, exact schedules, tiny absolute tolerances and safe checkpoint reuse.

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_scipy_breaking.py \
  --evidence results/catalog-breaking-ciliberto28-shard0-refinement/source-evidence.json \
  --output results/catalog-breaking-scipy-ciliberto28-shard0
```

This is a branch diagnostic. Complete-case recovery additionally requires
all corresponding controls, recomputed scores and validation of the conditional
search. `--resume` requires unchanged source, settings and environment, and
checks every cached array before reuse. A completed mismatch cannot be relabelled
as a pass merely because the integration finished.

### Complete network 33 control validation

The [network 33 audit](results/catalog-breaking-linux-33/audit.json) validates
the Tyson 1999 circadian model's full untreated control: 221,001 observations
over 0–2210 and all three observables agree across the two engines, with a
largest scaled discrepancy of 0.02223. There are no eligible initial cases
under this protocol. The other three partitions are explicitly empty; the
model's result depends on the validated control in partition zero.

### Complete network 34 validation

The [Marwan 2003 regulatory-hierarchy model](models/BIOMD0000000037.xml),
network 34, passes all **360 initial cases, 3,254 conditional trials and
6,509 response-trials**. Its [combined audit](results/catalog-breaking-linux-34/audit.json)
validates four disjoint Linux partitions from run `43101294718` at revision
`2e7327b0d273f4b33bdd8aa37601c1a497854a2a`. Every branch passes, with
12,936 branch records representing 12,870 distinct specifications, and no
unresolved conditional decisions. The [artifact record](results/catalog-breaking-linux-34/source-artifacts.json)
retains the downloaded archive and public-file checksums.

Of the 6,509 response-trials, 6,397 have no resolved history effect at rechallenge.
Twenty-one meet the controlled half-restoration criterion; three remain
unresolved at that classification threshold despite passing trajectory
agreement. Numerical validation therefore does not mean every intervention
produces a memory effect or a resolved behavioral label. These are conditional
trials with repeated response species and histories, not independent samples
for estimating population frequencies.

Published terminal breaking reports now cover **20 distinct models**. After
the separate network-4 and network-26 recoveries, 18 models have passing full
numerical validation; reduced Goldbeter and Marhl retain the failures described
above. Fifteen models still need their complete searches. All-35 completion
and whole-catalog frequency comparisons remain pending.

## Source protocol and documented discrepancies

### Tiny residuals change literal search paths

The [local/distributed comparison](results/catalog-breaking-muller26-run-comparison/report.json)
audits both complete network 26 runs before comparing their recorded trials.
Their model, calibration, experimental settings and package versions match.
Both validate 116/118 initial cases, but **38 cases have different search paths**:
the local run performs 594 conditional trials and the distributed run 524.
The runs share 502 trials and 1,440 response/engine assessments. Their controlled
classification keys agree on every shared assessment, while **210 raw reversal
labels differ**. All four means involved in every raw disagreement have magnitude
below `1.35e-19`, far below the `1e-7` absolute comparison floor.

For example, the first trial of `C_Raf_inactive__down--FGFR__up` measures the
response `MSH`. With the source's last regulation code equal to one, its literal
downward-reversal test is `cue_mean <= pre_mean / 1.5`:

| RoadRunner run | Pre-cue mean | Cue mean | Literal downward reversal |
|---|---:|---:|---|
| Local | −2.48124e-38 | −1.12648e-42 | No |
| Distributed | 6.72825e-39 | 3.05462e-43 | Yes |

The sign of a residue near zero changes this inequality. Both runs classify
the response as having **no resolved history effect at rechallenge**. The local
case continues through eight trials; the distributed case stops after one.
This illustrates sensitivity in the literal search rule, not a resolved memory
effect. We retain the literal rule for replication and report classifications
that account for numerical resolution separately.

There are 92 trials unique to the local run and 22 unique to the distributed
run. The comparison makes no equivalence claim for these unshared trials and
does not rerun trajectory arrays. Seven focused tests check the distinction
between raw and controlled labels, complete assessment inventories and the
limits of comparisons between different paths.

```bash
MPLBACKEND=Agg uv run --locked python scripts/compare_breaking_runs.py \
  --network 26 --source-revision 70a3afad61357e94873ff62a7300c099b4c7ae3e \
  --local results/catalog-breaking-original-completed \
  --partition results/catalog-breaking-linux-26/shard-0 \
  --partition results/catalog-breaking-linux-26/shard-1 \
  --partition results/catalog-breaking-linux-26/shard-2 \
  --partition results/catalog-breaking-linux-26/shard-3 \
  --output results/catalog-breaking-muller26-run-comparison/report.json
```

### MATLAB protocol and reconstruction limits

The operational source is
[`Find_DrugRes_Sensitize_SLURM1.m`](../Find_DrugRes_Sensitize_SLURM1.m), using
[`stimulateRelaxSingle.m`](../stimulateRelaxSingle.m) for the later exposures.
The search has up to three trials: a first new input B, the same input B again
if required, then every eligible different input C if still required. Each
trial contains one breaker exposure, a rest, one UCS rechallenge and a rest.

The [paper's sections 2.7–2.8 and 4.5–4.6](https://pmc.ncbi.nlm.nih.gov/articles/PMC9820177/)
describe sequences and scoring that differ from the checkout: some descriptions
use two breaker exposures or two UCS tests per trial. We follow the code's
explicit sequence and record its rule alongside additional controls. We do not
claim to reproduce a uniquely specified historical protocol or its prevalence.

One additional code defect is corrected: after computing `X9`, the resistance
branch sets `GenesDrugResis7 = X8(end,:)` before computing `X10`, discarding the
second rechallenge's state change. Our continuous simulation retains the actual
evolved state through every exposure and relaxation. This also preserves native
time, event state, rule variables and delay history. The original XML is unchanged.

## Eligibility and complete search

Initial eligibility is the **union** of the two engines' raw MATLAB resistance
and sensitization labels in the validated repeated screen. This covers either
engine's search path despite the numerical fragility of some raw labels. Every
candidate retains both engines' eligibility, phenotype and last nonzero pulse
code; the controlled repeated-pulse categories remain available in the source
report.

For each eligible UCS/response pair, B ranges over every other independently
writable state, in both directions with nonzero calibrated reset levels. C must
also differ from B. Thus the first trial requires three distinct identities,
and the third requires four. As in the MATLAB search, zero breaker levels are
excluded rather than replaced by invented nonzero doses. All levels come from
the original repeated screen's untreated 0–1010 calibration, even though the
new experiment can last longer.

For each response, a trial continues if either engine that considered the
response eligible has not passed the raw MATLAB reversal test. A raw-positive
result can stop a path while failing controlled interpretation. Both facts are
reported; the controls do not silently change the source algorithm's search
order. If the third trial is reached, every eligible C/direction is tested.
Responses with no available fourth identity are recorded explicitly.

## Continuous timeline

The six original pulses and intervening rests occupy 0–1010. Each later phase
lasts 100 native time units:

| Trial | Breaker | Rest before test | UCS rechallenge | Rest after test |
|---|---|---|---|---|
| 1 | B: 1010–1110 | 1110–1210 | 1210–1310 | 1310–1410 |
| 2, if required | B: 1410–1510 | 1510–1610 | 1610–1710 | 1710–1810 |
| 3, if required | C: 1810–1910 | 1910–2010 | 2010–2110 | 2110–2210 |

Later exposures use 999 resets at interval 0.1, excluding onset and withdrawal,
matching the single-stimulus helper. The six-pulse prefix keeps its 4,506 resets,
including onset and withdrawal. A full three-trial treated branch therefore
has **10,500 resets**. All branches run from the original model initial state;
no concentration-only restart approximates an evolved state.

## Eight controls at each trial

Three binary factors produce eight arms:

1. The original six-pulse history is present or absent.
2. The breaker sequence through the current trial is present or sham.
3. The current UCS rechallenge is present or sham.

**Earlier UCS rechallenges remain in every corresponding arm**, including the
current-cue sham. At trials 2 and 3, the group without initial training has
therefore still received earlier test pulses. This matches prior probe history
and prevents the last probe's effect from being confused with prior tests.
Identical complete intervention schedules, integration settings and end times
share a simulation branch.

Let $Y_{h,b,q}$ be the mean response during the current rechallenge window:
$h$ indicates the original six-pulse history, $b$ the breaker sequence and $q$
the current UCS cue. The incremental cue effect is

$$G_{h,b}=Y_{h,b,1}-Y_{h,b,0}.$$

The history-dependent cue effect without and with the breaker is

$$E_0=G_{1,0}-G_{0,0},\qquad E_B=G_{1,1}-G_{0,1}.$$

Their difference $E_B-E_0$ tests whether the breaker changes the effect of the
initial history. Persistent level shifts and direct cue effects shared by both
initial-history groups cancel. If $E_0$ is unresolved, the case cannot establish
breaking of an acquired cue response at this clock time: it may have already
decayed, or the raw pretest may have measured something else.

The operational restoration criterion is a resolved reduction by at least half:

$$\tfrac12|E_0|-|E_B|>\epsilon,$$

where $\epsilon=\tfrac12\epsilon_{E_0}+\epsilon_{E_B}$. Each linear contrast's
resolution is the sum of the absolute-coefficient-weighted per-mean tolerances
$10^{-7}+2\times10^{-5}|Y|$. This is an operational numerical-resolution rule,
not a confidence interval or a rigorous integration-error bound.

Categories distinguish half restoration, reversal, amplification, a smaller
change, no resolved breaker effect, no remaining resolved history effect, a
threshold ambiguity, and negative response states. Both engines must agree on
the category and all component contrast directions. A reduction is a finite
model response, not evidence of a particular mechanism or clinical efficacy.

The raw MATLAB score is also retained: a mean at least 1.5 times the preceding
rest receives an upward reversal label if the source's last code was downward;
a mean at most the preceding rest divided by 1.5 receives the converse label.
This includes the original zero-equality artifact. Raw differences are audited
separately from the controlled validation gate.

## A domain limit exposed by the Goldbeter model

Network 3 (BioModel 3) is the reduced Goldbeter mitotic oscillator.
[The original paper](https://doi.org/10.1073/pnas.88.20.9107), page 9108,
defines `M` and `X` as active fractions, with biological range 0–1. The
unchanged 100× calibration gives `M__up = 70.9307444` and
`X__up = 64.1636971`. Six of this model's eight initial breaking cases include
one of these resets. They therefore extrapolate the equations beyond their
original biological interpretation, even when integration passes. The
single-input and repeated screens likewise have two such cases out of six.

The activation terms contain denominators `0.005 + 1 - M` and
`0.005 + 1 - X`, which vanish at 1.005. In the first full breaking run,
`M__up--X__up` and `X__up--M__up` each have failed branches. The
[diagnostic script](scripts/diagnose_goldbeter_breaking.py) preserves the exact
reset schedules and compares both engines at three relative/absolute requests:
`1e-10/1e-12`, `1e-12/1e-14`, and `1e-13/1e-15`.
**All 24 integrations stop before the required endpoint**, in narrow regions
near time 1156.5317 or 1356.5317. COPASI's exposed final state approaches the
`M` activation denominator to within approximately `5e-9` of zero.

The [report](results/catalog-breaking-goldbeter-diagnostic/report.json) records
requests, reset counters, stopping times, exposed states, domain violations,
source hashes and versions. RoadRunner's state after an exception is not
assumed synchronized with its final internal CVODE step. These results establish
failed numerical convergence outside the biological domain; they do not prove
finite-time blow-up or nonexistence of a mathematical continuation.
The original amplitudes and XML remain unchanged, and these cases are not
counted as validated. Clipping fractions or adding inactive species would
define a different intervention or model, suitable for a separate comparison.

```bash
MPLBACKEND=Agg uv run --locked python scripts/diagnose_goldbeter_breaking.py
```

## Refinement recovery for the explicit-pool Goldbeter model

Network 4 (BioModel 4) has explicit inactive pools and a different failure mode
from the reduced model above. Its first full run evaluates all 54 initial cases;
51 pass, while eight branches across the other three cases complete but exceed
the trajectory-comparison tolerance. The largest normalized discrepancy is
1.74136, chiefly in `M` near time 2011. All eight branches extend to time 2210,
with 221,001 sampled times and seven original observables.

The [native refinement diagnostic](results/catalog-breaking-goldbeter4-refinement/report.json)
retains the original schedules and compares each engine at the original
`1e-12/1e-14` request, at `1e-13/1e-15`, and at `5e-14/5e-16`.
All 48 integrations complete. Every branch passes cross-engine comparison at
both tighter requests, as well as each engine's comparison between those two
requests. The largest cross-engine discrepancy is 0.17109 at `1e-13/1e-15`
and 0.06729 at `5e-14/5e-16`. The largest within-engine refinement discrepancies
are 0.12549 for RoadRunner and 0.02173 for COPASI. Acceptance remains 1.

Network 4 now requests `1e-13/1e-15` in both native solvers. Calibration, XML,
reset timing, output grid and acceptance thresholds are unchanged. The
[complete recovery](results/catalog-breaking-goldbeter4-full-recovery/audit.json)
now passes **all 54 cases, 323 conditional trials and 1,327 branches**, covering
442 response-trials. The audit verifies the complete conditional search and
recomputes every score against both engines. There are no incomplete branches,
trajectory mismatches, solver retries or unresolved continuation decisions.
The producer source is `40ca8ff586220a5df573e7d383defa2c19ed829a`.
This recovery is separate from the preserved original 51/54 result.
The [captured source evidence](results/catalog-breaking-goldbeter4-refinement/source-evidence.json)
preserves the original model report, all eight failed branch records and the
verified hashes of its complete branch inventory.

```bash
python scripts/diagnose_breaking_refinement.py \
  --evidence results/catalog-breaking-goldbeter4-refinement/source-evidence.json \
  --output results/reproduced-goldbeter4-refinement
python -m grn_memory.catalog_breaking --network 4 --workers 1 \
  --timeout 604800 --output results/catalog-breaking-goldbeter4-recovery
python scripts/audit_breaking_catalog.py \
  --input results/catalog-breaking-goldbeter4-full-recovery --network 4 \
  --source-revision 40ca8ff586220a5df573e7d383defa2c19ed829a \
  --output results/catalog-breaking-goldbeter4-full-recovery/audit.json
```

## Validation, checkpoints and evidence

The default output grid is 0.01 native time units. Samples coinciding with any
possible reset move to the actual time reset +$10^{-5}$, in every arm. Means are
arithmetic sample means, not converged continuous-time integrals. Every original
observable at every sampled time must meet the unchanged comparison threshold
$10^{-7}+2\times10^{-5}\max(|a|,|b|)$.

Integration requests and case-specific overrides come from the repeated screen.
For Rohwer, COPASI has one declared fallback, `rtol=1e-7`, `atol=1e-9`, only if
the original request raises a solver error or returns a partial trajectory.
Every attempt and the settings actually used are recorded. A completed trajectory
that fails the independent comparison is not retried under looser settings.
The need arose in a third-trial control after repeated `EIIAP` stimulation:
the ordinary request stopped at about 2030.41; the fallback completed all
221,001 samples with a normalized discrepancy of 0.15533. A still looser
`1e-6/1e-8` diagnostic failed comparison and is not an allowed fallback.
The Yoon timed-drive event representation receives an additional untreated
comparison with the original encoding in each engine over the full 0–2210
window. Delay controls receive the independent step/jump-width refinement.
Negative response ranges beyond tolerance are retained and marked as outside
the physical interpretation of concentration-based learning.

```bash
uv sync --locked --extra test --extra delay
MPLBACKEND=Agg uv run --locked --extra test --extra delay python -m pytest -q tests/test_catalog_breaking.py tests/test_protocol_retries.py
MPLBACKEND=Agg uv run --locked --extra delay python -m grn_memory.catalog_breaking --workers 3 --timeout 86400 --output results/catalog-breaking
```

Use `--resume` after interruption. Fingerprints cover the complete configuration,
source code, model XML, repeated-screen reference file, candidate plan and package
versions. Passed branch and case checkpoints are reused only when these match.
Failed branches are retried on resume. A bounded in-memory cache avoids retaining
the full search tree in RAM. `--timeout` is per model; it does not alter the
experiment. Partial `--limit-cases` or `--case` selections do not pass coverage.

Each model's JSON records case coverage and a manifest of hashed compressed
evidence shards. Branch shards contain schedules, integration settings,
cross-engine comparisons and every original observable's window means and ranges.
Case shards contain each conditional trial, response scores, search continuation
and branch references. They use gzip JSON Lines, with at most 100 records per
shard; Python's `gzip` module or `gzip -dc` can read them. Local atomic checkpoints
live in the ignored `.evidence/` directory. Published manifests identify exactly
which records belong to that run, excluding unused old checkpoints.

Ten tests cover residual levels, shared direct effects, restoration versus
overshoot, unresolved and negative states, raw continuation across engines,
the full three-trial schedule, distinct node identities, checkpoint provenance
and the exhaustive candidate inventory, plus bounded solver retries that cannot
turn a completed numerical mismatch into a pass. All ten pass locally. The
selected-case pilot is deliberately partial, so its aggregate status remains
incomplete despite all selected cases passing. Full run findings will be
recorded when their evidence is complete.
