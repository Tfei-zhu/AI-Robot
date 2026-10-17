"""Independent server-held Go probes. Neither agent verdict nor model tests label quality."""
import json
import time

from app.agents.go_workflow import machine_passed
from app.go_validation.contracts import CodeBundle, artifact_hash
from app.go_validation.fixtures import ACCEPTANCE_FILE, ACCEPTANCE_TESTS
from app.go_validation.runner import DockerGoRunner

PROBES = {
    "context_cancel": '''package example
import ("context";"testing";"time")
func TestEvalContextIdentity(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    if WaitForCancel(ctx)!=ctx.Err(){t.Fatal("must return exact ctx.Err, not only errors.Is")}
    deadline,stop:=context.WithTimeout(context.Background(),time.Millisecond);defer stop()
    if WaitForCancel(deadline)!=context.DeadlineExceeded{t.Fatal("deadline identity")}
}
func TestEvalContextWait(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());defer cancel()
    done:=make(chan error,1);go func(){done<-WaitForCancel(ctx)}()
    select {case <-done:t.Fatal("returned before cancellation");case <-time.After(12*time.Millisecond):}
    cancel();select {case err:=<-done:if err!=context.Canceled{t.Fatal(err)};case <-time.After(time.Second):t.Fatal("cancel ignored")}
}
''',
    "worker_pool": '''package example
import ("context";"reflect";"runtime";"testing")
func TestEvalPoolValues(t *testing.T) {
    jobs:=[]int{VALUES};original:=append([]int{},jobs...)
    want:=make([]int,len(jobs));for i,x:=range jobs{want[i]=x*2}
    for _,w:=range []int{1,3,100}{out,err:=WorkerPool(context.Background(),jobs,w)
        if err!=nil||!reflect.DeepEqual(out,want)||!reflect.DeepEqual(jobs,original){t.Fatal(out,err,jobs)}}
}
func TestEvalPoolBound(t *testing.T) {
    baseline:=runtime.NumGoroutine();done:=make(chan error,1)
    jobs:=make([]int,65536)
    go func(){_,err:=WorkerPool(context.Background(),jobs,3);done<-err}()
    for { select {case err:=<-done:if err!=nil{t.Fatal(err)};return;default:}
        if runtime.NumGoroutine()>baseline+3+4{t.Fatal("observed excessive goroutines")};runtime.Gosched() }
}
func TestEvalPoolCancel(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    if _,err:=WorkerPool(ctx,[]int{1},2);err==nil{t.Fatal("cancel ignored")}
    if _,err:=WorkerPool(context.Background(),[]int{1},0);err==nil{t.Fatal("invalid workers accepted")}
}
''',
    "channel": '''package example
import ("context";"testing";"time")
func TestEvalChannelValues(t *testing.T) {
    values:=[]int{VALUES};ch:=make(chan int,len(values));want:=0
    for _,x:=range values{ch<-x;want+=x};close(ch)
    got,err:=SumChannel(context.Background(),ch);if err!=nil||got!=want{t.Fatal(got,err,want)}
}
func TestEvalChannelPartialCancel(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());defer cancel()
    ch:=make(chan int);done:=make(chan struct{n int;err error},1)
    go func(){n,e:=SumChannel(ctx,ch);done<-struct{n int;err error}{n,e}}()
    ch<-17;ch<-(-4);cancel()
    select {case got:=<-done:if got.n!=13||got.err!=context.Canceled{t.Fatal(got)};case <-time.After(time.Second):t.Fatal("cancel ignored")}
}
''',
}


