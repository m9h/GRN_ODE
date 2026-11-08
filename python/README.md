# Learning and memory experiments in SBML networks

This code reproduces selected demonstrations from Biswas, Clawson and Levin,
[Learning in Transcriptional Network Models: Computational Discovery of Pathway-Level Memory and Effective Interventions](https://doi.org/10.3390/ijms24010285).
The question is whether a network's response to an input depends on its previous
stimulation. Its reaction equations and rate constants remain fixed throughout
training. What changes is the molecular state.

Five original SBML models, eight experiments, two independent reference simulators, and an
[executed notebook](examples/memory_lab.ipynb) are included. See
[RESULTS.md](RESULTS.md) for what reproduced and what the controls revealed.
An optional Jaxkineticmodel backend runs the same protocols on JAX 0.12.0.1;
see [JAX validation](JAX_VALIDATION.md) for the migration and three-engine results.

## Run it

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required for the commands below.
From this repository's `python/` directory:

```sh
uv sync --locked --extra test --extra notebook
uv run --locked python -m pytest -q
uv run --locked python -m grn_memory.suite
uv run --locked jupyter lab examples/memory_lab.ipynb
```

The default suite runs all eight experiments in both libRoadRunner (CVODE) and
COPASI (LSODA). It saves plots, a machine-readable `results/report.json`, and
compressed CSV trajectories. CSVs are generated locally and excluded from git.
Individual runs are useful while exploring:

```sh
uv run --locked python -m grn_memory.suite --case associative_recall --engine roadrunner --output results/exploration
```

All SBML inputs are checked in, so running the experiments after installation
does not depend on BioModels availability. Model hashes, download URLs and native
species orders are in [models/manifest.json](models/manifest.json). The complete
35-model mapping from supplementary Table S1 is in
[models/catalog.json](models/catalog.json). Only five are simulated here.

## The mathematics

For a fixed compartment volume $V$, a reaction model has the form

$$\dot{x}=V^{-1}Nv(x;\theta),$$

where $x$ contains species concentrations, $N$ is the stoichiometric matrix,
$v$ contains reaction rates in amount/time, and $\theta$ contains kinetic
parameters. In these examples the compartments have size one. The adapters
explicitly request concentrations from both simulators; a two-litre analytic
test guards against accidentally comparing concentrations with amounts.

For example, unphosphorylated MAPK $M$ can become singly phosphorylated $M_p$ and
then doubly phosphorylated $M_{pp}$. Kinases and phosphatases drive the forward
and reverse reactions. Reduced models use saturating rate laws; model 26 includes
enzyme-substrate complexes as explicit state variables. SBML supplies the actual
rate laws and parameters, rather than replacing them with generic sigmoids.

An untreated run provides a reference and stimulus levels. The memory experiments
use $x_i^{up}=100\max x_i(t)$ and $x_i^{down}=\min x_i(t)/100$ over the first
50 model-time units. Drug experiments calibrate against their whole untreated
trajectory and exclude exact zeros when computing the minimum, as in the MATLAB
drug script. A down stimulus can therefore be zero in a memory experiment.

The MATLAB intervention is an **impulse/reset protocol**, approximately clamping
a concentration by resetting it every 0.1 model-time units:

$$x(t_{k+1}^-) = \Phi_{0.1}(x(t_k^+)),\qquad
x_i(t_k^+) = u_i.$$

Between resets, the species follows its ordinary reaction equations. This differs
from an exact continuous clamp, which would enforce $\dot{x}_i=0$ during input.
The single-stimulus MATLAB routine leaves the first 0.1-unit block unforced and
does not return its final reset; those conventions are retained. The drug routine
resets at both onset and withdrawal; `Phase` exposes those options separately.
Sampling is every 0.01 unit. A 5000-step stimulation therefore lasts 50 time units.

Let $B$, $S$ and $C$ be the mean response during baseline, stimulation and the
time-matched untreated control. Up-regulation requires $S\ge qB$ and $S\ge qC$;
down-regulation requires $S\le B/q$ and $S\le C/q$. The initial pretest uses
$q=2$. The original associative evaluator changes this to $q=1.5$ for training
and recall; that distinction is explicit here. Equal zero traces are unregulated.

For a post-stimulation relaxation mean $L$, the retained fraction is

$$\rho = \frac{L-B}{S-B}.$$

After establishing a response direction, $\rho\ge 0.5$ passes the paper's
retention test. It can exceed one if the shift continues growing. This is a
finite-window statistic, not a proof of permanent memory or convergence to an
attractor. The retention examples also include a ten-times-longer relaxation.

## What each experiment asks

| Experiment | Sequence after baseline | Question |
|---|---|---|
| UCS memory | UCS → relax | Does at least half the induced response remain? |
| Pairing memory | UCS + CS → relax | Does the paired response remain? |
| Transfer | UCS → wash → CS | Did UCS alone change the formerly neutral cue's effect? |
| Association | UCS + CS → wash → CS → relax | Is paired training required by the threshold test, and does recall persist? |
| Delayed recall | UCS + CS → wash → delay → CS | Does an actual delayed cue become effective? |
| Repeated input | Six pulses separated by rest | Does the response decline or accumulate? |
| Breaking | Repeated input → second intervention → original input | Does the second input alter the subsequent response? |

UCS means unconditioned stimulus; CS is the initially neutral candidate
conditioned stimulus. All three roles must involve distinct species. Association
requires the UCS pretest to pass and the naive CS pretest to fail. UCS-only
training is tested first to distinguish transfer from the associative label.
Short/long recall refers only to retention over one additional 50-unit window.
The evaluator implements delayed rechallenge, but this suite does not establish
a positive consolidation example or estimate its frequency.

The extra **sham probe** continues the exact same trained state without applying
the cue. A positive paper-style recall score can otherwise arise from an already
changing trajectory. This additional control is reported separately from the
paper-style label so the distinction remains visible.

## Models and provenance

These five models describe **MAPK protein signaling**, with species representing
phosphorylation states and enzyme complexes. They do not explicitly model gene
transcription or learn new reaction weights. One model is a three-stage cascade
with negative feedback; four are related variants of a phosphorylation cycle.

The [BioModels guide](models/README.md) explains each model's original scientific
question, species, rate laws, initial conditions, conserved pools and role in our
experiments, with links to the source records and exact XML files.

| Paper network | BioModels ID | Example |
|---|---|---|
| 7 | BIOMD0000000010 | Kholodenko MAPK feedback; habituation-shaped response |
| 15 | BIOMD0000000026 | Markevich explicit enzyme reactions; association and transfer |
| 16 | BIOMD0000000027 | Markevich reduced ordered model; accumulating response |
| 18 | BIOMD0000000029 | Markevich random phosphorylation; breaking intervention |
| 19 | BIOMD0000000031 | Markevich separate kinases; memory and no-memory pair |

Model 26 tracks binding complexes explicitly, whereas models 27, 29 and 31
replace them with saturating rate laws and fixed enzyme concentrations. Model 29
distinguishes two possible first phosphorylation sites; model 31 uses separate
kinases for its two phosphorylation steps. These structural differences matter:
the same stimulus name need not have the same effect across models.

BioModels curation checks reproduction of the **original model publication**.
The memory protocols are later interventions, so their interpretation and our
added controls still need to be assessed separately. The four Markevich variants
also should not be counted as independent biological systems.

The [supplement](https://www.mdpi.com/1422-0067/24/1/285/s1) establishes this
mapping. Tests verify that the independent species' initial concentrations match
`forST.mat` in the original repository, in SBML species order, for all five models.
`ODE_New.mat` supplies the saved memory triples. For example, network 15's row
`[4,11,1,7,2,1,2]` means associative memory, UCS 11 up, response 7 down, CS 1 down:
`M_MKP3`, `Mp_MAPKK`, `M`. A second saved row
`[4,11,2,3,1,9,2]` is the drift-control example. The plots use verified SBML IDs
because the figure labels are not consistently aligned with these identities.

The original model papers are
[Markevich et al. (2004)](https://doi.org/10.1083/jcb.200308060) and
[Kholodenko (2000)](https://doi.org/10.1046/j.1432-1327.2000.01197.x).
Original SBML annotations, attribution and terms-of-use notices are preserved.

## License

Original replication code and documentation are [MIT licensed](../LICENSE),
copyright 2026 Morgan Hough. The downloaded model encodings and annotations have
a separate [BioModels CC0 notice](models/LICENSE). The original MATLAB code and
saved `.mat` files remain subject to their authors' rights; no upstream license
file was supplied. [LICENSING.md](../LICENSING.md) defines these boundaries.

## Differences and limits

The original repository does not include its model-specific MATLAB `f.m` and
`Initialize_ODE.m` files. We recovered the SBML models instead. No MATLAB executable
or historical MATLAB trajectory was used as an oracle. COPASI checks numerical
agreement with RoadRunner; it does not independently validate the experimental
design or memory definitions shared by this implementation.

Several original implementation details need care:

- `DetectMem.m` returns `9999` for failure, but pairing/long-recall callers test
  `~=0`. Python returns actual Booleans and tests failure cases.
- `Mem_Eval_US_R.m` overwrites earlier UCS rows and evaluates association after
  the UCS loop. Explicit experiment configurations avoid those aggregation errors.
- The paper describes a long initial relaxation, but `Initialize_Recheck.m`
  computes extrema and the initial experimental state from the *first* 5000
  samples. We use the first 50 units and do not label it a proven steady state.
- Windows here include both endpoints (5001 samples). MATLAB baseline/reference
  slices sometimes contain 5000. This small indexing difference is documented;
  bit-for-bit agreement and original prevalence percentages are not claimed.
- The MATLAB consolidation branch watches a later relaxation without delivering
  another cue. This implementation delivers a delayed cue and includes a matched
  sham, in line with the paper's verbal definition.
- Tolerances are tighter than the historical code. Both adapters support only
  the validated autonomous, fixed-compartment reaction-model subset; event-driven
  or nonautonomous SBML requires additional restart semantics and is rejected.

**Conservation matters.** In a closed three-species MAPK model,
$M+M_p+M_{pp}$ is conserved between inputs. A concentration reset can add or remove
MAPK, changing that total. Retention can therefore reflect a changed molecular
pool, even without switching between attractors on the same conserved manifold.
Likewise, drug pulses increase in duration (50, 60, …, 100 units), so an increasing
response alone is not evidence of growing sensitivity at a fixed dose. The
notebook makes these distinctions inspectable rather than hiding them in a label.

## Connection to RNMs and SBMLtoODEjax

The later [Regulatory Network Machine paper](https://doi.org/10.1016/j.isci.2025.112536)
studies computation through regulatory-network state transitions. These experiments
provide trajectories and intervention protocols from which one could identify
states and transitions. They do not yet construct an RNM graph, establish attractor
stability, or reproduce Cellnition's Hill/logistic network equations.

For the FLOWERS contribution, the five pinned SBML files, explicit resets,
concentration conventions and dual-simulator trajectories provide realistic test
cases beyond small synthetic fixtures. A JAX backend must reproduce the same
state update schedule, then validate trajectories and intervention gradients.
There is no JAX backend or gradient validation in this replication yet; the
separate assignment-rule fix in `sbmltoodejax` remains a focused contribution.
