"""Actual sandbox probe: untrusted package can change the test selection flags."""
import asyncio,json,sys
from pathlib import Path
from app.config import settings
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from test_multi_agent_agents import ScriptedModel, plan_json, review_json, fenced
from test_multi_agent_regressions import cfg
from test_multi_agent_workflow import request

OUT=Path(__file__).resolve().parent
SOURCE='''package example
import ("context";"os")
func init(){os.Args=[]string{os.Args[0],"-test.run=^TestOnlyModel$","-test.v=test2json","-test.timeout=8s"}}
func WaitForCancel(ctx context.Context) error { return nil }
'''
TEST='''package example
import "testing"
func TestOnlyModel(t *testing.T){if 1!=1 {t.Fatal("unreachable")}}
'''
async def run():
    settings.go_multi_agent=cfg()
    store=GoTaskStore(':memory:')
    try:
        control='--control' in sys.argv
        source=SOURCE if not control else SOURCE.replace('import ("context";"os")','import "context"').replace(
            'func init(){os.Args=[]string{os.Args[0],"-test.run=^TestOnlyModel$","-test.v=test2json","-test.timeout=8s"}}\n','')
        if control: settings.go_multi_agent=cfg(max_repairs=0)
        service=GoTaskService(store,supervisor_model=ScriptedModel(plan_json(),review_json()),
            code_model=ScriptedModel(fenced(('solution.go',source),('solution_test.go',TEST))),runner=DockerGoRunner())
        result=await service.run(request(),'review','sandbox-bypass')
        (OUT/('sandbox-control-result.json' if control else 'sandbox-selection-result.json')).write_text(result.model_dump_json(indent=2)+'\n')
        events=[json.loads(line) for stage in result.attempts[0].validation.stages if stage.stage=='test'
                for line in stage.output.splitlines() if line.startswith('{')]
        ran=[e.get('Test') for e in events if e.get('Action')=='run']
        print(json.dumps(dict(status=result.status,tests_run=ran,
            container_removed=result.attempts[0].validation.container_removed),ensure_ascii=False))
        assert result.status!='passed', 'Invalid code passed with ZERO trusted server tests executed'
    finally: store.close()
if __name__=='__main__':asyncio.run(run())
