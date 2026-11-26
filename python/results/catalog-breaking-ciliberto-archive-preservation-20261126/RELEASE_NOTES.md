Original Ciliberto workflow artifacts, preserved byte for byte as 500 MiB chunks.

Each `artifact-ID.manifest.json` identifies the original workflow, artifact size
and SHA-256, and ordered release asset IDs and checksums. Concatenating its chunks
reconstructs the exact original ZIP, including incomplete work and failures.
The manifest is published only after freshly downloading every chunk and
reproducing that original checksum. Existing assets are never overwritten.

This release stores evidence. It makes no new scientific agreement or case
recovery claim. All 256 later-control partitions, 6,859 later branches, and the
full 7,334-branch / 74-case audit remain required. Missing artifacts remain
missing; transport does not recompute them.
