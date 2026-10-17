"""Local rollback drill: real ASGI/SQLite/Docker, scripted models only.

Run in a fresh process with AIROBOT_GO_MULTI_AGENT_ENABLED=false.
Never loads .env or constructs provider clients. Does not touch production SQLite.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['PYTHON_DOTENV_DISABLED']='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def check(folder,multi_report=None):
    from httpx import ASGITransport,AsyncClient
    import app.main as main
    from app.config import settings
    from app.go_validation.service import GoTaskService
    from app.go_validation.store import GoTaskStore
    from app.go_validation.runner import DockerGoRunner
    from eval.go_fixtures import FixtureModel
    from eval.run_agent_eval import evaluate as chat_evaluate
    from eval.multi_agent_protocol import write_json
    if settings.go_multi_agent.enabled:
        raise ValueError('Rollback drill requires actual environment AIROBOT_GO_MULTI_AGENT_ENABLED=false')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    settings.admin_token='rollback-local-test';settings.ai_internal_token='rollback-internal-test';settings.ratelimit_enabled=False
    headers={'X-Internal-Token':'rollback-internal-test','X-Account-Id':'1'}
    owner=hashlib.sha256(b'account/1').hexdigest()
    store=GoTaskStore(str(folder/'reports.sqlite3'))
    # Insert historical JSON as it was saved, without new-model serialization.
    legacy=json.loads((ROOT/'docs/go-validation-fixture-report.json').read_text())['results']
    original={r['run_id']:r for r in legacy}
    if multi_report:
        multi=json.loads(Path(multi_report).read_text())
        if multi.get('workflow_version')!='multi-v1':raise ValueError('Expected actual multi-v1 report')
        original[multi['run_id']]=multi
    for row in original.values():
        store._db().execute('INSERT INTO go_tasks VALUES (?,?,?)',(row['run_id'],owner,json.dumps(row,ensure_ascii=False)))
    store._db().commit();store.close()
    store=GoTaskStore(store.path);main.go_store=store
    class ForbiddenRole:
        calls=0
        async def ainvoke(self,_):
            self.calls+=1;raise AssertionError('Disabled multi-agent role was invoked')
    role=ForbiddenRole();retrievals=0
    async def retrieve(_):
        nonlocal retrievals
        retrievals+=1;return {'chunks':[],'sources':[]}
    trials=[];read_checks=[];models=[]
    try:
        async with AsyncClient(transport=ASGITransport(app=main.app),base_url='http://rollback.test') as client:
            for scenario in ('context_cancel','worker_pool','channel'):
                for transport in ('json','sse'):
                    model=FixtureModel(scenario,'correct')
                    models.append(model)
                    main.go_service=GoTaskService(store,model=model,runner=DockerGoRunner(),retrieve=retrieve,
                        supervisor_model=role,code_model=role)
                    request=dict(scenario=scenario,requirement='按固定接口实现并满足全部服务端验收条件',session_id='rollback-'+scenario+'-'+transport)
                    response=await client.post('/api/v1/go/tasks'+('/stream' if transport=='sse' else ''),headers=headers,json=request)
                    assert response.status_code==200
                    if transport=='sse':
                        events=[json.loads(s[6:]) for s in response.text.splitlines() if s.startswith('data: ')]
                        assert events[-1]['type']=='go_done'
                        assert all(e['run_id']==events[0]['run_id'] for e in events)
                        result=events[-1]['result'];write_json(folder/(scenario+'-events.json'),events,exclusive=True)
                    else:result=response.json()
                    assert result['workflow_version']=='single-v1' and result['status']=='passed'
                    assert result['reviews']==result['artifacts']==[] and result['model_calls']==model.calls==1
                    assert result['validation_calls']==1 and result['attempts'][0]['validation']['container_removed']
                    assert (await client.get('/api/v1/go/tasks/'+result['run_id'],headers=headers)).json()==result
                    write_json(folder/(scenario+'-'+transport+'.json'),result,exclusive=True)
                    trials.append(dict(scenario=scenario,transport=transport,status=result['status'],actual_calls=model.calls,validation_calls=result['validation_calls']))
            for variant,expected,attempts in (('compile_error','passed',2),('persistent_bad','failed',3)):
                class Bad(FixtureModel):
                    async def ainvoke(self,messages):
                        from eval.go_fixtures import output
                        self.calls+=1;return output('channel','behavior_error')
                model=Bad('channel','behavior_error') if variant=='persistent_bad' else FixtureModel('channel',variant)
                models.append(model)
                main.go_service=GoTaskService(store,model=model,runner=DockerGoRunner(),retrieve=retrieve,
                                              supervisor_model=role,code_model=role)
                response=await client.post('/api/v1/go/tasks',headers=headers,json=dict(scenario='channel',requirement='求和并支持取消',session_id=variant))
                result=response.json();assert response.status_code==200 and result['status']==expected
                assert result['workflow_version']=='single-v1' and len(result['attempts'])==attempts
                assert model.calls==result['model_calls']==result['validation_calls']==attempts
                assert result['attempts'][0]['validation']['status']=='failed'
                assert all(a['validation']['container_removed'] for a in result['attempts'])
                write_json(folder/(variant+'.json'),result,exclusive=True)
                trials.append(dict(scenario='channel',transport='json',variant=variant,status=expected,actual_calls=model.calls,validation_calls=result['validation_calls']))
            before_calls=sum(model.calls for model in models)
            assert before_calls==sum(r['actual_calls'] for r in trials)
            for run_id,old in original.items():
                response=await client.get('/api/v1/go/tasks/'+run_id,headers=headers)
                current=response.json();assert response.status_code==200
                assert current['status']==old['status'] and current['attempts']
                assert current['workflow_version']==old.get('workflow_version','single-v1')
                # Source/log content and existing review evidence must survive normalization.
                for saved,loaded in zip(old['attempts'],current['attempts']):
                    assert saved['bundle']==loaded['bundle'] and saved['validation']['stages']==loaded['validation']['stages']
                if 'reviews' in old:assert current['reviews']==old['reviews']
                else:assert current['reviews']==[] and current['task_spec'] is None
                denied=await client.get('/api/v1/go/tasks/'+run_id,headers={**headers,'X-Account-Id':'2'})
                assert denied.status_code==404
                read_checks.append(dict(run_id=run_id,workflow_version=current['workflow_version'],status=current['status'],other_account=404))
                write_json(folder/('read-'+run_id+'.json'),current,exclusive=True)
            assert sum(model.calls for model in models)==before_calls
        chat=await chat_evaluate()  # six fixed-model direct/tool/article/error/budget cases
        assert len(chat)==6 and all(row['passed'] for row in chat)
        assert role.calls==0
        result=dict(status='passed',enabled=settings.go_multi_agent.enabled,configuration_source='fresh_process_environment',
            model_source='scripted_nonbillable',docker='real',provider_requests=0,multi_role_calls=role.calls,
            trials=trials,legacy_reports=len(legacy),reopened_report_checks=read_checks,ordinary_chat=chat,
            actual_fixture_calls=sum(model.calls for model in models),retrieval_calls=retrievals,
            model_calls_during_report_reads=sum(model.calls for model in models)-before_calls,
            report_reopen='passed',task_resume='not_implemented; reopening only reads stored JSON')
        write_json(folder/'summary.json',result,exclusive=True)
        print(json.dumps(result,ensure_ascii=False))
    finally:store.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--multi-report')
    args=parser.parse_args();asyncio.run(check(args.output,args.multi_report))
