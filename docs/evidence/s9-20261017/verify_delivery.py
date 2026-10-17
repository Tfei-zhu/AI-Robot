"""Final server/code/evidence checks; does not infer real model or remote CI success."""
import hashlib,json,runpy,subprocess,tarfile,xml.etree.ElementTree as ET
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
base=runpy.run_path(str(OUT.parent/'s0-20261017/run_baseline.py'));sha=lambda b:hashlib.sha256(b).hexdigest()
current=base['snapshot'](ROOT);tested=json.loads((OUT/'source-final-validation.json').read_text())
assert current['files_sha256']==tested['files_sha256'],'source changed after final implementation checks'
commands=json.loads((OUT/'commands.json').read_text())
for row in commands:
    assert sha((OUT/row['output']).read_bytes())==row['output_sha256']
    assert row['exit_code']==(1 if row['label']=='configuration' else 0),(row['label'],row['exit_code'])
final=next(r for r in commands if r['label']=='all-docker-confirmed')
assert final['source_manifest_sha256']==current['source_manifest_sha256'] and final['source_unchanged']
rollback=next(r for r in commands if r['label']=='rollback-final')
assert rollback['source_manifest_sha256']==current['source_manifest_sha256'] and rollback['source_unchanged']
xml=ET.parse(OUT/'all-docker-confirmed.xml')
assert not any(list(xml.iter(k)) for k in ('failure','error','skipped'))
status=json.loads((OUT/'delivery-status.json').read_text())
assert status['task_counts']=={'完成':24,'待验证':2,'阻塞':2}
assert status['acceptance_counts']=={'完成':18}
assert not status['enablement']['passed'] and status['real_model']['requests']==0
assert status['remote_ci']['status']=='not_run'
assert len(status['tasks'])==28 and len({r['id'] for r in status['tasks']})==28
assert len(status['acceptance'])==18 and all(r['status']=='完成' for r in status['acceptance'])
run=json.loads((OUT/'rollback-final/summary.json').read_text())
assert run['status']=='passed' and run['enabled'] is False and run['multi_role_calls']==0 and run['provider_requests']==0
assert run['model_calls_during_report_reads']==0
assert run['actual_fixture_calls']==11 and len(run['trials'])==8 and len(run['reopened_report_checks'])==10
assert len(run['ordinary_chat'])==6 and all(r['passed'] for r in run['ordinary_chat'])
assert sum(r['validation_calls'] for r in run['trials'])==11
for p in (OUT/'rollback-final').glob('*.json'):
    report=json.loads(p.read_text())
    if 'attempts' in report and not p.name.startswith('read-'):
        assert all(a['validation']['container_removed'] for a in report['attempts'])
assert not (OUT/'network-audit.txt').exists()
assert (OUT/'containers-after.txt').read_text()==''
preserve=json.loads((OUT/'preservation-before.json').read_text())
assert all(sha((ROOT/name).read_bytes())==h for name,h in preserve['old_evidence'].items())
assert sha((ROOT/'docs/multi-agent-execution-log.md').read_bytes()[:preserve['log_bytes']])==preserve['log_sha256']
before=json.loads((OUT/'source-before.json').read_text())
allowed={'README.md','.github/workflows/ci.yml','docs/go-validation.md','docs/multi-agent-implementation-plan.md',
 'docs/multi-agent-acceptance-matrix.md','docs/multi-agent-execution-prompts.md'}
modified=sorted(p for p,h in before['files_sha256'].items() if current['files_sha256'].get(p)!=h)
assert set(modified)<=allowed,modified
added=sorted(set(current['files_sha256'])-set(before['files_sha256']))
assert added==['docs/multi-agent-delivery-audit.md','docs/multi-agent.md','scripts/check_multi_agent_rollback.py'],added
assert current['head']==before['head'] and current['branch']==before['branch'] and current['staged_diff_sha256']==before['staged_diff_sha256']
assert sha((OUT/'tracked-working-tree.patch').read_bytes())==current['tracked_diff_sha256']
assert sha((OUT/'staged-working-tree.patch').read_bytes())==current['staged_diff_sha256']
with tarfile.open(OUT/'source-final.tar.gz') as archive:
    assert {m.name:sha(archive.extractfile(m).read()) for m in archive.getmembers()}==current['files_sha256']
assert json.loads((OUT/'configuration-check.json').read_text())['status']=='passed'
prepared=json.loads((OUT/'live-preflight.json').read_text());assert prepared['status']=='blocked' and prepared['calls_sent']==0
result=dict(status='passed',source_manifest_sha256=current['source_manifest_sha256'],head=current['head'],branch=current['branch'],
 tracked_diff_sha256=current['tracked_diff_sha256'],staged_diff_sha256=current['staged_diff_sha256'],
 source_files=len(current['files_sha256']),modified_files=modified,added_files=added,preserved_evidence_files=len(preserve['old_evidence']),
 local_tests=status['local_tests'],task_counts=status['task_counts'],acceptance_counts=status['acceptance_counts'],
 rollback='passed_with_actual_environment_false',rollback_real_docker_validations=11,rollback_paid_requests=0,
 remote_ci='not_run',real_model='blocked_not_run',enablement_passed=False,task_resume='not_implemented',ordinary_chat_auto_delegation='not_implemented')
(OUT/'source-after.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
(OUT/'final-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
