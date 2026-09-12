"""Trusted entry: install seccomp, then start one already-mounted worker.

No candidate is included in this file. The host controller must never import or
execute candidate code itself. A worker may use Python exec inside this sandbox.
"""
import os
import ctypes
import runpy
import sys

if os.getuid() == 0:
    raise RuntimeError('Refusing root worker')
if len(sys.argv) < 2 or sys.argv[1] != '/runner/worker.py':
    raise RuntimeError('Only the explicitly mounted worker is accepted')
# This is the trusted supervisor. It may fork one fresh case child at a time.
# The worker must set NPROC=64 and install the strict filter in every child
# before loading candidate source. Do not impose the shared-UID limit here.
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE = 4
    raise OSError(ctypes.get_errno(), 'PR_SET_DUMPABLE failed')
if libc.prctl(3, 0, 0, 0, 0) != 0:  # PR_GET_DUMPABLE = 3
    raise RuntimeError('Trusted supervisor is still dumpable')
guard = runpy.run_path('/runner/sandbox_guard.py')
guard['install_candidate_filter'](allow_fork=True)
sys.argv = ['/runner/worker.py', *sys.argv[2:]]
runpy.run_path('/runner/worker.py', run_name='__main__')
