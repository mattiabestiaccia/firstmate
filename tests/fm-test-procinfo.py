#!/usr/bin/env python3
"""fm-test-procinfo.py - ps-free process metadata for tests/lib.sh on macOS.

/bin/ps is setuid and cannot execute inside a Seatbelt sandbox, so the test
library reads the few per-process facts it needs from libproc instead:

  fm-test-procinfo.py ppid <pid>      parent pid
  fm-test-procinfo.py state <pid>     first letter of the run state (R S T Z I)
  fm-test-procinfo.py identity <pid>  darwin-start=<sec>.<usec> comm=<p_comm>

Only proc_pidinfo(PROC_PIDTBSDINFO) is called. Its record carries no argv and
no environment, and this helper must never read either: KERN_PROCARGS and
KERN_PROCARGS2 return a process's environment and stay out of this file.
The identity is therefore weaker than bin/fm-wake-lib.sh's fm_pid_identity,
which includes the full command line, and it is used only for test fixture
ownership, never for a production record.

Only processes of the caller's own uid are reported. Exit status:
  0  the fact was printed
  1  no such process (ESRCH), including a zombie libproc no longer reports
  2  not observable: another uid, permission denied, non-macOS host, short
     record, or a usage error; the caller falls back to ps
"""
import ctypes
import os
import struct
import sys

PROC_PIDTBSDINFO = 3
BSDINFO_SIZE = 136  # sizeof(struct proc_bsdinfo)
ESRCH = 3
STATES = {1: "I", 2: "R", 3: "S", 4: "T", 5: "Z"}


def bsdinfo(pid):
    """Return (status, ppid, uid, comm, start_sec, start_usec) or an exit code."""
    if sys.platform != "darwin":
        return 2
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError:
        return 2
    buf = ctypes.create_string_buffer(BSDINFO_SIZE)
    ctypes.set_errno(0)
    got = libproc.proc_pidinfo(pid, PROC_PIDTBSDINFO, ctypes.c_uint64(0),
                               buf, BSDINFO_SIZE)
    if got != BSDINFO_SIZE:
        return 1 if ctypes.get_errno() == ESRCH else 2
    raw = buf.raw
    # pbi_flags, pbi_status, pbi_xstatus, pbi_pid, pbi_ppid, pbi_uid
    _flags, status, _xstatus, rec_pid, ppid, uid = struct.unpack_from("<6I", raw, 0)
    if rec_pid != pid:
        return 2
    comm = raw[48:64].split(b"\0", 1)[0].decode("utf-8", "replace")
    comm = "".join(c if c.isprintable() else "?" for c in comm)
    start_sec, start_usec = struct.unpack_from("<QQ", raw, 120)
    return status, ppid, uid, comm, start_sec, start_usec


def main(argv):
    if len(argv) != 3 or argv[1] not in ("ppid", "state", "identity"):
        print("usage: fm-test-procinfo.py ppid|state|identity <pid>", file=sys.stderr)
        return 2
    if not argv[2].isdigit() or int(argv[2]) <= 0:
        return 2
    info = bsdinfo(int(argv[2]))
    if isinstance(info, int):
        return info
    status, ppid, uid, comm, start_sec, start_usec = info
    if uid != os.getuid():
        return 2
    if argv[1] == "ppid":
        print(ppid)
    elif argv[1] == "state":
        letter = STATES.get(status)
        if letter is None:
            return 2
        print(letter)
    else:
        if not comm or start_sec == 0:
            return 2
        print("darwin-start=%d.%06d comm=%s" % (start_sec, start_usec, comm))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
