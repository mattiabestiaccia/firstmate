#!/usr/bin/env python3
"""--retire-paused on temporary synthetic homes: fake hc, treehouse, lsof and ps.

Every case builds its own home, pool and paused hc scout. No live pool,
endpoint, provider or process scan is reached: the tool path holds only the
fakes plus an allowlist of real tools, the fake lsof reports no process, and
fake ps reads only fixture rows (unless FM_TEARDOWN_REAL_PS=1 explicitly enables
kernel process proof). Every call past the guards passes --skip-orphan-sweep.
"""
import json,os,pathlib,shutil,subprocess,sys,tempfile
R=pathlib.Path(__file__).resolve().parents[1];TEARDOWN=R/'bin/fm-teardown.sh';results=[]
ID='rp-task';LEASE='0123456789abcdef0123456789abcdef';TERMINAL='t115'
PAUSED_TODAY='error: task '+ID+' is paused; teardown would discard retained work. Resume and reconcile it first.\n'
REAL_TOOLS=['bash','git','node','tasks-axi','python3'];SEARCH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'
FORBIDDEN=['hc','herdr','herdr-core','treehouse','claude','codex','pi','gh','no-mistakes']
FAKE_HC='''#!/bin/sh
# Fake hc: one JSON file per terminal; a .fail file makes the read fail.
[ "$1" = --version ] && { echo 'hc 0.1.14'; exit 0; }
printf '%s\\n' "$*" >> "$HOME/hc.log"
f="$HOME/hc/$3.json"
case "$1" in
 get) [ ! -e "$HOME/hc/$3.fail" ] || exit 1; [ -f "$f" ] || exit 3; cat "$f" ;;
 rm) [ ! -e "$HOME/hc-rm-fail" ] || exit 1
     rm -f "$f"
     if [ -e "$HOME/available-after-close.json" ]; then cp "$HOME/available-after-close.json" "$HOME/treehouse-rows.json"; fi
     printf 'close\\n' >> "$HOME/order.log" ;;
esac
'''
FAKE_TREEHOUSE='''#!/bin/sh
# Fake treehouse: status prints the recorded rows; return empties them.
printf '%s\\n' "$*" >> "$HOME/treehouse.log"
case "$1" in
 status) cat "$HOME/treehouse-rows.json" ;;
 return) printf 'return\\n' >> "$HOME/order.log"; printf '[]\\n' > "$HOME/treehouse-rows.json" ;;
esac
'''
FAKE_TASKS_AXI='''#!/bin/sh
# Real tasks-axi, except that `done` fails while $HOME/fail-done exists.
if [ "$1" = done ] && [ -e "$HOME/fail-done" ]; then echo 'synthetic done failure' >&2; exit 1; fi
exec "$HOME/tools/tasks-axi" "$@"
'''
PAUSE_ONLY=['paused','paused.previous','checkpoint.json','native-delivery.json']
ALREADY_COVERED=['treehouse-lease.json','claude-native-ready','native-trust-pending','control-relaunch',
 'control-relaunch.meta-prior','control-relaunch.brief-prior','control-relaunch.note']
