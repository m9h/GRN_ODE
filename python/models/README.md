# The five BioModels used in this replication

These are **protein-signaling models** of the MAPK pathway. Although the parent
repository is called `GRN_ODE`, these five networks do not model transcription,
translation or changes to gene-network weights. Their state variables are
concentrations of proteins, phosphorylation states and enzyme-bound complexes.
The experiments ask what stimulation history can do to those biochemical states.

[BioModels](https://www.ebi.ac.uk/biomodels/) is a repository of computational
biological models. An SBML file describes species, reactions, rate laws,
parameters, initial conditions, compartments and annotations. A simulator such
as RoadRunner or COPASI supplies the numerical integration. BioModels curation
checks reproducibility of the source publication's simulations; it is not a
validation of the later memory experiments we impose on the model.
[BioModels' description of curation](https://doi.org/10.1002/psp4.3)

## Why these models?

The selected models occur in supplementary Table S1 of
[Biswas, Clawson and Levin (2023)](https://doi.org/10.3390/ijms24010285).
They support the paper's clearest examples of retained responses, associative
recall and repeated stimulation, and are small enough to inspect and run locally.
Four are variants from the same Markevich study, so they are not five independent
biological systems or a representative sample of the 35-model survey.

| BioModels record / local file | Paper network | Evolving species | Fixed species | SBML reaction elements | Representation and use |
|---|---:|---:|---:|---:|---|
| [0010](https://www.ebi.ac.uk/biomodels/BIOMD0000000010) / [XML](BIOMD0000000010.xml) | 7 | 8 | 0 | 10 | Three-stage MAPK cascade; declining response under repeated stimulation |
| [0026](https://www.ebi.ac.uk/biomodels/BIOMD0000000026) / [XML](BIOMD0000000026.xml) | 15 | 11 | 0 | 10 | Ordered phosphorylation with explicit enzyme complexes; association, transfer and drift control |
| [0027](https://www.ebi.ac.uk/biomodels/BIOMD0000000027) / [XML](BIOMD0000000027.xml) | 16 | 3 | 2 | 4 | Reduced ordered cycle; accumulating response under repeated stimulation |
| [0029](https://www.ebi.ac.uk/biomodels/BIOMD0000000029) / [XML](BIOMD0000000029.xml) | 18 | 4 | 2 | 7 | Alternative phosphorylation orders; second intervention changes rechallenge response |
| [0031](https://www.ebi.ac.uk/biomodels/BIOMD0000000031) / [XML](BIOMD0000000031.xml) | 19 | 3 | 3 | 4 | Two separate kinases; retained-response and no-memory comparison |

Counts come from the checked-in XML. A reversible reaction element can encode
forward and reverse fluxes together, so the reaction count is not necessarily
the number of elementary reaction directions. The fixed enzymes in the reduced
models have `constant="true"`; they are not additional evolving ODE states.
The short numbers above abbreviate identifiers such as `BIOMD0000000026`.

## Reading the biology and the equations

MAPK means mitogen-activated protein kinase. A kinase adds a phosphate group;
a phosphatase removes one. In the reduced models, `M` denotes unphosphorylated
MAPK, `Mp` a singly phosphorylated form, and `Mpp` the doubly phosphorylated form.
An underscore often identifies a complex: `Mp_MAPKK` is a bound complex of `Mp`
with its kinase, not a synonym for free `Mp`.

A typical ordered cycle is

$$M \xrightarrow{v_1} M_p \xrightarrow{v_2} M_{pp},
\qquad M_{pp}\xrightarrow{v_3}M_p\xrightarrow{v_4}M.$$

At compartment volume $V$, its concentration equations are

$$\dot M=(-v_1+v_4)/V,\quad
\dot M_p=(v_1-v_2+v_3-v_4)/V,\quad
\dot M_{pp}=(v_2-v_3)/V.$$

The sum of those derivatives is zero. Without intervention, phosphorylation
redistributes a fixed molecular pool. Our concentration resets can change that
pool. A post-training difference must therefore be interpreted in light of the
material introduced or removed, rather than automatically called a new attractor.

**Ordered** means the phosphorylation steps follow a prescribed sequence.
**Distributive** means enzyme and substrate can dissociate between modifications;
the enzyme does not necessarily add both phosphates in one encounter.
**Random order** permits alternative first sites; it does not mean the ODE
simulation is stochastic. Michaelis-Menten-like reductions replace explicit
binding states with saturating rate laws. Their denominators can also represent
competition between substrate forms for the same enzyme.

## 0010: feedback and ultrasensitivity across a kinase cascade

Source: Kholodenko BN (2000),
[Negative feedback and ultrasensitivity can bring about oscillations in the mitogen-activated protein kinase cascades](https://doi.org/10.1046/j.1432-1327.2000.01197.x).

This model has three layers: `MKKK` activates `MKK`, and activated `MKK` activates
`MAPK`. The SBML annotations name them Mos, Mek1 and Erk2. The top layer has two
states; each lower layer has unphosphorylated, singly phosphorylated and doubly
phosphorylated states. Terminal `MAPK_PP` inhibits the first activation reaction.
The original study asks how strong input-output sensitivity and negative feedback
can generate oscillations. [Model notes and equations](BIOMD0000000010.xml)

For example, the first reaction is encoded as

$$v_0=V\frac{V_1\,MKKK}{(1+(MAPK\_PP/K_i)^n)(K_1+MKKK)}.$$

The inhibitory factor couples the end of the cascade back to its beginning;
the saturation term makes the response nonlinear. `V1`, `Ki`, `n` and `K1` are
local kinetic parameters in this SBML reaction, rather than global parameters.
Our experiment repeatedly lowers `MKK` and measures `MKK_PP`. Its declining
response should be compared with the untreated evolving network, not a presumed
stationary baseline. [Experiment result](../results/habituation.png)

## 0026: explicit complexes and history-dependent cue responses

Source: Markevich NI, Hoek JB and Kholodenko BN (2004),
[Signaling switches and bistability arising from multisite phosphorylation in protein kinase cascades](https://doi.org/10.1083/jcb.200308060).

Model 26 explicitly represents `M`, `Mp`, `Mpp`, free kinase `MAPKK`, free
phosphatase `MKP3`, and six enzyme-substrate/product complexes. Binding,
unbinding and catalysis create transient sequestration: enzyme held in one
complex is unavailable for another reaction. For example, the first binding
flux is $v_{1a}=V(k_1 M\,MAPKK-k_{-1}M\_MAPKK)$, followed by catalytic flux
$v_{1b}=V k_2 M\_MAPKK$. [Model notes and equations](BIOMD0000000026.xml)

The original paper explores how distributive multisite modification can support
bistability and hysteresis without an imposed positive-feedback loop. Our memory
tests use the supplied parameter set and finite observation windows; they do not
establish a bifurcation diagram or prove bistability for each tested condition.

In the positive associative example, UCS is an increase of `M_MKP3`, CS is a
decrease of free `M`, and the response is the `Mp_MAPKK` complex. Both the input
and output can therefore be molecular complexes rather than abstract genes.
We compare paired training, UCS-only training, a naive cue and a sham probe.
The same model supplies a second saved associative case whose response is almost
identical with and without the probe. [Association](../results/associative_recall.png),
[drift control](../results/drift_control.png), [transfer](../results/transfer.png).

## 0027: a reduced cycle with a shared kinase

This Markevich variant retains only the three evolving MAPK forms and four net
conversion reactions. `MAPKK=50` and `MKP3=100` are fixed enzyme concentrations.
The omitted binding complexes are represented through competitive,
Michaelis-Menten-like rate laws. For example,

$$v_1=V\frac{k_{1cat}\,MAPKK\,(M/K_{m1})}
{1+M/K_{m1}+M_p/K_{m2}}.$$

Both `M` and `Mp` compete for the same kinase through the denominator. This
reduction makes the conservation law $M+M_p+M_{pp}$ easy to inspect. The SBML notes
associate this model with Figure 3 of the original Markevich paper.
[Model notes and equations](BIOMD0000000027.xml)

Our repeated-input example raises `Mp` and observes accumulating `Mpp`. Repeated
resets inject material, and successive pulses grow longer, so the rising trace
alone does not establish increased sensitivity at a fixed exposure.
[Experiment result](../results/sensitization.png)

## 0029: two alternative singly phosphorylated forms

This reduced Markevich model distinguishes `MpY` (the tyrosine-phosphorylated
form) from `MpT` (the threonine-phosphorylated form). Phosphorylation can begin
at either site, while dephosphorylation follows the ordered mechanism described
in the model notes. `MEK=180` and `MKP3=100` are fixed; four substrate species
evolve through seven reaction elements. The original notes point to schema 3,
Figure 2 and supplementary Table S3. [Model notes and equations](BIOMD0000000029.xml)

Here we repeatedly lower `MpT`, then raise `M` as a second intervention, and
finally apply the original input again while observing `Mpp`. The comparison
continues from the same conditioned state with a sham second intervention.
The resulting response changes sign relative to its preceding rest window.
This is a numerical intervention in a biochemical model, not a tested drug
regimen. [Experiment result](../results/breaking_habituation.png)

## 0031: two separate kinases

This Markevich variant again has three evolving substrate forms, but uses
`MAPKK1` for the first phosphorylation and `MAPKK2` for the second. A shared
`MKP3` phosphatase acts on both phosphorylated forms. The fixed values are
`MAPKK1=100`, `MAPKK2=1`, `MKP3=100`. The kinase-rate denominators no longer have
the same cross-competition as model 27. Its SBML notes identify the original
paper's supplementary Figure S9. [Model notes and equations](BIOMD0000000031.xml)

This is the small model used for our side-by-side retention tests: lowering `Mp`
and measuring `Mpp` fails the 50% retention test, while raising `Mpp` and measuring
`Mp` passes. The latter retains a changed total MAPK pool, so the observation
does not by itself prove switching between stable states at the same total.
[No-memory example](../results/no_memory.png),
[retained-response example](../results/retained_response.png).

## Initial states, units and reproducibility

| Model | Nonzero initial species values | Conserved pools between interventions |
|---|---|---|
| 0010 | `MKKK=90`, `MKKK_P=10`; each lower layer starts `280, 10, 10` | Top layer 100; middle and bottom layers 300 each |
| 0026 | `M=500`, free `MAPKK=50`, free `MKP3=100` | MAPK-bearing forms total 500; free plus bound kinase 50; free plus bound phosphatase 100 |
| 0027 | `M=500`; fixed enzymes as above | `M + Mp + Mpp = 500` |
| 0029 | `M=800`; fixed enzymes as above | `M + MpY + MpT + Mpp = 800` |
| 0031 | `M=500`; fixed enzymes as above | `M + Mp + Mpp = 500` |

Other evolving species start at zero. The XML defines substance units as
$10^{-9}$ mole, with a size-one compartment; we preserve native SBML values and
use concentration output consistently. Some files specify initial amounts and
others initial concentrations. They agree numerically for these size-one
compartments, but that cannot be assumed for arbitrary models. The test suite
includes a two-litre case to check the distinction. Parameter annotations are
not a substitute for a full dimensional audit.

These snapshots use SBML Level 2: Version 1 for 0026 and 0029, Version 4 for the
other three. None has events, rules or initial assignments. Our intervention
schedule is implemented by the experiment runner rather than embedded as SBML
events. The supplied reaction definitions and parameters remain unchanged.

[manifest.json](manifest.json) records download URLs, SHA-256 hashes, species
order, model structure, paper references and licensing evidence.
[catalog.json](catalog.json) maps all 35 paper-network numbers to BioModels IDs;
it is a catalog, not a claim that all 35 have been reproduced. Tests compare the
five initial state vectors with the authors' saved `forST.mat` and verify the
downloaded-file hashes. Record the git commit and protocol along with the model
ID when reporting an experiment; the identifier alone does not pin a file revision.

## Licensing and attribution

The encoded models and their annotations are covered by BioModels'
[CC0 policy](https://biomodels.org/termsofuse), separately from our MIT-licensed
implementation. [LICENSE](LICENSE) documents the five files, their embedded
notices and the basis for that designation. Historical XML notices remain intact;
we do not replace them with our copyright statement.

Please cite the model's original paper, its full BioModels ID and the memory
study when using these experiments, and identify this fork and its changes.
This preserves scientific attribution even though CC0 does not impose an
attribution condition. [BioModels' policy explanation](https://doi.org/10.1002/psp4.3)
