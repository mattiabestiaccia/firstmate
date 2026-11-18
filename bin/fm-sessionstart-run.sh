#!/usr/bin/env bash
# Session-open entry point for harnesses that RUN the digest instead of asking
# the agent to. It is the one command those harnesses' session-open adapters
# invoke, and it decides, from the session-open source, whether this open needs
# the full digest, a context re-emit, or nothing at all.
#
# Why running beats nudging: bin/fm-sessionstart-nudge.sh can only ASK the agent
# to take the helm, and an agent can defer that, including when a first-command
# skill has its own read-only path. When the native adapter injects this
# command's stdout into model context, running the digest here removes that
# discretion - the helm is taken before the model's first turn, whatever the
# first turn is.
#
# Usage: fm-sessionstart-run.sh [--source <source>] [--pi-prerequisite]
#   --source  The harness's own session-open source. When omitted, the source is
#             read from a Claude/Codex-shaped JSON hook payload on stdin
#             (the `source` field). An unreadable or unrecognized source is
#             treated as `startup`, because taking the helm redundantly is
#             cheap and idempotent while not taking it is the whole bug.
#   --pi-prerequisite
#             Internal Pi extension mode. An intentional gate/scope stand-down
#             exits 3 so provider preflight can distinguish it from an eligible
#             native attempt that settled without output. Every ordinary hook
#             invocation retains the always-zero compatibility contract below.
#
# Source routing (see docs/sessionstart-nudge.md for the per-harness names):
#   startup, new            full digest - this process has not taken the helm
#   clear, compact          `--reemit` digest only when this lock owner recorded
#                           a completed full startup; otherwise a full digest,
#                           so a startup killed mid-sweep is finished first
#   resume, reload, fork    silent when the lock holder is this process or a
#                           near ancestor (fm_session_lock_in_ancestry, the
#                           nudge wrapper's own check), because prior context
#                           is restored; otherwise a full digest, because a new
#                           process resumed an old session and has not taken the
#                           helm. The hook runs it rather than nudging: an agent
#                           command can be unable to see its harness in its own
#                           ancestry (a sandbox that hides other processes), so
#                           only the hook can take the lock for it.
#
# Two Claude-specific refinements (docs/sessionstart-nudge.md "Background
# copies" and "Resume wake" own the policy):
#   - Every full digest first asks fm_harness_ancestry_bg_spare_pid whether
#     this hook runs inside a Claude Code background copy (`claude bg-spare`).
#     Such a copy that does not already own the lock prints a BACKGROUND COPY
#     notice instead of the digest and never takes the lock.
#   - resume, reload, and fork buffer their output. When the session then owns
#     the lock under a trusted Claude session id, the home needs supervision,
#     state/.afk is absent, and jq is available, the wrapper writes a `watcher`
#     operational-input record and prints Claude's SessionStart JSON instead:
#     the digest, if any, as additionalContext and the record's doorbell as
#     initialUserMessage, so the resumed session takes a turn, drains, and its
#     Stop-owned auto-arm arms without waiting for the captain. Any failure on
#     that path prints the buffered digest unchanged.
#
# Every ordinary transport path exits 0, exactly like the nudge wrapper: a
# Claude SessionStart exit 2 blocks session initialization, so a failed session
# start must reach the agent as digest text it can act on, never as a refusal to
# open the session. The internal Pi prerequisite's silent exit 3 never reaches a
# harness hook; it only distinguishes intentional ineligibility before provider
# preflight. A lock another live session holds and a truncated digest are
# reported inside the digest, while broken GitHub auth arrives through the
# deferred network result inline or as a wake, for exactly that reason.
# A fresh clone has no gitignored state dir yet; a root that otherwise
# qualifies as primary gets one created here before the scope check runs, so
# the first session takes the helm without a manual `mkdir state`.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FM_ROOT="${FM_ROOT_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FM_HOME="${FM_HOME:-${FM_ROOT_OVERRIDE:-$FM_ROOT}}"
STATE="${FM_STATE_OVERRIDE:-$FM_HOME/state}"
COMPLETION_FILE="$STATE/.session-start-complete"

