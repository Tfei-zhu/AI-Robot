"""Predeclared synthetic task families; no model generation or outcome-based selection."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
old=[json.loads(s) for s in (ROOT/'eval/multi_agent_cases.jsonl').read_text().splitlines()]
base={c['scenario']:c for c in old if c['id'].endswith('-01')}
rows=[]
def add(scenario,family,split,variant,requirement,body,imports='"context";"testing"',feasible=True):
    c=json.loads(json.dumps(base[scenario]));c.update(id=f'live2-{scenario}-{family}-{variant}',group_id=f'{scenario}/{family}',
        split=split,fixture_profile='clean',family_rationale=f'同一 {family} 调用结构的两个边界值变体整体分集；接口 {scenario} 仍与其他族相关。',
        requirement=base[scenario]['requirement']+' '+requirement,feasible=feasible)
    if feasible:
        name='TestEvalCase'+''.join(p.title() for p in (scenario+'_'+family+'_'+str(variant)).split('_'))
        c['extra_probe']='package example\nimport ('+imports+')\nfunc '+name+'(t *testing.T) {\n'+body+'\n}\n'
        c['checklist'].append(dict(id='r-case',text=requirement,tests=[name],required=True))
    else:
        c['extra_probe']=None;c['checklist']=[dict(id='r-refuse',text='服务端明确拒绝标准库政策冲突',tests=['server_refusal'],required=True)]
    rows.append(c)
for v in (1,2):
    n=3 if v==1 else 17
    add('context_cancel','broadcast','dev',v,f'同一个 context 由 {n} 个等待者共享，取消一次后每个调用都必须返回 context.Canceled。',f'''ctx,cancel:=context.WithCancel(context.Background());defer cancel()
    done:=make(chan error,{n});for i:=0;i<{n};i++ {{go func(){{done<-WaitForCancel(ctx)}}()}};cancel()
    for i:=0;i<{n};i++{{select{{case e:=<-done:if e!=context.Canceled{{t.Fatal(e)}};case <-time.After(time.Second):t.Fatal("waiter stuck")}}}}''','"context";"testing";"time"')
    depth=2 if v==1 else 7
    add('context_cancel','parent_tree','dev',v,f'构造 {depth} 层派生 context，取消根节点后最深节点必须返回 context.Canceled。',f'''root,cancel:=context.WithCancel(context.Background());defer cancel();ctx:=root
    for i:=0;i<{depth};i++{{next,stop:=context.WithCancel(ctx);defer stop();ctx=next}};cancel()
    if e:=WaitForCancel(ctx);e!=context.Canceled{{t.Fatal(e)}}''')
    ms=2 if v==1 else 20
    add('context_cancel','expired_deadline','dev',v,f'传入已在 {ms} 毫秒前到期的 context，返回的错误必须与该 context.Err() 完全相同。',f'''ctx,cancel:=context.WithDeadline(context.Background(),time.Now().Add(-{ms}*time.Millisecond));defer cancel()
    if e:=WaitForCancel(ctx);e!=ctx.Err()||e!=context.DeadlineExceeded{{t.Fatal(e)}}''','"context";"testing";"time"')
    n=1 if v==1 else 9
    add('context_cancel','child_isolation','holdout',v,f'父 context 下创建 {n} 个独立子 context；取消每个子节点并等待后，父节点仍须未取消。',f'''parent,stop:=context.WithCancel(context.Background());defer stop()
    for i:=0;i<{n};i++{{child,cancel:=context.WithCancel(parent);cancel();if e:=WaitForCancel(child);e!=context.Canceled{{t.Fatal(e)}}}}
    if parent.Err()!=nil{{t.Fatal("parent canceled")}}''')
    depth=1 if v==1 else 11
    add('context_cancel','value_wrappers','holdout',v,f'取消信号必须穿透 {depth} 层 WithValue 包装；调用后仍能读取最外层键值。',f'''ctx,cancel:=context.WithCancel(context.Background());defer cancel()
    for i:=0;i<{depth};i++{{ctx=context.WithValue(ctx,i,i+10)}};cancel()
    if e:=WaitForCancel(ctx);e!=context.Canceled{{t.Fatal(e)}}
    if ctx.Value({depth}-1)!={depth}+9{{t.Fatal("value changed")}}''')
    values=[0,-3,8] if v==1 else [21,21,-9,0,4]
    lit=','.join(map(str,values));want=','.join(str(x*2) for x in values)
    add('worker_pool','ordered_edges','dev',v,f'输入为 {values}、workers={v} 时，逐项乘二且重复值保留原位置；调用前后的输入必须相同。',f'''jobs:=[]int{{{lit}}};before:=append([]int{{}},jobs...)
    got,e:=WorkerPool(context.Background(),jobs,{v});if e!=nil||!reflect.DeepEqual(got,[]int{{{want}}})||!reflect.DeepEqual(jobs,before){{t.Fatal(got,e,jobs)}}''','"context";"testing";"reflect"')
    count=3 if v==1 else 12
    add('worker_pool','reuse','dev',v,f'连续调用 {count} 次，每次只处理本次单元素输入，不能复用上一次结果或保留旧任务。',f'''for i:=0;i<{count};i++{{got,e:=WorkerPool(context.Background(),[]int{{i-5}},2);if e!=nil||len(got)!=1||got[0]!=2*(i-5){{t.Fatal(got,e)}}}}''')
    worker=1 if v==1 else 32
    add('worker_pool','empty_input','dev',v,f'空输入、workers={worker} 时返回零长度结果和 nil 错误，不能等待不存在的任务。',f'''got,e:=WorkerPool(context.Background(),[]int{{}},{worker});if e!=nil||len(got)!=0{{t.Fatal(got,e)}}''')
    worker=0 if v==1 else -7
    add('worker_pool','invalid_workers','holdout',v,f'即使输入为空，workers={worker} 也必须返回非 nil 错误，不能因空输入提前报告成功。',f'''_,e:=WorkerPool(context.Background(),nil,{worker});if e==nil{{t.Fatal("invalid workers accepted on empty jobs")}}''')
    module='github.com/s8/externalpool' if v==1 else 'golang.org/x/sync/errgroup'
    add('worker_pool','policy_conflict','holdout',v,f'还必须实际导入并使用第三方模块 {module}。这与固定标准库限制冲突，不能满足时必须明确拒绝并返回 clarification_needed，不能悄悄忽略。','',feasible=False)
    values=[-5,0,12] if v==1 else [42,-42,6,6]
    lit=','.join(map(str,values))
    add('channel','buffered_values','dev',v,f'已关闭的缓冲 channel 包含 {values} 时须消费全部值并返回总和 {sum(values)} 与 nil 错误。',f'''ch:=make(chan int,{len(values)});for _,x:=range []int{{{lit}}}{{ch<-x}};close(ch)
    got,e:=SumChannel(context.Background(),ch);if e!=nil||got!={sum(values)}{{t.Fatal(got,e)}}''')
    count=3 if v==1 else 19
    add('channel','stream_close','dev',v,f'无缓冲 channel 从其他 goroutine 依次发送 1 到 {count} 后关闭，必须等待并返回完整总和 {count*(count+1)//2}。',f'''ch:=make(chan int);go func(){{defer close(ch);for i:=1;i<={count};i++{{ch<-i}}}}()
    got,e:=SumChannel(context.Background(),ch);if e!=nil||got!={count*(count+1)//2}{{t.Fatal(got,e)}}''')
    cap=0 if v==1 else 8
    add('channel','closed_empty','dev',v,f'容量为 {cap} 的空 channel 先关闭再传入，必须返回 0 和 nil 错误，不可将正常关闭当取消。',f'''ch:=make(chan int,{cap});close(ch);got,e:=SumChannel(context.Background(),ch);if e!=nil||got!=0{{t.Fatal(got,e)}}''')
    ms=3 if v==1 else 15
    add('channel','nil_deadline','holdout',v,f'nil channel 不会产生值，context 在 {ms} 毫秒后到期时须返回 0 和原始 context.DeadlineExceeded。',f'''ctx,cancel:=context.WithTimeout(context.Background(),{ms}*time.Millisecond);defer cancel()
    got,e:=SumChannel(ctx,nil);if got!=0||e!=context.DeadlineExceeded{{t.Fatal(got,e)}}''','"context";"testing";"time"')
    a,b=(23,-8) if v==1 else (-19,4)
    add('channel','partial_cancel','holdout',v,f'无缓冲 channel 成功发送 {a} 和 {b} 后取消，返回已接收部分和 {a+b} 及原始 context.Canceled，不可丢弃部分结果。',f'''ctx,cancel:=context.WithCancel(context.Background());defer cancel();ch:=make(chan int)
    done:=make(chan struct{{n int;e error}},1);go func(){{n,e:=SumChannel(ctx,ch);done<-struct{{n int;e error}}{{n,e}}}}()
    ch<-{a};ch<-{b};cancel();select{{case got:=<-done:if got.n!={a+b}||got.e!=context.Canceled{{t.Fatal(got)}};case <-time.After(time.Second):t.Fatal("cancel ignored")}}''','"context";"testing";"time"')
rows.sort(key=lambda c:c['id'])
(ROOT/'eval/multi_agent_live_cases.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False,separators=(',',':'))+'\n' for c in rows))
p=json.loads((ROOT/'eval/multi_agent_protocol.json').read_text());p.update(version='s8-live-candidate-v2',dataset_purpose='grouped-live-candidate-v2')
p['scoring']['version']='independent-go-tests-v2-case-probes'
p['interpretation']+=' New corpus: 30 synthetic requirements, 15 caller-pattern families split 9 dev/6 holdout, same three APIs. Dedup/group checks do not establish semantic independence or real-world representativeness. V1 results cannot label this corpus. Two policy conflicts retain the known refusal-path gap.'
(ROOT/'eval/multi_agent_live_protocol.json').write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
print(len(rows),'cases',len({c['requirement'] for c in rows}),'unique requirements',len({c['group_id'] for c in rows}),'families')