def run(cmd,env,**kw):return subprocess.run(cmd,env=env,capture_output=True,text=True,**kw)
def passed(name):results.append(name)
class Home:
 def __init__(self,tmp,name,kind='scout',paused='paused\nsynthetic stop note\n',terminal='finished'):
  H=self.H=pathlib.Path(tmp).resolve()/name;self.state=H/'state';self.data=H/'data'
  for d in ['state','data/'+ID,'config','fakebin','tools','hc','pool/1']:(H/d).mkdir(parents=True)
  for tool in REAL_TOOLS:
   real=shutil.which(tool,path=SEARCH)
   if real:(H/'tools'/tool).symlink_to(real)
  for tool,body in [('hc',FAKE_HC),('treehouse',FAKE_TREEHOUSE),('tasks-axi',FAKE_TASKS_AXI),('lsof','#!/bin/sh\nexit 0\n'),('ps','#!/bin/sh\n[ -f "$HOME/ps-rows" ] || exit 1\ncat "$HOME/ps-rows"\n')]:
   (H/'fakebin'/tool).write_text(body);(H/'fakebin'/tool).chmod(0o700)
  path=':'.join([str(H/'fakebin'),str(H/'tools'),'/usr/bin','/bin','/usr/sbin','/sbin'])
  for tool in FORBIDDEN:
   found=shutil.which(tool,path=path);assert found is None or found.startswith(str(H/'fakebin')),(tool,found)
  env=self.env={'HOME':str(H),'PATH':path,'FM_HOME':str(H),'FM_ROOT_OVERRIDE':str(R),'TMPDIR':str(H),
   'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'}
  ident=['-c','user.name=fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false']
  proj=self.proj=H/'proj';wt=self.wt=H/'pool/1/project'
  for cmd in [['git','init','-q','-b','main',str(proj)],['git','-C',str(proj),*ident,'commit','-q','--allow-empty','-m','fixture'],
    ['git','-C',str(proj),'worktree','add','-q','-b','fm/'+ID,str(wt)]]:
   r=run(cmd,env);assert r.returncode==0,(cmd,r.stderr)
  (wt/'tracked').write_text('kept\n');r=run(['git','-C',str(wt),*ident,'add','tracked'],env);assert r.returncode==0,r.stderr
  r=run(['git','-C',str(wt),*ident,'commit','-q','-m','work'],env);assert r.returncode==0,r.stderr
  (H/'pool/treehouse-state.json').write_text('{}\n');(H/'pool/1/.fm-slot-owner').write_text('task=%s\nhome=%s\n'%(ID,H))
  r=run(['git','hash-object','--stdin'],env,input=str(H));assert r.returncode==0,r.stderr
  self.holder='fm-%s-%s'%(r.stdout.strip(),ID)
  (H/'treehouse-rows.json').write_text(json.dumps([{'path':str(wt),'status':'leased','lease_holder':self.holder,'lease_id':LEASE}])+'\n')
  r=run(['/bin/bash','-c','. "$1/bin/fm-backend-hometag-lib.sh"; FM_ROOT=$1 fm_backend_hometag','fixture',str(R)],env)
  assert r.returncode==0 and r.stdout.strip(),r.stderr
  self.labels={'firstmate.task':'fm-'+ID,'firstmate.home':r.stdout.strip()};self.terminal(terminal)
  (H/'.tasks.toml').write_text('backend = "markdown"\n[markdown]\npath = "data/backlog.md"\narchive = "data/done-archive.md"\ndone_keep = 10\n')
  (self.data/'backlog.md').write_text('# Backlog\n\n## In flight\n- [ ] %s - Fake paused %s (kind: %s) (since 2026-11-10)\n\n## Queued\n\n## Done\n'%(ID,kind,kind)
   +''.join('- [x] fake-old-%d - Fake old (closed 2026-11-09)\n'%i for i in range(10)))
  (self.data/ID/'report.md').write_text('synthetic report\n')
  self.meta=self.state/(ID+'.meta')
  self.meta.write_text(''.join(k+'='+v+'\n' for k,v in [('window','default:'+TERMINAL),('endpoint_task_id',ID),('worktree',str(wt)),
   ('treehouse_lease_holder',self.holder),('treehouse_lease_id',LEASE),('project',str(proj)),('harness','claude'),('kind',kind),
   ('mode','local-only'),('spawn_gen','s1794320000.1.1'),('backend','hc'),('hc_session','default'),('hc_terminal',TERMINAL),('decisions_reviewed','1'),('decision_keys','')]))
  for suffix in ALREADY_COVERED+[x for x in PAUSE_ONLY if x not in ('paused','checkpoint.json')]:(self.state/(ID+'.'+suffix)).write_text('synthetic\n')
  if paused is not None:
   (self.state/(ID+'.paused')).write_text(paused)
   r=run([sys.executable,str(R/'bin/fm-task-checkpoint.py'),'capture',str(wt),str(self.state/(ID+'.checkpoint.json'))],env);assert r.returncode==0,r.stderr
 def terminal(self,state):
  f=self.H/'hc'/(TERMINAL+'.json');(self.H/'hc'/(TERMINAL+'.fail')).unlink(missing_ok=True)
  if state=='absent':f.unlink(missing_ok=True)
  elif state=='unreadable':(self.H/'hc'/(TERMINAL+'.fail')).write_text('')
  else:
   row={'state':state,'labels':self.labels}
   if state=='live':row['foreground']={'name':'claude','argv':['claude'],'pid':1}
   f.write_text(json.dumps(row)+'\n')
 def teardown(self,*args):return run(['/bin/bash',str(TEARDOWN),ID,*args],self.env)
 def snapshot(self):
  # Everything the refusal contract names: task records, lease rows, terminal, copy, backlog, fake logs.
  # Lock directories and the guard's advisory banner state are transient and not task effects.
  out={}
  for p in sorted(self.H.rglob('*')):
   rel=str(p.relative_to(self.H))
   if rel.startswith(('tools/','fakebin/','proj/.git/','state/.guard-')) or '.lock' in rel or rel in ('hc.log','treehouse.log'):continue
   out[rel]=os.readlink(p) if p.is_symlink() else (p.read_bytes() if p.is_file() else 'dir')
  for log in ['hc.log','treehouse.log']:
   lines=(self.H/log).read_text().splitlines() if (self.H/log).exists() else []
   out[log]=[l for l in lines if not l.startswith(('get ','status '))]
  return out
 def refused(self,*args,want,code=None,stdout=''):
  before=self.snapshot();r=self.teardown(*args)
  assert r.returncode!=0 and (code is None or r.returncode==code),(args,r.returncode,r.stderr)
  assert want in r.stderr,(args,r.stderr);assert r.stdout==stdout,(args,r.stdout)
  after=self.snapshot();assert after==before,(args,sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k)))
  return r
