#!/usr/bin/env bash
# Task handoff retains Treehouse ownership across a stopped worker.
# A pause marker blocks steering, automatic relaunch and teardown. Only an
# explicit fm-control relaunch --resume-paused consumes it after success.
# Callers provide the existing metadata, Treehouse and lock library functions.
fm_task_lease_holder() {  # <home> <id>
  local home hash
  home=$(cd "$1" && pwd -P) || return 1
  hash=$(printf '%s' "$home" | git hash-object --stdin) || return 1
  printf 'fm-%s-%s\n' "$hash" "$2"
}

fm_task_handoff_verify() {  # <meta> <id> <home>
  local project lock rc=0
  project=$(fm_meta_get "$1" project)
  lock=$(fm_treehouse_project_lock_path "$project") || return 1
  # Spawn already owns this lock through publication; control takes it locally.
  if [ "${SPAWN_TREEHOUSE_PROJECT_LOCK_HELD:-0}" = 1 ]; then
    fm_task_handoff_verify_locked "$@"
    return $?
  fi
  fm_lock_acquire_wait "$lock" || return 1
  fm_task_handoff_verify_locked "$@" || rc=$?
  fm_lock_release "$lock" || return 1
  return "$rc"
}

fm_task_handoff_verify_locked() {  # <meta> <id> <home>
  local meta=$1 id=$2 home=$3 wt project holder lease rows real_home owner_home common
  wt=$(fm_meta_get "$meta" worktree)
  project=$(fm_meta_get "$meta" project)
  holder=$(fm_meta_get "$meta" treehouse_lease_holder)
  lease=$(fm_meta_get "$meta" treehouse_lease_id)
  [ -n "$holder" ] && [ -n "$lease" ] || {
    echo "error: task $id has no recorded durable Treehouse lease; preserve the copy and provision its lease explicitly before handoff" >&2
    return 1
  }
  [ "$holder" = "$(fm_task_lease_holder "$home" "$id")" ] || return 1
  fm_treehouse_pool_slot "$project" "$wt" || return 1
  fm_treehouse_slot_owner_state "$wt" "$id"
  [ "$FM_TREEHOUSE_SLOT_OWNER" = mine ] || return 1
  real_home=$(cd "$home" && pwd -P) || return 1
  owner_home=$(cd "$FM_TREEHOUSE_SLOT_OWNER_HOME" && pwd -P) || return 1
  [ "$real_home" = "$owner_home" ] || return 1
  common=$(cd "$wt" && pwd -P) || return 1
  rows=$(cd "$project" && treehouse status --json) || return 1
  printf '%s' "$rows" | jq -e --arg p "$common" --arg h "$holder" --arg l "$lease" '
    [.[] | select(.path == $p)] | length == 1 and
    (.[0] | .status == "leased" and .lease_holder == $h and .lease_id == $l)' >/dev/null
}

# Fingerprint only the wiring this adapter owns; never overwrite user edits.
fm_task_wiring_hash() {  # <harness> <worktree> <state> <id> <kind>
  local path
  case "$1:$5" in claude:ship|claude:scout|pi:ship|pi:scout|pi-signed:ship|pi-signed:scout) ;; *) return 0 ;; esac
  path=$(fm_control_harness_wiring_paths "$@") || return 1
  [ -n "$path" ] || return 1
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then printf 'absent\n'; return 0; fi
  [ -f "$path" ] && [ ! -L "$path" ] || return 1
  git hash-object -- "$path"
}

fm_task_wiring_verify() {  # <meta> <harness> <worktree> <state> <id> <kind>
  local meta=$1 actual expected
  shift
  actual=$(fm_task_wiring_hash "$@") || return 1
  [ -n "$actual" ] || return 0
  expected=$(fm_meta_get "$meta" handoff_wiring_hash)
  # Older tasks without provenance are never allowed to remove existing wiring.
  [ -n "$expected" ] || expected=absent
  [ "$actual" = "$expected" ] || {
    echo 'error: harness wiring changed or has no ownership fingerprint; preserve and review before handoff' >&2
    return 1
  }
}
