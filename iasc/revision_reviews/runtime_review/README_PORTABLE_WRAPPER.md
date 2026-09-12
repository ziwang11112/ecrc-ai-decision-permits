# Portable supplemental wrapper QA (R2)

The historical `review_atomic_wrapper.py` and `WRAPPER_QA_RESULT.json` are unchanged.
Use `review_atomic_wrapper_portable.py` for the packaged layout: it resolves
`end_to_end/` from the package root, checks that layout, and writes distinct new
report/evidence names. `WRAPPER_QA_PORTABLE.diff` shows the path/output-only edits.

The new entry point was executed in an independently copied directory containing
only the 34 frozen source/input/protocol files, `CODE_FREEZE.json`, and this entry
point. All 10 supplemental cases passed: five per arm (three BaseException
rollback/recovery checkpoints, cleanup before competing arm, and arm before expiry
cleanup). These cases use no HTTP or process kills and do not add to the 36 formal
S8 runs. The 34 frozen file hashes matched before and after execution; all six
historical runtime-review files also retained their hashes.

Files:

- `WRAPPER_QA_PORTABLE_RESULT.json`: complete new ten-case output.
- `wrapper_qa_portable/`: the ten databases from this clean execution (and any
  SQLite sidecars retained on process exit).
- `PORTABLE_WRAPPER_VERIFICATION.json`: source, history and evidence hashes,
  exact scope, and verification checks.
- `PORTABLE_WRAPPER_EXECUTION.log`: command context, exit code, stdout and stderr.

To repeat the supplemental checks, create a **fresh destination** with this layout:

```text
fresh_bundle/
  end_to_end/                         # copy the 34 paths in CODE_FREEZE.json
    CODE_FREEZE.json                  # also copy the freeze manifest
  revision_reviews/runtime_review/
    review_atomic_wrapper_portable.py # copy only this entry point
```

From `fresh_bundle`, run:

```console
python -B revision_reviews/runtime_review/review_atomic_wrapper_portable.py
```

The entry point creates `WRAPPER_QA_PORTABLE_RESULT.json` and
`wrapper_qa_portable/` next to itself. It refuses to overwrite prior portable QA
output. Preserve this archive as evidence and use a new directory for each repeat.
No original workspace path or historical QA directory is required.
