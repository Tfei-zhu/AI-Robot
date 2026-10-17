"""S8.1 candidate data checks. Synthetic corpus readiness is not model quality."""
import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from eval.go_fixtures import output
from eval.multi_agent_protocol import freeze,load_freeze,validate_live_cases,live_preflight,write_json
from eval.multi_agent_scoring import score,scoring_bundle,label

ROOT=Path(__file__).resolve().parents[1]
CASES=ROOT/'eval/multi_agent_live_cases.jsonl'
PROTOCOL=ROOT/'eval/multi_agent_live_protocol.json'

def cases():return [json.loads(s) for s in CASES.read_text().splitlines()]

def test_candidate_families_and_freeze_are_bound(tmp_path):
    rows=cases();validate_live_cases(rows)
    assert len({r['requirement'] for r in rows})==30
    assert len({r['group_id'] for r in rows})==15
    assert sum(r['split']=='dev' for r in rows)==18
    assert sum(not r['feasible'] for r in rows)==2
    frozen=freeze(tmp_path/'v2','test',cases_path=CASES,protocol_path=PROTOCOL)
    assert load_freeze(tmp_path/'v2')==frozen
    assert frozen['protocol']['dataset_purpose']=='grouped-live-candidate-v2'
    assert frozen['cases']==rows

@pytest.mark.parametrize('mutation',['duplicate','family_leak','missing_probe','wrong_probe','missing_rationale'])
def test_live_data_guard_rejects_invalid_corpus(mutation):
    rows=cases()
    if mutation=='duplicate':rows[1]['requirement']='\n'+rows[0]['requirement']+'！'
    if mutation=='family_leak':
        dev=next(r for r in rows if r['split']=='dev');held=next(r for r in rows if r['split']=='holdout');held['group_id']=dev['group_id']
    if mutation=='missing_probe':rows[0]['extra_probe']=''
    if mutation=='wrong_probe':rows[0]['extra_probe']=rows[0]['extra_probe'].replace('TestEvalCase','TestIgnored')
    if mutation=='missing_rationale':rows[0]['family_rationale']=''
    with pytest.raises(ValueError):validate_live_cases(rows)

def test_old_mechanism_corpus_cannot_be_live_even_with_synthetic_authorization(tmp_path):
    old=freeze(tmp_path/'old','test')
    model=dict(name='fixed-version',revision='fixed-version',revision_verified=True,context_window=32768,
               endpoint='https://example.invalid/v1',temperature=0.2,sdk_retries=0)
    rates=dict(model=model['name'],endpoint=model['endpoint'],input_ceiling_per_million='1',output_ceiling_per_million='1',
               currency='TEST',verified_at='synthetic-only',includes_all_token_surcharges=True)
    old['protocol'].update(live_model=model,live_rates=rates);old['protocol']['targets']['live_total_cost_cap']='1'
    problems=live_preflight(old,'1',rates,str(tmp_path/'ledger'))
    assert any('机制条件' in p for p in problems)
    fresh=copy.deepcopy(old);fresh['cases']=cases();fresh['protocol']['dataset_purpose']='grouped-live-candidate-v2'
    assert live_preflight(fresh,'1',rates,str(tmp_path/'ledger'))==[]  # no clients, TEST is not currency authorization

def test_new_probes_are_scoring_only_and_missing_evidence_is_unknown():
    for case in cases():
        if not case['feasible']:
            assert label(case,None,refusal=False)['correct'] is False
            assert label(case,None,refusal=True)['correct'] is True
            continue
        scored=scoring_bundle(case,output(case['scenario']).bundle)
        assert any(f.name=='eval_case_test.go' and f.content==case['extra_probe'] for f in scored.files)
        assert label(case,None)['correct'] is None

@pytest.mark.skipif(os.environ.get('AIROBOT_TEST_DOCKER')!='1',reason='S8.1 genuine Docker case probes')
@pytest.mark.parametrize('case',[c for c in cases() if c['feasible']],ids=lambda c:c['id'])
def test_real_candidate_probe_executes_against_reference(case):
    checked=asyncio.run(score(case,output(case['scenario']).bundle))
    if os.environ.get('S81_PROBE_EVIDENCE'):
        folder=Path(os.environ['S81_PROBE_EVIDENCE']);folder.mkdir(parents=True,exist_ok=True)
        write_json(folder/(case['id']+'.json'),dict(case=case,independent=checked),exclusive=True)
    assert checked['correct'] is True,checked
    assert all(c['status']=='pass' for c in checked['checks'])
    assert checked['report']['container_removed'] is True

@pytest.mark.skipif(os.environ.get('AIROBOT_TEST_DOCKER')!='1',reason='S8.1 genuine Docker counterexample')
def test_real_new_empty_invalid_requirement_rejects_plausible_bug():
    case=next(c for c in cases() if c['group_id']=='worker_pool/invalid_workers')
    bundle=output('worker_pool').bundle
    bundle.files[0].content=bundle.files[0].content.replace('if workers<=0', 'if len(jobs)==0 {return []int{},nil}; if workers<=0')
    checked=asyncio.run(score(case,bundle))
    if os.environ.get('S81_PROBE_EVIDENCE'):
        write_json(Path(os.environ['S81_PROBE_EVIDENCE'])/'counterexample.json',dict(case=case,independent=checked),exclusive=True)
    assert checked['correct'] is False
    assert next(c for c in checked['checks'] if c['id']=='r-case')['status']=='fail'
    assert checked['report']['container_removed'] is True
