# Development history and measurement boundary

This new application is an exploratory extension designed after the original
paper and earlier HumanEval explorations. The engineering development partition
is not a previously unseen benchmark holdout. The final evaluation candidates
are not run before the separately timestamped protocol freeze.

The initial official-reference check passed 160 of 164 suites. Four suites
required helper functions from the program namespace. The corrected test
namespace inherits those helpers before loading the unchanged official suite.
Previous source and outputs remain in workload/qa_revision_v1 and
workload/qa_reference_v1. A later correction distinguishes an unknown child-start
state after a host launch with missing start evidence from a known zero-start
prelaunch rejection; previous code is retained in workload/qa_revision_v2.
Final reference checks passed 164/164 and the final 80-candidate serial
calibration retained 43 passes, 37 failures and no infrastructure error.

The first raw request development check retained an unused review route without
a review claim. The issuer correctly rejected that configuration. The corrected
request authorizes alert, abstain and no_action only; both frozen issuers accept
the bound verification request. These attempts remain in development/
request_schema_check and request_schema_check_v2.

All eight development/integration_v1 cells failed before an actual suite start
because nested Windows paths exceeded the usable path length. Scientific run
identity is now stored in the grid and summaries, with short rNNN folders and
flat UUID service attempt folders. The earlier service source is preserved in
service/history, and all eight cells were rerun in fresh integration_v2. The
second grid has eight completed technical checks and retains all valid task
failures. No original IASC client, source snapshot or S1--S8 result was edited.

Before final integration, workflow setup was made exception-safe and drain
retries were aligned to their originally scheduled due time. Unexpected client,
binding or recovery exceptions are labelled unclassified_workflow_failure,
not automatically classified as environment failure. The final frozen source
is archived separately; unretained intermediate root-script bytes are not
claimed to have been recovered.

The first job in integration_v2 used about 1.938 seconds of launcher wall time,
versus about 0.25 seconds for subsequent jobs; its supervised test used only
about 0.003 seconds. The difference demonstrates sensitivity to environment
startup overhead. There is no formal warm-up and no deadline retuning. The
formal grid counterbalances arm, policy and condition position, and records
all launch costs. One host and one trajectory per cell do not support a
general runtime or implementation-superiority inference.

Input construction, client initialization and service readiness precede the
trajectory clock. The timed window includes issuance, arm, transport, actual
verification launcher/suite work and result reconciliation. A near-deadline
operation can cross the deadline; this is a timely-result metric, not a hard
physical-start or execution-stop guarantee. Stop snapshots are observed
checkpoints that may occur before or after D. Pending drain results do not
increase timely completion.
