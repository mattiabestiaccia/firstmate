#!/usr/bin/env bash
# Public checkpoint CLI: preserve dirty/index/untracked, refuse drift.
set -eu
# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
TMP_ROOT=$(fm_test_tmproot fm-checkpoint)
fm_git_init_commit "$TMP_ROOT/repo"
printf 'tracked\n' > "$TMP_ROOT/repo/change.txt"
git -C "$TMP_ROOT/repo" add change.txt
git -C "$TMP_ROOT/repo" -c user.name=Test -c user.email=test@example.invalid commit -qm baseline
printf 'staged\n' > "$TMP_ROOT/repo/change.txt"
git -C "$TMP_ROOT/repo" add change.txt
printf 'working\n' >> "$TMP_ROOT/repo/change.txt"
printf 'untracked\n' > "$TMP_ROOT/repo/new.txt"
python3 "$ROOT/bin/fm-task-checkpoint.py" capture "$TMP_ROOT/repo" "$TMP_ROOT/checkpoint.json"
python3 "$ROOT/bin/fm-task-checkpoint.py" verify "$TMP_ROOT/repo" "$TMP_ROOT/checkpoint.json"
printf 'drift\n' >> "$TMP_ROOT/repo/new.txt"
if python3 "$ROOT/bin/fm-task-checkpoint.py" verify "$TMP_ROOT/repo" "$TMP_ROOT/checkpoint.json" 2>/dev/null; then fail 'untracked drift accepted'; fi
[ "$(cat "$TMP_ROOT/repo/change.txt")" = $'staged\nworking' ] || fail 'checkpoint changed work'
[ "$(git -C "$TMP_ROOT/repo" show :change.txt)" = staged ] || fail 'checkpoint changed index'
printf '1..1\nok - checkpoint preserves index and dirty files and refuses untracked drift\nFM_TEST_COMPLETE\n'
