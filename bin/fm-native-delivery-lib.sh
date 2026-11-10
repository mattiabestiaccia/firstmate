#!/usr/bin/env bash
# Durable, at-most-once submission of a native Claude launch brief.
# Callers hold the task spawn lock (and control lock for continuation).
# shellcheck source=bin/fm-operational-input.sh
. "$(dirname "${BASH_SOURCE[0]}")/fm-operational-input.sh"

fm_native_hash() {
  [ -f "$1" ] && [ ! -L "$1" ] || return 1
  git hash-object -- "$1"
}

fm_native_prepare() { # state id meta brief doorbell
  local state=$1 id=$2 meta=$3 brief=$4 doorbell=$5 record kind journal tmp
  journal="$state/$id.native-delivery.json"
  fm_operational_doorbell_path "$doorbell" record || return 1
  fm_operational_doorbell_kind "$doorbell" "$state" kind || return 1
  [ "$kind" = launch-brief ] || return 1
  # A new generation may replace a completed/abandoned journal only while the
  # normal spawn transaction holds its task lock; archive rather than discard.
  if [ -e "$journal" ] || [ -L "$journal" ]; then
    [ ! -L "$journal" ] || return 1
    mv "$journal" "$journal.previous" || return 1
  fi
  tmp=$(umask 077; mktemp "$state/.native-delivery.XXXXXX") || return 1
  jq -n --arg meta "$(fm_native_hash "$meta")" --arg brief "$(fm_native_hash "$brief")" \
    --arg record_hash "$(fm_native_hash "$record")" --arg record "$record" \
    --arg doorbell "$doorbell" --arg gen "$(fm_meta_get "$meta" busy_gen)" \
    '{version:1,state:"not-sent",meta_hash:$meta,brief_hash:$brief,record_hash:$record_hash,record:$record,doorbell:$doorbell,gen:$gen}' > "$tmp" || return 1
  jq -e '[.meta_hash,.brief_hash,.record_hash,.gen] | all(length > 0)' "$tmp" >/dev/null || return 1
  mv "$tmp" "$journal"
}

fm_native_transition() { # journal state; fsync BEFORE any input is sent
  python3 - "$1" "$2" <<'PY'
import json,os,sys,tempfile
p,state=sys.argv[1:];d=json.load(open(p));d['state']=state
fd,tmp=tempfile.mkstemp(prefix='.native-delivery-',dir=os.path.dirname(p))
with os.fdopen(fd,'w') as f:
    json.dump(d,f);f.write('\n');f.flush();os.fsync(f.fileno())
os.replace(tmp,p)
fd=os.open(os.path.dirname(p),os.O_RDONLY)
try: os.fsync(fd)
finally: os.close(fd)
PY
}

fm_native_deliver() { # state id meta brief home backend target label
  local state=$1 id=$2 meta=$3 brief=$4 home=$5 backend=$6 target=$7 label=$8
  local journal="$1/$2.native-delivery.json" pending="$1/$2.native-trust-pending"
  local stage doorbell record kind gen result actual
  [ "$backend" = hc ] && [ "$(fm_meta_get "$meta" harness)" = claude ] || return 1
  [ -f "$journal" ] && [ ! -L "$journal" ] || {
    echo 'error: no durable native delivery reference; legacy pending launch cannot be continued' >&2; return 1;
  }
  [ ! -e "$state/$id.paused" ] && [ ! -L "$state/$id.paused" ] || return 1
  stage=$(jq -er 'select(.version == 1) | .state' "$journal") || return 1
  [ "$stage" = not-sent ] || {
    if [ "$stage" = delivered ]; then
      [ "$(fm_native_hash "$meta")" = "$(jq -r .meta_hash "$journal")" ] || return 1
      [ "$(fm_native_hash "$brief")" = "$(jq -r .brief_hash "$journal")" ] || return 1
      # A crash after the durable receipt but before cleanup is recoverable
      # without sending anything again.
      [ ! -L "$pending" ] || return 1
      rm -f "$pending" || return 1
      echo 'native brief already submitted; no input sent'
      return 0
    fi
    echo 'error: native delivery ambiguous; automatic retry refused' >&2; return 1;
  }
  [ -f "$pending" ] && [ ! -L "$pending" ] && [ "$(cat "$pending")" = not-sent ] || return 1
  [ "$(fm_native_hash "$meta")" = "$(jq -r .meta_hash "$journal")" ] || return 1
  [ "$(fm_native_hash "$brief")" = "$(jq -r .brief_hash "$journal")" ] || return 1
  doorbell=$(jq -er .doorbell "$journal") || return 1
  record=$(jq -er .record "$journal") || return 1
  fm_operational_doorbell_path "$doorbell" actual || return 1
  [ "$actual" = "$record" ] || return 1
  [ "$(fm_native_hash "$record")" = "$(jq -r .record_hash "$journal")" ] || return 1
  fm_operational_doorbell_kind "$doorbell" "$state" kind || return 1
  [ "$kind" = launch-brief ] || return 1
  fm_task_handoff_verify "$meta" "$id" "$home" || return 1
  fm_task_wiring_verify "$meta" claude "$(fm_meta_get "$meta" worktree)" "$state" "$id" "$(fm_meta_get "$meta" kind)" || return 1
  gen=$(jq -er .gen "$journal") || return 1
  [ "$gen" = "$(fm_meta_get "$meta" busy_gen)" ] || return 1
  [ -f "$state/$id.claude-native-ready" ] && [ ! -L "$state/$id.claude-native-ready" ] || return 1
  [ "$(cat "$state/$id.claude-native-ready")" = "$gen" ] || return 1
  [ "$(fm_backend_agent_state "$backend" "$target")" = alive ] || return 1
  [ "$(fm_backend_composer_state "$backend" "$target" "$label")" = empty ] || return 1
  # Crash or any failure after this durable claim is ambiguous, never retryable.
  fm_native_transition "$journal" sending || return 1
  printf '%s\n' ambiguous > "$pending" || return 1
  result=$(fm_backend_send_text_submit "$backend" "$target" "$doorbell" 0 0.4 0 "$label") || result=unknown
  [ "$result" = empty ] || { echo 'error: native submission unconfirmed; no automatic retry' >&2; return 1; }
  fm_native_transition "$journal" delivered || return 1
  rm -f "$pending" || return 1
  echo 'native brief submitted once; worker result still requires verification'
}
