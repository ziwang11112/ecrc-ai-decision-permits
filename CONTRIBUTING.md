# Contributing

Thank you for helping improve ECRC. Use GitHub Issues for reproducible bugs,
documentation corrections and questions about the public artifacts.

## Report a problem

Include the release or commit, operating system, Python version, exact command,
expected result and a short error excerpt. For numerical discrepancies, identify
the study, file and row or metric. Remove credentials and private provider traffic
before posting logs.

## Propose a change

Keep changes focused and explain their purpose and verification in the pull
request. Run the relevant offline command from [REPRODUCIBILITY.md](REPRODUCIBILITY.md).
For saved-result checks, use `revision_results/verify.py` and
`scripts/verify_current_results.py`. Actor-loop changes also need the documented
offline runtime tests. Tests should use injected model responses and inert runners.

## Preserve published evidence

Retained scientific records and frozen source files identify completed studies.
Keep corrections in a new, documented version with a mapping to the original
records. New experiments belong in new output directories and need their own
protocol and execution environment.

Repository files are covered by `MANIFEST.json` and `SHA256SUMS.txt`; some packages
also have their own manifests. Maintainers regenerate affected inventories when
preparing a release. Review a numerical or code change before updating its hashes.

Contributions to project software use the existing [MIT License](LICENSE).
Preserve third-party notices described in [LICENSES.md](LICENSES.md).
