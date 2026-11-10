#!/usr/bin/env python3
"""Fixture-only checks: no live pool, endpoint, provider or orphan scan."""
import hashlib,json,os,pathlib,subprocess,tempfile
R=pathlib.Path(__file__).resolve().parents[1];source=(R/'bin/fm-teardown.sh').read_text();results=[]
def shell(code,env,args=()):
 return subprocess.run(['/bin/bash','-c',code,'fixture',*args],env=env,capture_output=True,text=True)
def passed(name):results.append(name)
with tempfile.TemporaryDirectory(prefix='fm-orphan-scope-') as tmp:
 H=pathlib.Path(tmp);(H/'config/task-preservation').mkdir(parents=True);(H/'state').mkdir();(H/'data').mkdir();(H/'fakebin').mkdir()
 env={'HOME':str(H),'PATH':'/opt/homebrew/bin:/usr/bin:/bin','FM_HOME':str(H),'FM_ROOT_OVERRIDE':str(R),'TMPDIR':str(H)}
 def full(*args):return subprocess.run(['/bin/bash',str(R/'bin/fm-teardown.sh'),'test',*args],env=env,capture_output=True,text=True)
 def snapshot():return {str(p.relative_to(H)):p.read_bytes() for p in H.rglob('*') if p.is_file()}
 before=snapshot();r=full('--unknown-scope');assert r.returncode==2 and 'invalid teardown request' in r.stderr and snapshot()==before;passed('unknown option refuses without effects')
 (H/'state/test.meta').write_text('sentinel: must not be consumed\n');flag=H/'config/task-preservation/test';flag.write_text('retain synthetic task\n');before=snapshot()
 r=full('--skip-orphan-sweep','--no-prune');assert r.returncode!=0 and 'resource-preserved' in r.stderr and snapshot()==before;passed('full teardown preservation refuses both flags without effects')
 flag.unlink()
 # Actual argument parser, then actual Fix3 block. Only its external dependency is fake.
 parser=source[source.index('ID=$1\n'):source.index('teardown_require_source "$SCRIPT_DIR/fm-task-preserve-lib.sh"')]
 sweep=source[source.index('if [ "$SKIP_ORPHAN_SWEEP" -eq 0 ]; then'):];sweep=sweep[:sweep.index('\nfi')+3]
 mock=H/'fakebin/fm-remote-job-reap-orphans.sh';mock.write_text('#!/bin/sh\nprintf sweep >> "$HOME/sweep.log"\n');mock.chmod(0o700)
 for options,want in [((),True),(('--skip-orphan-sweep',),False),(('--legacy-record','--skip-orphan-sweep'),False)]:
  log=H/'sweep.log';log.unlink(missing_ok=True)
  r=shell(parser+'\nSCRIPT_DIR="$HOME/fakebin"\n'+sweep,env,('test',*options));assert r.returncode==0 and log.exists()==want;passed('parser+original Fix3 '+repr(options))
 # Negative durable-lease check via original library, metadata getter fixture only.
 lease=R/'bin/fm-task-handoff-lib.sh'
 code='source "$1"; fm_meta_get() { case "$2" in treehouse_lease_holder) echo holder;; treehouse_lease_id) echo old;; project|worktree) echo "$HOME";; esac; }; fm_task_lease_holder() { echo holder; }; fm_treehouse_pool_slot() { return 0; }; fm_treehouse_slot_owner_state() { FM_TREEHOUSE_SLOT_OWNER=mine; FM_TREEHOUSE_SLOT_OWNER_HOME="$HOME"; }; treehouse() { printf \'[{"path":"%s","status":"leased","lease_holder":"holder","lease_id":"different"}]\' "$HOME"; }; SKIP_ORPHAN_SWEEP=1; fm_task_handoff_verify_locked fake test "$HOME"'
 r=shell(code,env,(str(lease),));assert r.returncode!=0;passed('original durable lease rejects changed lease with skip flag')
 # Identity validator called by teardown, original function refuses malformed HC identity.
 code='source "$1"; SKIP_ORPHAN_SWEEP=1; fm_backend_validate_task_endpoint "$2" test "$HOME"'
 (H/'state/test.meta').write_text('backend=hc\nwindow=not-an-hc-endpoint\nendpoint_task_id=test\nspawn_gen=fake\nhome='+str(H)+'\n')
 r=shell(code,env,(str(R/'bin/fm-backend.sh'),str(H/'state/test.meta')));assert r.returncode!=0;passed('original endpoint validator rejects malformed identity with skip flag')
 # Original scratch cleanup still removes untracked scratch, retains tracked/ignored data.
 wt=H/'wt';wt.mkdir();subprocess.run(['git','init','-q',str(wt)],env=env,check=True)
 (wt/'.gitignore').write_text('ignored\n');(wt/'tracked').write_text('kept');subprocess.run(['git','-C',str(wt),'add','.gitignore','tracked'],env=env,check=True)
 (wt/'scratch').write_text('discard fixture');(wt/'ignored').write_text('kept')
 fn=source[source.index('teardown_scrub_scratch_copy() {'):];fn=fn[:fn.index('\n}')+2]
 r=shell('SKIP_ORPHAN_SWEEP=1\n'+fn+'\nteardown_scrub_scratch_copy "$1"',env,(str(wt),));assert r.returncode==0 and not (wt/'scratch').exists() and (wt/'tracked').exists() and (wt/'ignored').exists();passed('original task scratch cleanup unchanged with skip flag')
 # Scope remains single call; required checks still precede it in actual script.
 assert source.count('"$SCRIPT_DIR/fm-remote-job-reap-orphans.sh"')==1
 for gate in ['fm_task_preserve_guard','fm_lease_guard "$ID"','fm_task_handoff_verify "$META"','fm_backend_validate_task_endpoint "$META"']:
  assert source.index(gate)<source.index('if [ "$SKIP_ORPHAN_SWEEP" -eq 0 ]; then')
 passed('static unchanged gate ordering and single sweep site')
print(json.dumps({'passed':len(results),'cases':results,'limits':'component checks plus full parser/preservation; not full live teardown or HC runtime'},indent=2))
