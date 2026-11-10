#!/usr/bin/env python3
"""Original marker/replay and real tasks client, only temporary synthetic homes."""
from pathlib import Path
import tempfile,subprocess,json
R=Path(__file__).resolve().parents[1];results=[]
with tempfile.TemporaryDirectory(prefix='fm-no-prune-') as tmp:
 for name,flags,replay,expected in [('new-replay',['--no-prune'],True,0),('new-direct',['--no-prune'],False,0),('legacy-replay',[],True,1),('duplicate',['--no-prune','--no-prune'],True,None)]:
  H=Path(tmp)/name
  for d in ['state','data/task','config']:(H/d).mkdir(parents=True,exist_ok=True)
  (H/'.tasks.toml').write_text('backend = "markdown"\n[markdown]\npath = "data/backlog.md"\narchive = "data/done-archive.md"\ndone_keep = 10\n')
  b='# Backlog\n\n## In flight\n- [ ] task - Fake target (since 2026-11-10)\n\n## Queued\n\n## Done\n'+''.join('- [x] fake-old-'+str(i)+' - Fake old (closed 2026-11-09)\n' for i in range(10))
  (H/'data/backlog.md').write_text(b);(H/'data/task/report.md').write_text('synthetic report\n')
  env={'HOME':str(H),'FM_HOME':str(H),'PATH':'/opt/homebrew/bin:/usr/bin:/bin','FM_ROOT_OVERRIDE':str(R)}
  code='source "$1/bin/fm-tasks-axi-lib.sh"; source "$1/bin/fm-backlog-transition-lib.sh"; shift; fm_backlog_close_marker_write "$HOME/state" task "$HOME/data" s1794320000.1.1 --report data/task/report.md "$@" || { printf "%s" "$FM_BACKLOG_TRANSITION_ERROR" >&2; exit 9; }; '
  if replay:code+='fm_backlog_close_marker_replay "$HOME/state" "$HOME/state/task.backlog-close" "$HOME/data" || { printf "%s" "$FM_BACKLOG_TRANSITION_ERROR" >&2; exit 10; }'
  else:code+='fm_backlog_atomic_transition close "" "$HOME/state/task.backlog-close" "$HOME/data" task "$HOME/state" --report data/task/report.md "$@" || exit 11'
  r=subprocess.run(['/bin/bash','-c',code,'fixture',str(R),*flags],env=env,cwd=H,capture_output=True,text=True)
  if expected is None:
   assert r.returncode==9 and (H/'data/backlog.md').read_text()==b and not (H/'state/task.backlog-close').exists(),(name,r.returncode,r.stderr)
  else:
   assert r.returncode==0,(name,r.returncode,r.stderr)
   a=H/'data/done-archive.md';moved=sum('fake-old-'+str(i)+' ' in (a.read_text() if a.exists() else '') for i in range(10));assert moved==expected,(name,moved)
   assert not (H/'state/task.backlog-close').exists()
   assert '- [x] task ' in (H/'data/backlog.md').read_text()
  results.append({'case':name,'pass':True,'archived_other_rows':expected})
print(json.dumps({'passed':len(results),'cases':results,'scope':'fake homes only, original marker/direct/replay functions and installed tasks client'},indent=2))
