# Licensing and provenance

This repository contains material from different sources. The root
[MIT license](LICENSE) covers Morgan Hough's original contributions to this fork;
it does not replace upstream or model-specific terms.

| Material | Applicable notice |
|---|---|
| Original Python replication code, tests, notebooks, documentation and generated plots | MIT, copyright 2026 Morgan Hough |
| Original workflow, configuration and provenance-metadata additions | MIT |
| Five downloaded SBML models in `python/models/` | BioModels' CC0 1.0 Public Domain Dedication; see [model notice](python/models/LICENSE) |
| Original MATLAB scripts and `.mat` files | Upstream authors' rights; no license file was supplied at the imported baseline |
| Third-party dependencies and cited papers | Their respective terms |

## Original replication contributions

The MIT grant covers original content in `python/grn_memory/`, `python/tests/`,
`python/examples/`, `python/results/`, the Python guides, and the fork's original
configuration, model documentation, and metadata. It also covers the original
portions of changes to the root README. Downloaded SBML files and any third-party
content are excluded from that grant.

The Python implementation uses the models and experimental ideas described in
the papers; attribution and scientific provenance remain in the documentation.
Applying MIT to the new implementation does not license the papers or imply
endorsement by their authors.

## Upstream MATLAB material

The original source is
[wesleypclawson/GRN_ODE](https://github.com/wesleypclawson/GRN_ODE), imported at
commit `aaa60c37a49d41b5fa15e09b9a81d098674694fc`.
Its README credits Biswas for the coding work. No license file was present in
that baseline. Its `.m` scripts, saved `.mat` results and other inherited material
are not relicensed by this fork. In particular, tests reading `forST.mat` do not
make that source dataset part of our MIT grant.

## BioModels material

The [BioModels terms](https://biomodels.org/termsofuse) dedicate the encoded models
and associated annotations to the public domain under CC0. The BioModels team's
[published description](https://doi.org/10.1002/psp4.3) also explains that policy.
This is distinct from both our MIT license and the licenses of the original
scientific articles.

The downloaded XML files are preserved byte for byte. Some contain an explicit
CC0 notice; others retain older copyright/terms links or only scientific notes.
Those historical notices remain intact. The model-level notice records the
repository policy and the evidence present in each file. Attribution to the
model authors and BioModels is retained, and the
[model guide](python/models/README.md) links the relevant papers and records.
