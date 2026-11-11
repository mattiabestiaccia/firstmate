#!/usr/bin/env bash
# Fixture-only retention checks. No real endpoint or pool is contacted.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
python3 - "$ROOT" <<'PY'
import os, pathlib, subprocess, sys, tempfile
root=pathlib.Path(sys.argv[1])
with tempfile.TemporaryDirectory(prefix='fm-preserve-test-') as tmp:
 home=pathlib.Path(tmp)/'home'
 for d in ('config/task-preservation','state','data','worktree','fakebin'):
  (home/d).mkdir(parents=True)
 (home/'worktree/untracked').write_text('keep me')
 (home/'state/task.meta').write_text('sentinel metadata; must not be read or modified')
 log=home/'runtime.log'
 for tool in ('hc','treehouse','tmux'):
  p=home/'fakebin'/tool
  p.write_text('#!/bin/sh\nprintf invoked >> "$FM_RUNTIME_LOG"\nexit 91\n');p.chmod(0o755)
 env=dict(os.environ,FM_HOME=str(home),FM_ROOT_OVERRIDE=str(root),FM_RUNTIME_LOG=str(log))
 env['PATH']=str(home/'fakebin')+':'+env['PATH']
 for name in ('FM_STATE_OVERRIDE','FM_DATA_OVERRIDE','FM_CONFIG_OVERRIDE'):
  env.pop(name,None)
 flag=home/'config/task-preservation/task'
 def snapshot():
  return {str(p.relative_to(home)): ('link',os.readlink(p)) if p.is_symlink() else ('dir',) if p.is_dir() else ('file',p.read_bytes()) for p in home.rglob('*')}
 def guard():
  return subprocess.run(['bash','-c','. "$1"; fm_task_preserve_guard "$2" task teardown','bash',str(root/'bin/fm-task-preserve-lib.sh'),str(home/'config')],env=env,capture_output=True,text=True)
 assert guard().returncode==0
 flag.write_text('Explicit preservation requested for fixture')
 commands=[['fm-teardown.sh','task'],['fm-teardown.sh','task','--force'],['fm-control.sh','task','exit'],['fm-control.sh','task','relaunch'],['fm-spawn.sh','task','--relaunch'],['fm-spawn.sh','task','fixture-project','--mode','local-only','--yolo','off']]
 for cmd in commands:
  before=snapshot()
  r=subprocess.run(['bash',str(root/'bin'/cmd[0]),*cmd[1:]],env=env,capture_output=True,text=True)
  assert r.returncode!=0 and 'resource-preserved' in r.stderr,(cmd,r.stdout,r.stderr)
  assert snapshot()==before,('mutation',cmd,[(k,before.get(k),snapshot().get(k)) for k in set(before)|set(snapshot()) if before.get(k)!=snapshot().get(k)])
  print('PASS no effects:',*cmd)
 # Task without metadata (the retained idle-shell case).
 (home/'state/task.meta').unlink()
 before=snapshot()
 r=subprocess.run(['bash',str(root/'bin/fm-teardown.sh'),'task'],env=env,capture_output=True,text=True)
 assert r.returncode!=0 and 'resource-preserved' in r.stderr
 assert snapshot()==before
 print('PASS preservation without metadata')
 # Only explicit removal lifts this guard; other lifecycle gates still apply.
 flag.unlink();assert guard().returncode==0
 print('PASS explicit revocation')
 flag.symlink_to(home/'missing');assert guard().returncode!=0
 flag.unlink();flag.mkdir();assert guard().returncode!=0;flag.rmdir()
 directory=flag.parent;directory.rmdir();directory.symlink_to(home/'missing')
 assert guard().returncode!=0
 print('PASS malformed and dangling-symlink fail closed')
 # A linked config directory is read through; a dangling one fails closed.
 directory.unlink();directory.mkdir()
 target=home/'config-target';(home/'config').rename(target);(home/'config').symlink_to(target)
 assert guard().returncode==0
 (target/'task-preservation/task').write_text('Explicit preservation requested for fixture')
 r=guard();assert r.returncode!=0 and 'resource-preserved' in r.stderr,(r.stdout,r.stderr)
 (target/'task-preservation/task').unlink()
 (home/'config').unlink();(home/'config').symlink_to(home/'missing')
 r=guard();assert r.returncode!=0 and 'unsafe or unreadable' in r.stderr,(r.stdout,r.stderr)
 print('PASS linked config is read through and a dangling config link fails closed')
 assert not log.exists()
PY