# shellcheck source=bin/fm-gate-refuse-lib.sh
. "$SCRIPT_DIR/fm-gate-refuse-lib.sh"
# shellcheck source=bin/fm-primary-scope-lib.sh
. "$SCRIPT_DIR/fm-primary-scope-lib.sh"
# shellcheck source=bin/fm-session-lock-lib.sh
. "$SCRIPT_DIR/fm-session-lock-lib.sh"
# shellcheck source=bin/fm-hook-host-lib.sh
. "$SCRIPT_DIR/fm-hook-host-lib.sh"
# shellcheck source=bin/fm-supervision-lib.sh
. "$SCRIPT_DIR/fm-supervision-lib.sh"
# shellcheck source=bin/fm-operational-input.sh
. "$SCRIPT_DIR/fm-operational-input.sh"

SOURCE=
PI_PREREQUISITE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --source)
      SOURCE=${2:-}
      # A bare trailing --source leaves the source empty rather than aborting,
      # so a malformed call still falls through to taking the helm.
      if [ $# -ge 2 ]; then shift 2; else shift; fi
      ;;
    --source=*) SOURCE=${1#--source=}; shift ;;
    --pi-prerequisite) PI_PREREQUISITE=1; shift ;;
    *) shift ;;
  esac
done

stand_down() {
  if [ "$PI_PREREQUISITE" = 1 ]; then
    exit 3
  fi
  exit 0
}

# The same two eligibility owners the nudge wrapper uses, so a no-mistakes gate
# agent and an unmarked task worktree can never run a session start for a home
# they do not own. Pi's preflight-only status preserves that intentional silence
# without mistaking it for a failed eligible attempt that needs the manual nudge.
fm_is_gate_agent "$FM_ROOT" && stand_down
if [ ! -d "$STATE" ] && fm_primary_root_matches "$FM_ROOT"; then
  if ! MKDIR_ERR=$(mkdir -p "$STATE" 2>&1); then
    printf 'fm-sessionstart-run: startup could not create the state directory %s: %s\n' \
      "$STATE" "${MKDIR_ERR##*: }" >&2
    stand_down
  fi
fi
fm_primary_scope_matches "$FM_ROOT" "$STATE" || stand_down

session_start_completed() {
  local lock_pid completion_pid
  [ -f "$STATE/.lock" ] && [ ! -L "$STATE/.lock" ] || return 1
  [ -f "$COMPLETION_FILE" ] && [ ! -L "$COMPLETION_FILE" ] || return 1
  fm_session_lock_owned_by_self "$STATE" || return 1
  lock_pid=$(cat "$STATE/.lock" 2>/dev/null) || return 1
  completion_pid=$(cat "$COMPLETION_FILE" 2>/dev/null) || return 1
  fm_session_pid_valid "$lock_pid" || return 1
  [ "$completion_pid" = "$lock_pid" ]
}

