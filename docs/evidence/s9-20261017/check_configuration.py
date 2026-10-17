"""Local syntax/configuration/link checks; never a remote CI result."""
import ast,json,re,sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
ci=yaml.load((ROOT/'.github/workflows/ci.yml').read_text(),Loader=yaml.BaseLoader)
assert set(ci['on'])=={'push','pull_request'}
assert ci['env']['AIROBOT_GO_MULTI_AGENT_ENABLED']=='false'
assert ci['env']['AIROBOT_LLM_API_KEY']==ci['env']['AIROBOT_EMBEDDING_API_KEY']==''
assert ci['jobs']['go-validation']['env']['AIROBOT_TEST_DOCKER']=='1'
runs=[s['run'] for j in ci['jobs'].values() for s in j['steps'] if 'run' in s]
assert any('python -m pytest tests -q -ra --junitxml=' in s for s in runs)
assert any('check_multi_agent_rollback.py' in s for s in runs)
assert not any('eval/run_eval.py' in s or '--live' in s or '--mode live' in s for s in runs)
assert '${{ secrets.' not in (ROOT/'.github/workflows/ci.yml').read_text()
# Existing Go/ordinary chat source and test code are unchanged in S9.
before=json.loads((OUT/'source-before.json').read_text())
import hashlib
for name,sha in before['files_sha256'].items():
    if name.startswith(('app/','tests/','eval/','sandbox/')):
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
for folder in ('app','scripts','eval','tests'):
    for p in (ROOT/folder).rglob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p),feature_version=(3,11))
# Verify local documentation targets; generated S9 final artifacts are deliberately pending.
missing=[]
for name in ('README.md','docs/multi-agent.md','docs/multi-agent-delivery-audit.md','docs/go-validation.md','docs/multi-agent-acceptance-matrix.md','docs/multi-agent-implementation-plan.md'):
    p=ROOT/name
    for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' in dest or dest.startswith('#'):continue
        target=(p.parent/dest.split('#')[0]).resolve()
        if not target.exists() and not (OUT in target.parents):missing.append(str(target))
assert not missing,missing
result=dict(status='passed',workflow_yaml='parsed_and_structurally_checked',remote_ci='not_run',
    paid_jobs='absent',default_multi_enabled=False,product_source_unchanged=True,syntax='passed',local_links='passed')
(OUT/'configuration-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
