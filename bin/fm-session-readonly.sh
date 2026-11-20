#!/usr/bin/env bash
# Report whether the current session runs read-only on this firstmate home.
#
# A session is read-only when it does not own the home's session lock
# (state/.lock). Ownership is decided only by fm_session_lock_owned_by_self in
# bin/fm-session-lock-lib.sh; this script never re-derives it. It exists so a
# fast, side-effect-free caller such as bin/fm-statusline.sh can ask the
# question without acquiring the lock the way bin/fm-lock.sh does.
#
# Verdicts and exit codes:
#   0  owned        this session owns the lock.
#   1  read-only    the lock is held by another live session, or ownership is
#                   uncertain: the lock is missing, unreadable, or malformed,
#                   this process's harness ancestry cannot be resolved, or the
#                   recorded owner is alive but cannot be verified. Uncertainty
#                   counts as read-only on purpose.
#   3  recoverable  the recorded owner pid is dead (fm_session_lock_inspect
#                   reports the lock stale). The session is not read-only:
#                   bin/fm-lock.sh reclaims such a lock on its next acquisition.
#   2  usage error.
#
# Output is one machine-oriented debug line on stdout, for example
#   verdict=read-only reason=foreign-live lock_pid=4242 state_dir=/home/state
# and is not meant as end-user prose. Pass --quiet to print nothing.
#
# Read-only by construction: it never writes, never touches state/.lock or
# state/.lock-session, makes no network call, and never runs gh. FM_HOME
# selects the home (default: the FirstMate code root, FM_CODE). FM_CODE
# defaults to the repository this script lives in, resolved through symlinks,
# and can be overridden, for example by tests.
#
# Usage: fm-session-readonly.sh [--quiet]
#        fm-session-readonly.sh --help
set -u

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
FM_CODE="${FM_CODE:-$(dirname "$SCRIPT_DIR")}"

usage() {
  sed -n '2,/^set -u$/{/^set -u$/d;s/^# \{0,1\}//;p;}' "${BASH_SOURCE[0]}"
}

QUIET=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    -q | --quiet) QUIET=1; shift ;;
    *) printf 'fm-session-readonly: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

FM_HOME="${FM_HOME:-$FM_CODE}"
STATE="$FM_HOME/state"

# shellcheck source=bin/fm-session-lock-lib.sh
. "$FM_CODE/bin/fm-session-lock-lib.sh"

report() {  # <verdict> <reason> <lock_pid> <exit>
  [ "$QUIET" -eq 1 ] || printf 'verdict=%s reason=%s lock_pid=%s state_dir=%s\n' "$1" "$2" "${3:--}" "$STATE"
  exit "$4"
}

if fm_session_lock_owned_by_self "$STATE"; then
  report owned self "$(head -n 1 "$STATE/.lock" 2>/dev/null)" 0
fi

fm_session_lock_inspect "$STATE"
lock_pid=$FM_LOCK_INSPECT_PID
case "$FM_LOCK_INSPECT_STATE" in
  stale) report recoverable dead-owner "$lock_pid" 3 ;;
  free) report read-only missing "" 1 ;;
  unreadable) report read-only unreadable "" 1 ;;
esac
fm_session_pid_valid "$lock_pid" || report read-only malformed "$lock_pid" 1
fm_harness_ancestry_pids >/dev/null || report read-only ancestry-unresolved "$lock_pid" 1
if fm_session_lock_foreign_owner_live "$STATE"; then
  report read-only foreign-live "$lock_pid" 1
fi
report read-only unverifiable-owner "$lock_pid" 1