if [ -z "$SOURCE" ] && [ ! -t 0 ]; then
  # Claude and Codex both deliver a JSON SessionStart payload on stdin whose
  # `source` field carries startup|resume|clear|compact. Parsed without jq so a
  # host missing it still gets correct routing rather than silent full runs.
  # A terminal stdin is skipped outright: a hook always pipes its payload, and
  # an operator running this by hand must not be left waiting on a read.
  # Splitting on the quote character finds the FIRST "source" key and its value
  # without depending on greedy-regex luck, and it cannot mistake a string VALUE
  # of "source" for the key, because only a key is followed by a bare colon.
  PAYLOAD=$(cat 2>/dev/null || true)
  # Cursor loads the tracked Claude settings as well as its own registration,
  # so a Cursor-delivered payload here is the duplicate: bin/fm-sessionstart-
  # cursor.sh already owns that session open and calls this wrapper with an
  # explicit --source and no payload. Running twice would take the helm twice
  # and repeat every startup sweep.
  if fm_hook_payload_is_foreign_host "$PAYLOAD"; then
    exit 0
  fi
  SOURCE=$(printf '%s' "$PAYLOAD" | awk '
    BEGIN { RS = "\"" }
    seen == 2 { print; exit }
    seen == 1 && $0 ~ /^[[:space:]]*:[[:space:]]*$/ { seen = 2; next }
    seen == 1 { seen = 0 }
    $0 == "source" { seen = 1 }
  ')
fi

# A Claude Code background copy never takes a fleet lock it does not already
# own; it says so instead, so its model leaves the fleet to the foreground
# session that opens or resumes the same conversation.
background_copy_stands_down() {
  local spare
  spare=$(fm_harness_ancestry_bg_spare_pid) || return 1
  fm_session_lock_owned_by_self "$STATE" && return 1
  cat <<EOF
================================================================================
SESSION START - BACKGROUND COPY - $FM_HOME
================================================================================
This Claude Code process is a background copy of a conversation (claude bg-spare, pid $spare), such as the one the exit dialog's "Move to background and exit" leaves running.
It did not take this home's fleet lock, so the captain's own session takes the helm when it opens or resumes.
Treat this session as read-only for the fleet: do not run bin/fm-session-start.sh, spawn, steer, merge, drain the wake queue, or change any task.
Only if the captain explicitly makes this background session the first mate, run bin/fm-session-start.sh here once; it still refuses while another live session holds the lock.
EOF
}

run_full_digest() {
  background_copy_stands_down && return 0
  "$SCRIPT_DIR/fm-session-start.sh" --source "$SOURCE" || true
}

RESUME_WAKE_BODY='check: session-resume - this session was resumed while the home needs supervision, and it has no supervision cycle of its own yet, so wakes delivered to the previous process never reach it. If the session-start digest in your context is only a preview saved to a file, read that file first. Then run bin/fm-wake-drain.sh, handle its queued work, run its exact WAKE_ACK_REQUIRED command, and end the turn normally so the Stop-owned auto-arm arms supervision for this session. This is automatic supervision, not a captain message.'

# Print the doorbell that wakes this resumed Claude session, or return 1 when
# no wake is owed.
resume_wake_doorbell() {
  local doorbell
  [ "$PI_PREREQUISITE" = 0 ] || return 1
  command -v jq >/dev/null 2>&1 || return 1
  [ ! -e "$STATE/.afk" ] || return 1
  fm_session_lock_trusted_session_id >/dev/null || return 1
  fm_session_lock_owned_by_self "$STATE" || return 1
  fm_supervision_needed "$STATE" || return 1
  fm_operational_record_write "$STATE" watcher "$RESUME_WAKE_BODY" doorbell || return 1
  printf '%s' "$doorbell"
}

resume_open() {
  local out doorbell
  if ! out=$(mktemp "${TMPDIR:-/tmp}/fm-sessionstart-run.XXXXXX" 2>/dev/null); then
    fm_session_lock_in_ancestry "$STATE" || run_full_digest
    return 0
  fi
  fm_session_lock_in_ancestry "$STATE" || run_full_digest > "$out"
  if doorbell=$(resume_wake_doorbell) \
    && jq -n --rawfile context "$out" --arg message "$doorbell" '{hookSpecificOutput: ({hookEventName: "SessionStart", initialUserMessage: $message} + (if $context == "" then {} else {additionalContext: $context} end))}' 2>/dev/null; then
    :
  else
    cat "$out"
  fi
  rm -f "$out"
}

case "$SOURCE" in
  resume|reload|fork)
    resume_open
    ;;
  clear|compact)
    if session_start_completed; then
      "$SCRIPT_DIR/fm-session-start.sh" --reemit --source "$SOURCE" || true
    else
      run_full_digest
    fi
    ;;
  *)
    run_full_digest
    ;;
esac
exit 0
