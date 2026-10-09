"""人工编写的固定模型输出，用于复现真实编译器验证；不代表模型生成质量。"""
from app.go_validation.contracts import CodeBundle, GeneratedCode

CORRECT = {
    "context_cancel": '''package example
import "context"
// 等待取消或 deadline 到期，保留具体错误。
func WaitForCancel(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }
''',
    "worker_pool": '''package example
import ("context"; "fmt"; "sync")
// 固定 worker 数量，索引对应输出位置；不修改输入。
func WorkerPool(ctx context.Context, jobs []int, workers int) ([]int,error) {
    if workers<=0 { return nil,fmt.Errorf("workers 必须大于零") }
    if err:=ctx.Err();err!=nil {return nil,err}
    out:=make([]int,len(jobs));if len(jobs)==0{return out,nil}
    if workers>len(jobs){workers=len(jobs)}
    queue:=make(chan int);var wg sync.WaitGroup
    for n:=0;n<workers;n++ {wg.Add(1);go func(){defer wg.Done()
        for {select {case <-ctx.Done():return;case i,ok:=<-queue:if !ok{return};out[i]=jobs[i]*2}}
    }()}
    send: for i:=range jobs {select {case <-ctx.Done():break send;case queue<-i:}}
    close(queue);wg.Wait();if err:=ctx.Err();err!=nil{return nil,err};return out,nil
}
''',
    "channel": '''package example
import "context"
// nil channel 禁用读分支，取消仍可唤醒 select。
func SumChannel(ctx context.Context,input <-chan int)(int,error){
    sum:=0
    for {if err:=ctx.Err();err!=nil{return sum,err}
        select {case <-ctx.Done():return sum,ctx.Err()
        case v,ok:=<-input:if !ok{return sum,nil};sum+=v}
    }
}
''',
}

BEHAVIOR_ERROR = {
    "context_cancel": '''package example
import "context"
func WaitForCancel(ctx context.Context) error { return nil }
''',
    "worker_pool": '''package example
import "context"
func WorkerPool(ctx context.Context,jobs []int,workers int)([]int,error){return jobs,nil}
''',
    "channel": '''package example
import "context"
func SumChannel(ctx context.Context,input <-chan int)(int,error){return 0,nil}
''',
}

MODEL_TESTS = {
    "context_cancel": '''package example
import ("context";"errors";"testing")
func TestGeneratedCancelled(t *testing.T){ctx,cancel:=context.WithCancel(context.Background());cancel()
    if !errors.Is(WaitForCancel(ctx),context.Canceled){t.Fatal("取消错误")}}
''',
    "worker_pool": '''package example
import ("context";"testing")
func TestGeneratedPool(t *testing.T){out,err:=WorkerPool(context.Background(),[]int{2},1)
    if err!=nil||len(out)!=1||out[0]!=4{t.Fatal(out,err)}}
''',
    "channel": '''package example
import ("context";"testing")
func TestGeneratedChannel(t *testing.T){ch:=make(chan int,1);ch<-4;close(ch)
    sum,err:=SumChannel(context.Background(),ch);if err!=nil||sum!=4{t.Fatal(sum,err)}}
''',
}


def output(scenario, variant="correct"):
    content = BEHAVIOR_ERROR[scenario] if variant == "behavior_error" else CORRECT[scenario]
    if variant == "compile_error":
        content += "\nvar broken = missingIdentifier\n"
    return GeneratedCode(bundle=CodeBundle(files=[
        {"name": "solution.go", "content": content},
        {"name": "solution_test.go", "content": MODEL_TESTS[scenario]},
    ]), change_summary="人工固定样例：" + variant)


class FixtureModel:
    def __init__(self, scenario, variant):
        self.scenario, self.variant, self.calls = scenario, variant, 0

    async def ainvoke(self, messages):
        self.calls += 1
        # 首轮注入既定缺陷；后续提供人工正确实现，不能据此推断真实模型修复能力。
        return output(self.scenario, self.variant if self.calls == 1 else "correct")
