# Scheduling complete Fuss continuations

The first run retained 274 complete integration arrays across all 32 partitions.
The first sixteen resumed partitions added 137 arrays while preserving their
137 earlier arrays byte for byte. Some individual Radau integrations take hours;
an integration interrupted by the job limit must currently restart. These
observations motivate a scheduling change for subsequent continuations.

The workflow now permits sixteen concurrent partitions, subject to GitHub's
available runner capacity. Each worker has a 19,200-second cooperative budget
and a 19,800-second external time limit. The six-hour job limit retains thirty
minutes for setup, checkpoint verification, termination grace and upload.
The previous limits were 16,800 and 17,400 seconds with eight parallel partitions.

This changes scheduling only. All numerical implementation files, the original
execution plan and source inputs, all 1,309 trajectories, both COPASI requests,
both Radau requests, all observation times and all acceptance checks remain
byte-identical to producing revision
`4c0f97adcf1e54019792f5eaf57963efb62cedf1`. The same strict parent restore checks
apply. A changed Git revision is recorded for the new workflow, while the
numerical implementation hashes and experiment fingerprint remain unchanged.

The currently running workflow is unaffected. A continuation using these limits
must wait for its entire parent workflow to finish, retain a predetermined
complete selection of the original partition indices, and verify all parent
artifacts and cached arrays. It cannot promote a partial inventory or recover
any case without the complete case audit.

The only test-code change decodes compiler output explicitly as UTF-8 so that
the existing delay-equation test also works in an ASCII locale. Its numerical
test and assertions are unchanged.
