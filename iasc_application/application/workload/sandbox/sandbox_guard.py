"""Trusted Linux seccomp setup; no candidate loading or execution here.

The trusted supervisor may install allow_fork=True. Each per-test child must
then install the default strict profile before any candidate code is loaded.
Python exec remains usable; OS exec/network remain denied in both profiles.
"""
import ctypes
import errno

FORK_SYSCALLS = ('fork', 'vfork', 'clone', 'clone3')
CHILD_SIGNAL_SYSCALLS = ('kill', 'tkill', 'tgkill', 'pidfd_send_signal')
DENIED_SYSCALLS = (
    'execve', 'execveat',
    'socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
    'sendto', 'sendmsg', 'sendmmsg', 'recvfrom', 'recvmsg', 'recvmmsg',
    'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd',
    'mount', 'umount2', 'pivot_root', 'move_mount', 'open_tree', 'fsopen',
    'fsconfig', 'fsmount', 'fspick', 'mount_setattr', 'unshare', 'setns',
    'bpf', 'perf_event_open', 'userfaultfd', 'keyctl', 'add_key', 'request_key',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register',
)


def install_candidate_filter(allow_fork=False):
    if type(allow_fork) is not bool:
        raise TypeError('allow_fork must be bool')
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('seccomp_init failed; refusing to start worker')
    denied, unavailable = [], []
    try:
        names = DENIED_SYSCALLS if allow_fork else DENIED_SYSCALLS + FORK_SYSCALLS + CHILD_SIGNAL_SYSCALLS
        for name in names:
            number = lib.seccomp_syscall_resolve_name(name.encode('ascii'))
            if number < 0:
                unavailable.append(name)
                continue
            rc = lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0)
            if rc != 0:
                raise RuntimeError(f'seccomp_rule_add({name}) failed: {rc}')
            denied.append(name)
        required = {'execve', 'socket', 'unshare', 'setns'}
        if not allow_fork:
            required.update({'fork', 'vfork', 'clone', 'kill', 'tgkill'})
        if not required.issubset(denied):
            raise RuntimeError('Required syscall names unavailable; refusing worker')
        rc = lib.seccomp_load(context)
        if rc != 0:
            raise RuntimeError(f'seccomp_load failed: {rc}; refusing worker')
    finally:
        lib.seccomp_release(context)
    return {'allow_fork': allow_fork, 'denied_syscalls': denied, 'unavailable_syscalls': unavailable}
