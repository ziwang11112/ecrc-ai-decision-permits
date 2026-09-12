# Ordinary issuance development log

These events precede source freeze and the formal experiment. They are excluded
from the planned 36-run denominator.

The first `ordinary_e2e_checks.py` run reached all contract assertions, then
failed when Python removed its temporary SQLite files on Windows:

```
PermissionError: [WinError 32] The process cannot access the file because it is
being used by another process: .../ordinary-e2e-dev-6gf40q_s/gate-available_at.sqlite
```

Cause: the copied delivery adapter constructor uses `with connection`; SQLite's
ordinary context manager commits/rolls back but does not close its connection.
The new `ordinary_e2e.py` adapter now provides its own connection subclass whose
context-manager exit closes that connection. Other methods already explicitly
close their connections. The legacy snapshot is unchanged. A clean rerun is
recorded separately in `ordinary_e2e_dev_checks.json`.
