#!/usr/bin/env bash
# Per-task resource retention, distinct from backlog hold. Configure/revoke only
# with lifecycle writers quiescent: a running operation is not cancelled.
# Caller supplies an already validated exact task id.
fm_task_preserve_guard() { # <config-directory> <task-id> <operation>
  local config=$1 id=$2 operation=$3 root
  root="$config/task-preservation"
  if [ -L "$config" ] || { [ -e "$config" ] && { [ ! -d "$config" ] || [ ! -x "$config" ] || [ ! -r "$config" ]; }; }; then
    echo "error: task preservation configuration is unsafe or unreadable; refusing $operation" >&2
    return 1
  fi
  if [ -L "$root" ] || { [ -e "$root" ] && { [ ! -d "$root" ] || [ ! -x "$root" ] || [ ! -r "$root" ]; }; }; then
    echo "error: task preservation directory is unsafe or unreadable; refusing $operation" >&2
    return 1
  fi
  if [ -e "$root/$id" ] || [ -L "$root/$id" ]; then
    echo "error: task $id is resource-preserved; refusing $operation. Explicit operator revocation is required." >&2
    return 1
  fi
  return 0
}
