"""人工确认的场景行为测试：服务端追加，模型不能删除或修改。"""
from app.go_validation.contracts import CodeBundle

ACCEPTANCE_FILE = "server_acceptance_test.go"
ACCEPTANCE_TESTS = {
    "context_cancel": '''package example
import ("context"; "errors"; "testing"; "time")
func TestServerAlreadyCancelled(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    if !errors.Is(WaitForCancel(ctx),context.Canceled) {t.Fatal("必须返回取消错误")}
}
func TestServerWaitsThenCancels(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());defer cancel()
    done:=make(chan error,1);go func(){done<-WaitForCancel(ctx)}()
    select {case <-done:t.Fatal("取消前不能提前返回");case <-time.After(20*time.Millisecond):}
    cancel()
    select {case err:=<-done:if !errors.Is(err,context.Canceled){t.Fatal(err)};case <-time.After(time.Second):t.Fatal("未响应取消")}
}
func TestServerDeadline(t *testing.T) {
    ctx,cancel:=context.WithTimeout(context.Background(),20*time.Millisecond);defer cancel()
    if !errors.Is(WaitForCancel(ctx),context.DeadlineExceeded){t.Fatal("必须传播超时")}
}
''',
    "worker_pool": '''package example
import ("context"; "reflect"; "testing")
func TestServerPoolValuesOrderAndInput(t *testing.T) {
    jobs:=[]int{4,-3,0,8,2}; original:=append([]int{},jobs...)
    out,err:=WorkerPool(context.Background(),jobs,2)
    if err!=nil||!reflect.DeepEqual(out,[]int{8,-6,0,16,4}){t.Fatalf("输出或顺序错误: %v %v",out,err)}
    if !reflect.DeepEqual(jobs,original){t.Fatal("修改了输入")}
}
func TestServerPoolInvalidWorkers(t *testing.T) {
    for _,n:=range []int{0,-1}{if _,err:=WorkerPool(context.Background(),[]int{1},n);err==nil{t.Fatal("非法 workers 必须报错")}}
}
func TestServerPoolCancelled(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    if _,err:=WorkerPool(ctx,[]int{1,2},2);err==nil{t.Fatal("取消必须报错")}
}
func TestServerPoolEmpty(t *testing.T) {
    out,err:=WorkerPool(context.Background(),nil,2)
    if err!=nil||len(out)!=0{t.Fatal("空任务处理错误")}
}
''',
    "channel": '''package example
import ("context"; "errors"; "testing"; "time")
func TestServerChannelSumAndClose(t *testing.T) {
    ch:=make(chan int,4);for _,v:=range []int{3,-1,0,8}{ch<-v};close(ch)
    sum,err:=SumChannel(context.Background(),ch)
    if err!=nil||sum!=10{t.Fatalf("求和错误: %v %v",sum,err)}
    empty:=make(chan int);close(empty)
    sum,err=SumChannel(context.Background(),empty)
    if err!=nil||sum!=0{t.Fatal("空 channel 错误")}
}
func TestServerNilChannelCancellation(t *testing.T) {
    ctx,cancel:=context.WithTimeout(context.Background(),30*time.Millisecond);defer cancel()
    if _,err:=SumChannel(ctx,nil);!errors.Is(err,context.DeadlineExceeded){t.Fatal("nil channel 必须响应取消")}
}
func TestServerChannelCancellation(t *testing.T) {
    ctx,cancel:=context.WithCancel(context.Background());cancel()
    if _,err:=SumChannel(ctx,make(chan int));!errors.Is(err,context.Canceled){t.Fatal("必须传播取消错误")}
}
''',
}


def with_acceptance_tests(bundle: CodeBundle, scenario: str) -> CodeBundle:
    if any(f.name.lower() == ACCEPTANCE_FILE for f in bundle.files):
        raise ValueError("模型不能提交服务端验收测试文件")
    # 为可信测试预留一个文件位置；合并后仍受 8 文件、64KiB 总量限制。
    return CodeBundle(files=[*bundle.files, {"name": ACCEPTANCE_FILE, "content": ACCEPTANCE_TESTS[scenario]}])
