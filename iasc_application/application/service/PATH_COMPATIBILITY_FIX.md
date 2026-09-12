# Development correction: short Windows output paths

The root's retained `development/integration_v1` failed before actual job execution while creating deeply nested operation/attempt output directories under descriptive run folders. The new service uses a single fresh `service_runs/a-<UUID>` directory for each attempt. Operation identity remains in database rows, the bound job JSON and trusted events; directory spelling is not an identity mechanism. The root separately shortens grid folder names.

This is a path compatibility correction. HTTP, job binding, execution, caching, transaction and receipt semantics are unchanged. No evaluation job was executed for this correction.

- Prior service SHA-256: `a51744d904ac7c4d06b3d1588bd1fdb99ac558e69d7ba297da04e5236b022bcd`, preserved in `history/verification_service_v1.py` with the original `dev_qa_01` records.
- Corrected service SHA-256: `4ebd35083fafaadad865ef578c9273044b4bdb0c58d1b57b0fab1a6a9f61ca81`.
- `dev_qa_02/QA_REPORT.json`: all eight separate-process toy checks passed; four completed toy results, one retained infrastructure abort, five runner invocations, zero evaluation candidates.
- `dev_qa_02/catalog_startup/CATALOG_STARTUP.json`: actual frozen-catalog startup and health passed, with zero effects, job results or aborts. Catalog SHA-256 `bbd28484d9f10143b1d5db9d80740996b49a43987e5f737ce659114a3b87a9c8`; runner bundle SHA-256 `e05cebc18c2dab444215fb826377edb0480db72e2bf33ed776afbbc2a1d7f150`.