def probe_source(case,source_names):
    content=PROBES[case["scenario"]].replace("VALUES",",".join(map(str,case["values"])))
    if case.get("marker"):
        # Go AST attaches a comment to the actual exported function; a marker
        # elsewhere (including model tests or string literals) does not suffice.
        target={"context_cancel":"WaitForCancel","worker_pool":"WorkerPool","channel":"SumChannel"}[case["scenario"]]
        imports='import ("go/ast";"go/parser";"go/token";"strings";"testing")\n'
        body='func TestEvalRequiredDoc(t *testing.T) { found:=false\n'
        body+='for _,name:=range []string{'+",".join(json.dumps(n) for n in source_names)+'}{\n'
        body+='file,err:=parser.ParseFile(token.NewFileSet(),name,nil,parser.ParseComments);if err!=nil{t.Fatal(err)}\n'
        body+='for _,d:=range file.Decls { f,ok:=d.(*ast.FuncDecl);if ok && f.Name.Name=='+json.dumps(target)+' && f.Doc!=nil && strings.Contains(f.Doc.Text(),'+json.dumps(case["marker"],ensure_ascii=False)+'){found=true} } }\n'
        body+='if !found {t.Fatal("required public function comment missing")} }\n'
        return content, "package example\n"+imports+body
    return content,None


def scoring_bundle(case,bundle):
    # Discard model test assertions and inject probes separately. The workflow
    # artifact hash is retained separately; the scorer input has its own hash.
    sources=[f.model_dump() for f in bundle.files if not f.name.endswith("_test.go")]
    probes,doc=probe_source(case,[f["name"] for f in sources])
    files=[*sources,{"name":ACCEPTANCE_FILE,"content":ACCEPTANCE_TESTS[case["scenario"]]},
           {"name":"eval_independent_test.go","content":probes}]
    if doc:files.append({"name":"eval_requirements_test.go","content":doc})
    if case.get("extra_probe"):
        files.append({"name":"eval_case_test.go","content":case["extra_probe"]})
    return CodeBundle(files=files)


def label(case,report,*,artifact=None,scorer_hash=None,refusal=False):
    # approve is deliberately absent from this API.
    if not case["feasible"]:
        checks=[dict(id=r["id"],status="pass" if refusal else "fail",tests=r["tests"]) for r in case["checklist"]]
        return dict(correct=bool(refusal),checks=checks,reason="explicit_server_refusal" if refusal else "infeasible_request_not_rejected",
                    artifact_hash=artifact,scorer_input_hash=scorer_hash,report=None)
    actions={}
    if report is not None:
        for stage in report.stages:
            if stage.stage!="test":continue
            for line in stage.output.splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get("Test") and event.get("Action") in {"pass","fail","skip"}:
                    actions[event["Test"]]=event["Action"]
    checks=[]
    for requirement in case["checklist"]:
        states=[actions.get(name,"unknown") for name in requirement["tests"]]
        status="pass" if all(s=="pass" for s in states) else "fail" if "fail" in states or "skip" in states else "unknown"
        checks.append(dict(id=requirement["id"],status=status,tests=requirement["tests"]))
    verified=bool(report and (report.status=="failed" or
                  (machine_passed(report) and all(c["status"]!="unknown" for c in checks))))
    complete=bool(report and machine_passed(report)) and all(c["status"]=="pass" for c in checks)
    return dict(correct=complete if verified else None,checks=checks,
                reason="independent_pass" if complete else "independent_failure" if verified else "unverified",
                artifact_hash=artifact,scorer_input_hash=scorer_hash,report=report.model_dump() if report else None)


async def score(case,bundle,*,refusal=False,runner=None):
    started=time.perf_counter()
    original=artifact_hash(bundle.files) if bundle else None
    if not case["feasible"] or bundle is None:
        result=label(case,None,artifact=original,refusal=refusal)
    else:
        independent=scoring_bundle(case,bundle)
        scorer_hash=artifact_hash(independent.files)
        report=await (runner or DockerGoRunner()).validate(independent)
        if report.artifact_hash!=scorer_hash:
            raise ValueError("Independent validator report hash mismatch")
        result=label(case,report,artifact=original,scorer_hash=scorer_hash)
        result["scorer_files"]=[f.model_dump() for f in independent.files]
    result["elapsed_ms"]=round((time.perf_counter()-started)*1000,2)
    return result