with tempfile.TemporaryDirectory(prefix='fm-retire-paused-') as tmp:
 # A returned pool copy permits only explicit forced record retirement.
 for name,rows in [('available',[{'status':'available'}]),
                   ('leased-other',[{'status':'leased','lease_holder':'another-task','lease_id':'new'}]),
                   ('available-stale-lease',[{'status':'available','lease_id':'still-leased'}]),
                   ('duplicate',[{'status':'available'},{'status':'available'}]),
                   ('missing',[])]:
  h=Home(tmp,'returned-'+name,paused=None)
  (h.H/'treehouse-rows.json').write_text(json.dumps([dict(row,path=str(h.wt)) for row in rows])+'\n')
  h.refused('--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
  if name!='available':
   h.refused('--force','--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
   continue
  def copy_snapshot():
   return {str(p.relative_to(h.H/'pool')):(os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else 'dir') for p in (h.H/'pool').rglob('*')}
  before=copy_snapshot()
  refs=run(['git','-C',str(h.proj),'show-ref'],h.env).stdout
  r=h.teardown('--force','--skip-orphan-sweep')
  assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
  assert 'closing only the task record' in r.stderr,r.stderr
  assert copy_snapshot()==before,'returned copy or owner claim changed'
  assert run(['git','-C',str(h.proj),'show-ref'],h.env).stdout==refs,'branches changed'
  assert not h.meta.exists(),'task metadata retained'
  assert not (h.H/'hc'/(TERMINAL+'.json')).exists(),'endpoint retained'
  assert '- [x] '+ID in (h.data/'backlog.md').read_text(),'backlog not closed'
  assert not any(line.startswith('return ') for line in (h.H/'treehouse.log').read_text().splitlines()),'returned copy twice'
 passed('returned slots require force and close only records; another lease, stale lease fields, duplicate or missing rows refuse')
 h=Home(tmp,'returned-unreadable',paused=None)
 (h.H/'treehouse-rows.json').write_text('not JSON\n')
 h.refused('--force','--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
 passed('unreadable returned-slot status refuses even with force')
 # A reassigned slot held by a known task licenses ONLY old-record retirement.
 for valid in [True,False]:
  h=Home(tmp,'reassigned-known-'+str(valid),paused=None)
  owner='new-task';new_lease='fedcba9876543210fedcba9876543210'
  new_holder=h.holder.removesuffix(ID)+owner
  owner_meta=h.state/(owner+'.meta')
  owner_meta.write_text(h.meta.read_text().replace(ID,owner).replace(LEASE,new_lease).replace(TERMINAL,'t222'))
  (h.H/'pool/1/.fm-slot-owner').write_text('task=%s\nhome=%s\n'%(owner,h.H))
  rows=[{'path':str(h.wt),'status':'leased','lease_holder':new_holder,'lease_id':new_lease if valid else 'mismatched','processes':[{'pid':98765}]}]
  (h.H/'treehouse-rows.json').write_text(json.dumps(rows))
  if not valid:
   h.refused('--force','--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
   continue
  (h.H/'hc-rm-fail').write_text('')
  before_refusal=h.snapshot();r=h.teardown('--force','--skip-orphan-sweep')
  assert r.returncode==1 and 'before returning its copy' in r.stderr,r.stderr
  after_refusal=h.snapshot();before_refusal.pop('hc.log');after_refusal.pop('hc.log')
  assert before_refusal==after_refusal,'close failure changed copy or durable records'
  (h.H/'hc-rm-fail').unlink()
  before={str(p.relative_to(h.H/'pool')):(p.read_bytes() if p.is_file() else 'dir') for p in (h.H/'pool').rglob('*')}
  owner_before=owner_meta.read_bytes();refs=run(['git','-C',str(h.proj),'show-ref'],h.env).stdout
  r=h.teardown('--force','--skip-orphan-sweep');assert r.returncode==0,(r.returncode,r.stderr)
  assert 'another known task holds the new lease' in r.stderr,r.stderr
  assert not h.meta.exists() and not (h.H/'hc'/(TERMINAL+'.json')).exists()
  assert owner_meta.read_bytes()==owner_before and json.loads((h.H/'treehouse-rows.json').read_text())==rows
  assert {str(p.relative_to(h.H/'pool')):(p.read_bytes() if p.is_file() else 'dir') for p in (h.H/'pool').rglob('*')}==before
  assert run(['git','-C',str(h.proj),'show-ref'],h.env).stdout==refs
  assert (h.H/'order.log').read_text().splitlines()==['close']
 passed('reassigned known-task lease closes only stale record/endpoint; copy, foreign PID, claim, new metadata, lease and refs untouched; mismatched claimant refuses')
 # Returned in-use slots authorize only descendants of their own endpoint.
 for name,pids,ps_rows,owner,good in [
   ('shell-only',[101],'101 1\n',None,True),
   ('shell-child',[101,102],'101 1\n102 101\n',None,True),
   ('foreign-process',[101,201],'101 1\n201 1\n',None,False),
   ('foreign-owner',[101],'101 1\n','another-task',False),
   ('unreadable-process-table',[101],None,None,False),
   ('missing-root',[101],'102 1\n',None,False),
   ('cycle',[102],'101 1\n102 103\n103 102\n',None,False),
   ('missing-process-list',None,'101 1\n',None,False),
   ('empty-process-list',[],'101 1\n',None,False),
   ('malformed-pid',['101'],'101 1\n',None,False)]:
  h=Home(tmp,'in-use-'+name,paused=None,terminal='live')
  endpoint=h.H/'hc'/(TERMINAL+'.json');obj=json.loads(endpoint.read_text())
  obj['foreground']={'name':'fish','argv':['fish'],'pid':101};endpoint.write_text(json.dumps(obj))
  row={'path':str(h.wt),'status':'in-use','lease_holder':'','lease_id':''}
  if pids is not None:row['processes']=[{'pid':p} for p in pids]
  (h.H/'treehouse-rows.json').write_text(json.dumps([row]))
  (h.H/'available-after-close.json').write_text(json.dumps([dict(row,status='available',processes=[])]))
  if ps_rows is not None:(h.H/'ps-rows').write_text(ps_rows)
  if owner:(h.H/'pool/1/.fm-slot-owner').write_text('task=%s\nhome=%s\n'%(owner,h.H))
  if not good:
   h.refused('--force','--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
   continue
  copy_before=(h.wt/'tracked').read_bytes();r=h.teardown('--force','--skip-orphan-sweep')
  assert r.returncode==0,(name,r.returncode,r.stdout,r.stderr)
  assert not h.meta.exists() and not endpoint.exists(),name
  assert (h.wt/'tracked').read_bytes()==copy_before,name
  assert (h.H/'order.log').read_text().splitlines()==['close'],name
 passed('in-use returned slot: endpoint shell and descendants close; foreign PID/owner, denied ps, missing/cyclic/malformed proof refuse unchanged')
 # Opt-in kernel process proof, still with synthetic hc/Treehouse only.
 # Outside a sandbox denying ps: FM_TEARDOWN_REAL_PS=1 python3 tests/fm-teardown-retire-paused.test.py
 if os.environ.get('FM_TEARDOWN_REAL_PS')=='1':
  real_ps=shutil.which('ps',path=SEARCH);assert real_ps,'ps is required for the explicit real-process run'
  check=run([real_ps,'-A','-o','pid=,ppid='],os.environ)
  assert check.returncode==0,check.stderr
  root=subprocess.Popen([sys.executable,'-u','-c','import subprocess,time; p=subprocess.Popen(["sleep","300"]); print(p.pid,flush=True); time.sleep(300)'],stdout=subprocess.PIPE,text=True)
  child=int(root.stdout.readline().strip())
  outsider=subprocess.Popen(['sleep','300'])
  try:
   for foreign in [False,True]:
    h=Home(tmp,'real-process-'+str(foreign),paused=None,terminal='live')
    (h.H/'fakebin/ps').unlink();(h.H/'fakebin/ps').symlink_to(real_ps)
    endpoint=h.H/'hc'/(TERMINAL+'.json');obj=json.loads(endpoint.read_text());obj['foreground']['pid']=root.pid;endpoint.write_text(json.dumps(obj))
    row={'path':str(h.wt),'status':'in-use','processes':[{'pid':p} for p in [root.pid,child]+([outsider.pid] if foreign else [])]}
    (h.H/'treehouse-rows.json').write_text(json.dumps([row]))
    (h.H/'available-after-close.json').write_text(json.dumps([dict(row,status='available',processes=[])]))
    if foreign:h.refused('--force','--skip-orphan-sweep',want='durable Treehouse lease changed',code=1)
    else:
     r=h.teardown('--force','--skip-orphan-sweep');assert r.returncode==0,r.stderr
   passed('real ps: actual endpoint descendant tree accepted and actual unrelated PID refused (synthetic endpoint close/status)')
  finally:
   os.kill(child,15);root.terminate();outsider.terminate();root.wait();outsider.wait()
 # Closing a terminal is not proof that the copy became idle: re-read status.
 h=Home(tmp,'in-use-still-busy',paused=None,terminal='live')
 endpoint=h.H/'hc'/(TERMINAL+'.json');obj=json.loads(endpoint.read_text());obj['foreground']['pid']=101;endpoint.write_text(json.dumps(obj))
 (h.H/'ps-rows').write_text('101 1\n')
 (h.H/'treehouse-rows.json').write_text(json.dumps([{'path':str(h.wt),'status':'in-use','processes':[{'pid':101}]}]))
 r=h.teardown('--force','--skip-orphan-sweep')
 assert r.returncode==1 and 'not empty and available after endpoint close' in r.stderr,r.stderr
 assert h.meta.exists() and (h.wt/'tracked').exists()
 assert not any(l.startswith('return ') for l in (h.H/'treehouse.log').read_text().splitlines())
 passed('post-close still-busy slot retains records and copy without returning it')
 # Prove the original ordering bug: a close failure must precede pool return.
 h=Home(tmp,'close-fails-before-return',paused=None)
 (h.H/'hc-rm-fail').write_text('')
 r=h.teardown('--force','--skip-orphan-sweep')
 assert r.returncode==1 and 'before returning its copy' in r.stderr,r.stderr
 assert h.meta.exists() and (h.H/'hc'/(TERMINAL+'.json')).exists()
 assert not any(l.startswith('return ') for l in (h.H/'treehouse.log').read_text().splitlines())
 h=Home(tmp,'close-before-return',paused=None)
 r=h.teardown('--force','--skip-orphan-sweep');assert r.returncode==0,r.stderr
 assert (h.H/'order.log').read_text().splitlines()==['close','return']
 passed('origin regression: endpoint close precedes pool return; close refusal cannot strand a returned slot')
 # (i) Without the option a paused task is refused with today's exact bytes and exit status.
 h=Home(tmp,'plain')
 for args in [('--skip-orphan-sweep',),('--skip-orphan-sweep','--no-prune'),()]:
  r=h.refused(*args,want=PAUSED_TODAY,code=1);assert r.stderr==PAUSED_TODAY,r.stderr
 passed('i: without the option a paused task keeps the current refusal bytes and exit 1')
 # (vi) --retire-paused with --force refuses in either order, before the pause is read.
 for args in [('--retire-paused','--force','--skip-orphan-sweep'),('--skip-orphan-sweep','--force','--retire-paused','--no-prune')]:
  h.refused(*args,want='--retire-paused cannot be combined with --force',code=2)
 passed('vi: --retire-paused with --force refuses without effects')
 # (viii) The preservation guard still comes first, with the pause untouched.
 flag=h.H/'config/task-preservation';flag.mkdir();(flag/ID).write_text('retain synthetic task\n')
 r=h.refused('--retire-paused','--skip-orphan-sweep',want='task '+ID+' is resource-preserved; refusing teardown',code=1)
 assert 'paused' not in r.stderr,r.stderr;passed('viii: preservation guard refuses before the pause is examined')
 # (vii) The option is not a synonym for an ordinary teardown.
 h=Home(tmp,'not-paused',paused=None)
 h.refused('--retire-paused','--skip-orphan-sweep',want='task '+ID+' is not paused; --retire-paused retires only a paused task',code=1)
 passed('vii: --retire-paused on a task that is not paused refuses without effects')
 # (v) A pause whose stop was never confirmed, or an unsafe pause record, refuses.
 for name,body in [('pausing','pausing\nnote\n'),('padded','paused \nnote\n'),('empty','')]:
  h=Home(tmp,'first-line-'+name,paused=body)
  h.refused('--retire-paused','--skip-orphan-sweep',want="is not a regular file whose first line is exactly 'paused'",code=1)
 h=Home(tmp,'pause-symlink');real=h.state/'elsewhere';real.write_text('paused\nnote\n')
 (h.state/(ID+'.paused')).unlink();(h.state/(ID+'.paused')).symlink_to(real)
 h.refused('--retire-paused','--skip-orphan-sweep',want="is not a regular file whose first line is exactly 'paused'",code=1)
 passed('v: an incomplete or unsafe pause record refuses without effects')
 # (iii) An agent that is alive, or whose state cannot be read, refuses.
 for state,reads in [('live','alive'),('unreadable','unreadable'),('starting','unreadable')]:
  h=Home(tmp,'endpoint-'+state,terminal=state)
  h.refused('--retire-paused','--skip-orphan-sweep',want="recorded endpoint reads '%s', not confidently dead or agent-less"%reads,code=1)
 passed('iii: a live or unreadable endpoint refuses without effects')
 # (iv) A checkpoint that does not verify refuses: drift in the copy, then no checkpoint at all.
 h=Home(tmp,'checkpoint-drift');(h.wt/'tracked').write_text('changed after the pause\n')
 h.refused('--retire-paused','--skip-orphan-sweep',want='does not verify against its copy',code=1)
 h=Home(tmp,'checkpoint-untracked');(h.wt/'new-file').write_text('written after the pause\n')
 h.refused('--retire-paused','--skip-orphan-sweep',want='does not verify against its copy',code=1)
 h=Home(tmp,'checkpoint-missing');(h.state/(ID+'.checkpoint.json')).unlink()
 h.refused('--retire-paused','--skip-orphan-sweep',want='does not verify against its copy',code=1)
 passed('iv: an unverifiable checkpoint refuses without effects')
 # The durable-lease check and the scout gate are not relaxed by the option.
 h=Home(tmp,'lease-changed');(h.H/'treehouse-rows.json').write_text(json.dumps([{'path':str(h.wt),'status':'leased','lease_holder':h.holder,'lease_id':'different'}])+'\n')
 h.refused('--retire-paused','--skip-orphan-sweep',want='durable Treehouse lease changed; teardown preserves the copy',code=1)
 h=Home(tmp,'scout-no-report');(h.data/ID/'report.md').unlink()
 h.refused('--retire-paused','--skip-orphan-sweep',want='REFUSED: scout task '+ID+' has no report',code=1)
 h=Home(tmp,'scout-unreviewed');h.meta.write_text(h.meta.read_text().replace('decisions_reviewed=1\n',''))
 h.refused('--retire-paused','--skip-orphan-sweep',want='has not passed the captain-call completion gate',code=1)
 passed('existing lease check and scout gate still refuse with the option')
 # A paused ship still faces the landed-work checks, and a secondmate is never retired this way.
 h=Home(tmp,'ship-unlanded',kind='ship')
 h.refused('--retire-paused','--skip-orphan-sweep',want='has work not yet merged into main and not on any remote',code=1)
 h=Home(tmp,'secondmate',kind='secondmate')
 h.refused('--retire-paused','--skip-orphan-sweep',want='--retire-paused supports ship and scout tasks only',code=1)
 passed('landed-work checks still refuse a paused ship; a secondmate is refused')
 # (ii) Valid preconditions retire the task: lease returned, terminal removed, pause records gone, row closed.
 for name,terminal in [('retire-finished','finished'),('retire-absent','absent')]:
  h=Home(tmp,name,terminal=terminal);r=h.teardown('--retire-paused','--skip-orphan-sweep','--no-prune')
  assert r.returncode==0,(name,r.returncode,r.stdout,r.stderr)
  assert 'teardown '+ID+' complete (window default:'+TERMINAL in r.stdout,r.stdout
  log=(h.H/'treehouse.log').read_text().splitlines()
  assert 'return --force --if-lease-holder %s %s'%(h.holder,h.wt) in log,log
  assert json.loads((h.H/'treehouse-rows.json').read_text())==[]
  assert not (h.H/'hc'/(TERMINAL+'.json')).exists() and not (h.H/'pool/1/.fm-slot-owner').exists()
  hc=(h.H/'hc.log').read_text().splitlines();assert not any(l.startswith('kill ') for l in hc),hc
  assert ('rm --json '+TERMINAL in hc)==(terminal=='finished'),hc
  left=sorted(p.name for p in h.state.iterdir() if p.name.startswith(ID+'.'));assert left==[],left
  backlog=(h.data/'backlog.md').read_text();assert '- [x] '+ID+' ' in backlog and '- [ ] '+ID+' ' not in backlog,backlog
  assert sum('fake-old-%d '%i in backlog for i in range(10))==10 and not (h.data/'done-archive.md').exists()
  assert (h.data/ID/'report.md').exists()
  r=h.teardown('--retire-paused','--skip-orphan-sweep');assert r.returncode!=0 and 'is not paused' in r.stderr,r.stderr
 passed('ii: valid preconditions retire the task, return the lease, remove the pause records and close the row')
 # The pause records go with the other state files, before the backlog transition: a failed transition
 # leaves only the usual pending-close record, byte for byte what an ordinary teardown leaves, and it replays.
 markers={}
 for name,paused,args in [('transition-fails',True,('--retire-paused',)),('transition-fails-ordinary',False,())]:
  h=Home(tmp,name) if paused else Home(tmp,name,paused=None)
  (h.H/'fail-done').write_text('');r=h.teardown(*args,'--skip-orphan-sweep')
  assert r.returncode==1 and 'its backlog item could not be closed atomically (synthetic done failure)' in r.stderr,(name,r.returncode,r.stderr)
  left=sorted(p.name[len(ID)+1:] for p in h.state.iterdir() if p.name.startswith(ID+'.'))
  assert left==['backlog-close']+([] if paused else ['native-delivery.json','paused.previous']),(name,left)
  assert '- [ ] '+ID+' ' in (h.data/'backlog.md').read_text() and json.loads((h.H/'treehouse-rows.json').read_text())==[]
  markers[name]=(h.state/(ID+'.backlog-close')).read_text().replace(str(h.H),'<home>')
 assert markers['transition-fails']==markers['transition-fails-ordinary'],markers
 h=Home(tmp,'transition-replays');(h.H/'fail-done').write_text('');r=h.teardown('--retire-paused','--skip-orphan-sweep');assert r.returncode==1,r.stderr
 (h.H/'fail-done').unlink()
 code='source "$1/bin/fm-tasks-axi-lib.sh"; source "$1/bin/fm-backlog-transition-lib.sh"; fm_backlog_close_marker_replay "$HOME/state" "$HOME/state/$2.backlog-close" "$HOME/data" || { printf "%s" "$FM_BACKLOG_TRANSITION_ERROR" >&2; exit 10; }; printf "%s" "$FM_BACKLOG_CLOSE_REPLAY_RESULT"'
 r=run(['/bin/bash','-c',code,'fixture',str(R),ID],h.env,cwd=h.H);assert r.returncode==0 and r.stdout=='closed',(r.returncode,r.stdout,r.stderr)
 assert '- [x] '+ID+' ' in (h.data/'backlog.md').read_text() and [p.name for p in h.state.iterdir() if p.name.startswith(ID+'.')]==[]
 passed('a failed backlog transition leaves no pause record, only the usual pending-close record, and it replays')
print(json.dumps({'passed':len(results),'cases':results,'limits':'fake hc, treehouse and lsof on synthetic homes, real tasks-axi; ps synthetic unless FM_TEARDOWN_REAL_PS=1; no real Herdr Core, Treehouse, harness or orphan sweep'},indent=2))
