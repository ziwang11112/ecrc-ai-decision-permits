# Preserved sandbox source and explicit dependency configuration

The candidate runner never imports candidate source in the host interpreter.
Its Linux launcher uses fresh bubblewrap namespaces, a cleared sandbox
environment, read-only system/dependency/input mounts, an isolated temporary
directory, resource limits, and seccomp filters. Supervisor events establish
actual starts; absence of a valid event after a launcher failure can remain
unknown. Unknown starts are not converted to zero.

The historical source depended on author-local binary and package directories.
Only those three launcher paths have been replaced with required configuration:

| Environment variable | Required value |
| --- | --- |
| `ECRC_BWRAP_BIN` | Absolute Linux path to the bubblewrap executable |
| `ECRC_SCIENCE_PACKAGES` | Absolute Linux path containing the scientific package inventory below |
| `ECRC_PYTEST_PACKAGES` | Absolute Linux path containing the pytest inventory below |

The pinned bubblewrap SHA-256 remains
`52231e1caf55bcbc667b269f49c63599a6f7db4767ae6a039580d0ff853db712`.
That binary is not bundled. A different binary fails the launcher hash check;
changing the pin is a new execution profile requiring independent validation.
The package directory inventory is exact, including distribution metadata
directory names. Dependencies are not installed by this release.

Scientific inventory: `numpy==2.3.5` (including `numpy.libs`), `sympy==1.14.0`,
`mpmath==1.3.0`, `python-dateutil==2.9.0.post0`, `six==1.17.0`,
`packaging==26.3`. Pytest inventory: `pytest==8.3.5`, `pluggy==1.5.0`,
`iniconfig==2.1.0`, plus the accompanying `_pytest` and `py.py`. The launcher
lists every mounted path. These dependencies differ from the repository's
host analysis environment and should not be replaced by its root requirements.

Linux Python inherits the three variables from the caller. Windows Python
starts a noninteractive WSL process and does not explicitly forward them:
they must be made available in that WSL process, for example by an appropriately
configured `WSLENV`, or execution must start with Linux Python in the configured
shell. Setting only Windows environment variables is insufficient. Windows
drive paths and Linux paths must not be interchanged in these values.

The preserved job runner sets 15-second launcher wall time, 10-second CPU,
512 MiB address space and 1 MiB per-file limits; the fixed-suite worker receives
a 3-second suite timeout. Address-space limits are not an RSS/cgroup guarantee.
The sandbox exposes the host `/usr` read-only and selected dependency files,
so exact dependency/system identity still requires an independently frozen
environment. This source distribution is neither a container image nor a
security certification. The same official tests are rerun after the workflow;
they are not held-out tests or an oracle against deliberately harness-aware
programs. No sandbox execution was performed as part of this release check.
