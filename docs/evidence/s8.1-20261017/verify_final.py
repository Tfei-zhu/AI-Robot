import hashlib,json,runpy,tarfile,xml.etree.ElementTree as ET
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sha=lambda b:hashlib.sha256(b).hexdigest()
base=runpy.run_path(str(OUT.parent/'s0-20261017/run_baseline.py'))
preserve=json.loads((OUT/'preservation-before.json').read_text())
assert all(sha((ROOT/p).read_bytes())==h for p,h in preserve['old_evidence'].items())
assert sha((ROOT/'docs/multi-agent-execution-log.md').read_bytes()[:preserve['log_bytes']])==preserve['log_sha256']
before=json.loads((OUT/'source-before.json').read_text());after=base['snapshot'](ROOT)
allowed={'eval/multi_agent_protocol.py','eval/multi_agent_scoring.py','eval/run_multi_agent_eval.py','docs/multi-agent-evaluation.md'}
assert all(p in allowed or after['files_sha256'].get(p)==h for p,h in before['files_sha256'].items())
assert before['tracked_diff_sha256']==after['tracked_diff_sha256']
from eval.multi_agent_protocol import load_freeze,validate_live_cases
frozen=load_freeze(OUT/'freeze-v2');validate_live_cases(frozen['cases'])
prepared=json.loads((OUT/'live-preflight.json').read_text());assert prepared['status']=='blocked' and prepared['calls_sent']==0
probes=[json.loads(p.read_text()) for p in (OUT/'probes').glob('*.json')]
positive=[p for p in probes if p['independent']['correct'] is True];negative=[p for p in probes if p['independent']['correct'] is False]
assert len(positive)==28 and len(negative)==1
assert all(p['independent']['report']['container_removed'] for p in probes)
assert all(p['independent']['artifact_hash'] and p['independent']['scorer_input_hash'] for p in probes)
commands=json.loads((OUT/'commands.json').read_text())
full=next(r for r in commands if r['label']=='all-docker')
assert full['exit_code']==0 and full['source_unchanged'] and full['source_manifest_sha256']==after['source_manifest_sha256']
xml=ET.parse(OUT/next(s.split('=',1)[1].split('/')[-1] for s in full['argv'] if s.startswith('--junitxml='))).getroot()
assert not list(xml.iter('failure')) and not list(xml.iter('error')) and not list(xml.iter('skipped'))
assert not (OUT/'network-audit.txt').exists()
assert (OUT/'containers-after.txt').read_text()==''
(OUT/'source-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
with tarfile.open(OUT/'source-final.tar.gz','w:gz') as tar:
    for name in after['files_sha256']:tar.add(ROOT/name,arcname=name)
result=dict(status='passed',head=after['head'],branch=after['branch'],source_manifest_sha256=after['source_manifest_sha256'],
 tracked_diff_sha256=after['tracked_diff_sha256'],freeze_hash=frozen['freeze_hash'],preserved_evidence_files=len(preserve['old_evidence']),
 junit_records=len(list(xml.iter('testcase'))),real_docker_candidate_reference_checks=28,real_docker_counterexample_rejected=1,
 live_status='blocked',live_provider_requests=0,new_corpus_quality_comparison='not_run',old_v1_results='unchanged')
(OUT/'final-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
