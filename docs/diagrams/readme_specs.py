"""README 图示：只保留主链与关键分支，完整解释留在 notes。"""
DIAGRAMS=[]


def node(key,title,sub='',x=0,y=200,w=240,h=100,kind='rect',optional=False):
    return dict(id=key,title=title,sub=sub,x=x,y=y,width=w,height=h,kind=kind,optional=optional)


def edge(source,target,points,label='',label_at=None):
    return dict(source=source,target=target,points=points,label=label,label_at=label_at)


def add(key,title,caption,nodes,edges,height=460):
    DIAGRAMS.append(dict(id=key,title=title,caption=caption,width=1400,height=height,nodes=nodes,edges=edges))
    return DIAGRAMS[-1]


def chain(key,title,caption,labels):
    # 单行最多五步；六步采用两行蛇形，字号保持可读。
    n=len(labels)
    if n<=5:
        w=220 if n==5 else 260
        gap=50 if n==5 else 70
        start=(1400-(n*w+(n-1)*gap))/2
        positions=[(start+i*(w+gap),200) for i in range(n)]
        height=460
    else:
        w=240;positions=[(100,200),(580,200),(1060,200),(1060,420),(580,420),(100,420)]
        height=660
    nodes=[node(f'n{i}',*label,x=positions[i][0],y=positions[i][1],w=w) for i,label in enumerate(labels)]
    edges=[]
    for a,b in zip(nodes,nodes[1:]):
        if a['y']==b['y']:
            points=[(a['x']+w,a['y']+50),(b['x'],b['y']+50)] if b['x']>a['x'] else [(a['x'],a['y']+50),(b['x']+w,b['y']+50)]
        else:points=[(a['x']+w/2,a['y']+100),(b['x']+w/2,b['y'])]
        edges.append(edge(a['id'],b['id'],points))
    return add(key,title,caption,nodes,edges,height)


# 01：三条独立业务路径，不把文章事件误画成 HTTP 上传请求。
nodes=[];edges=[]
rows=[ [('普通聊天','JSON / SSE'),('聊天服务','缓存或单智能体'),('回答与来源','JSON / SSE 返回')],
       [('Go 专用任务','JSON / SSE'),('GoTaskService','生成、验证与修复'),('任务报告','可按账户重新读取')],
       [('文件 / 文章','管理员上传或事件'),('知识库 kb','解析、分块与索引'),('可检索知识','原文与来源')]]
for r,labels in enumerate(rows):
    for c,label in enumerate(labels):nodes.append(node(f'r{r}c{c}',*label,x=[100,580,1060][c],y=180+r*180))
    edges.extend([edge(f'r{r}c0',f'r{r}c1',[(340,230+r*180),(580,230+r*180)]),edge(f'r{r}c1',f'r{r}c2',[(820,230+r*180),(1060,230+r*180)])])
add('01-architecture-01','三条业务主线','聊天与 Go 任务分别编排；知识入库直接进入 kb。',nodes,edges,740)
nodes=[node('services','业务组件','各自维护索引、状态与持久化数据',60,180,1280)]
for i,(key,title,sub,opt) in enumerate([('memory','进程内','索引 / 会话 / 缓存',False),('sqlite','SQLite','分块 / 文章 / Go 报告',False),('milvus','Milvus','可选向量后端',True),('context','上下文库','默认 off',True)]):
    nodes.append(node(key,title,sub,100+i*320,420,optional=opt))
add('01-architecture-02','索引与存储边界','Milvus 只替代内存向量；BM25 始终留在进程内。',nodes,[edge('services',n['id'],[(n['x']+120,280),(n['x']+120,420)]) for n in nodes[1:]],620)

# 02：请求生命周期保留真实顺序，错误全集不再塞进图片。
chain('02-request-lifecycle-01','请求进入服务','放行主链：限流先于日志；会话占用仅适用于聊天与 Go POST。',[
    ('HTTP 请求','进入服务'),('鉴权与读体','仅受保护 API'),('限流检查','按 principal'),('日志开始计时','await call_next'),('参数与会话','校验后再占用'),('业务路由','JSON 或 SSE')])
nodes=[node('run','执行业务','聊天 / Go / 其他',100,200),node('release','路由收尾','Chat / Go 释放会话',580,200),node('json','JSON 序列化','校验输出',1060,200),node('handled','已处理异常','HTTPException 等',100,420),node('log','请求日志','状态与耗时头',580,420),node('send','发送 JSON','返回客户端',1060,420)]
edges=[edge('run','release',[(340,250),(580,250)]),edge('release','json',[(820,250),(1060,250)]),edge('release','handled',[(700,300),(700,330),(220,330),(220,420)],'已注册异常',(400,367)),edge('handled','log',[(340,470),(580,470)]),edge('json','log',[(1180,300),(1180,370),(700,370),(700,420)]),edge('log','send',[(820,470),(1060,470)])]
add('02-request-lifecycle-02','普通 JSON 返回','正常与已处理错误的回程；外层 500 和取消边界见说明。',nodes,edges,650)
d=chain('02-request-lifecycle-03','SSE 建立与结束','响应已开始后不改发 JSON 500；内层关闭按接口区分。',[
    ('校验与会话','路由前置检查'),('建立 SSE','HTTP 200'),('消费业务流','持续推送事件'),('按接口清理','Go / 聊天有差异'),('释放会话','响应层 finally')])
d['nodes'].append(node('interrupted','断开 / 异常','或实际任务取消',590,420,220))
d['edges'] += [edge('n2','interrupted',[(700,300),(700,420)]),edge('interrupted','n3',[(810,470),(970,470),(970,300)])]
d['height']=620
chain('02-request-lifecycle-04','Go 任务执行与收尾','JSON / SSE 共用；保护段内取消保存 cancelled 后重抛。',[
    ('初始报告','running'),('首次事件','go_start'),('排队与执行','Semaphore(2)'),('清理与释放槽','取得槽后才适用'),('保存终态报告','成功 / 失败 / 超时'),('记录与返回','trace → go_done')])

# 03：缓存检查在加载完整历史之前；规划与最终生成保持分离。
nodes=[node('input','输入问题','内部会话键',60,200,260),node('cache','首轮缓存','满足条件才查询',400,200,260),node('history','加载历史','按需准备摘要',740,200,260),node('agent','单智能体循环','规划与只读工具',1080,200,260),node('cached','缓存答复','不调用生成模型',400,420,260),node('final','finalize 回答','独立生成最终答案',1080,420,260),node('commit','提交并返回','会话与运行轨迹',740,420,260)]
edges=[edge('input','cache',[(320,250),(400,250)]),edge('cache','history',[(660,250),(740,250)],'未命中',(700,220)),edge('history','agent',[(1000,250),(1080,250)]),edge('agent','final',[(1210,300),(1210,420)]),edge('final','commit',[(1080,470),(1000,470)]),edge('cache','cached',[(530,300),(530,420)],'命中',(600,365)),edge('cached','commit',[(660,470),(740,470)])]
add('03-chat-agent-01','普通聊天：缓存与智能体','缓存检查先于完整历史加载；规划文本不直接作为最终答复。',nodes,edges,650)
d=chain('03-chat-agent-02','一轮只读工具调用','工具由模型选择，服务端校验后顺序执行；预算异常直接中止。',[
    ('tool_calls','模型提出调用'),('白名单校验','工具与参数'),('顺序执行','检索 / 文章 / 规范'),('ToolMessage','成功或错误结果'),('继续规划','仍受轮次限制')])
d['nodes'].append(node('budget','预算异常','中止本轮',590,420,220))
d['edges'].append(edge('n2','budget',[(700,300),(700,420)],'预算不足',(805,365)))
d['height']=620

# 04：三个入口共享索引子流程，正文、原文和索引的保存顺序不同。
chain('04-knowledge-ingestion-01','管理员上传文件','支持 PDF、DOCX、Markdown、TXT；入库不经过智能体。',[
    ('管理员上传','/api/v1/ingest'),('校验文件','权限 / 大小 / 类型'),('解析与分块','保留来源元数据'),('写入索引','共享入库流程'),('清理并返回','删除临时文件')])
chain('04-knowledge-ingestion-02','文章发布事件入库','正文先落库；失败重投，到达上限后登记并确认。',[
    ('接收文章事件','RabbitMQ'),('校验与去重','article_id'),('取得正文','优先使用本地'),('保存正文','pending'),('分块与索引','共享入库流程'),('状态与确认','ingested / ACK')])
chain('04-knowledge-ingestion-03','启动恢复已有知识','知识分块 → 样例检查 → 文章恢复；就绪不代表依赖全部可用。',[
    ('恢复知识分块','重建已有索引'),('检查空库样例','符合条件才导入'),('恢复文章','本地正文重新分块'),('按配置启消费','AMQP_URL'),('服务就绪','开始接收请求')])
chain('04-knowledge-ingestion-04','共享索引写入顺序','恢复已有分块时跳过原文保存；跨存储没有统一事务。',[
    ('分块去重','正文 + 元数据'),('保存分块原文','persist=true 时'),('向量化与写入','内存或 Milvus'),('更新 BM25','进程内关键词索引'),('更新内存状态','数量 / ID / revision')])

# 05：向量与 BM25 按实际顺序执行，不画成必然并行。
d=chain('05-rag-retrieval-01','从查询到检索证据','混合路径顺序执行；重排不可用时保留原排序。',[
    ('向量召回','混合 15 / 纯向量 5'),('关键词召回','BM25 · 最多 15'),('排名融合','RRF · 最多 10'),('可选重排','不可用则保留排序'),('原文证据','默认最多 5 条')])
d['edges'].append(edge('n0','n3',[(160,300),(160,410),(970,410),(970,300)],'混合关闭或 BM25 未就绪：仅向量',(585,389)))
d['height']=520
chain('05-rag-retrieval-02','证据返回与最终生成','检索只提供原文与来源；回答由智能体另行生成。',[
    ('知识检索','search_knowledge'),('原文与来源','空结果也可正常返回'),('工具消息','enforce 可精简'),('Agent 规划','可继续调用工具'),('finalize 回答','汇总来源')])

# 06：默认和可选分支分开；最终成功由服务端判定。
nodes=[node('service','GoTaskService','任务创建与排队',580,150),node('switch','多智能体？','默认关闭',580,320,kind='diamond'),node('single','single-v1','生成 → 验证 → 修复',100,500),node('multi','multi-v1','规划 → 生成 → 审查',1060,500,optional=True),node('report','报告与响应','SQLite + JSON / SSE',580,680)]
edges=[edge('service','switch',[(700,250),(700,320)]),edge('switch','single',[(580,370),(220,370),(220,500)],'false · 默认',(355,347)),edge('switch','multi',[(820,370),(1180,370),(1180,500)],'true · 显式启用',(1040,347)),edge('single','report',[(220,600),(220,730),(580,730)]),edge('multi','report',[(1180,600),(1180,730),(820,730)])]
add('06-go-orchestration-01','Go 专用任务的两条分支','普通聊天不进入此分支；报告可重读，任务不能恢复执行。',nodes,edges,870)
d=chain('06-go-orchestration-02','多智能体：两个角色顺序协作','服务端驱动；只有 proceed 评估才进入后续生成。',[
    ('需求评估与规划','proceed 后按需检索'),('CodeAgent','生成或修复代码'),('Docker 验证','代码失败也可审查'),('Supervisor 审查','需求与验证证据'),('服务端判定','通过 / 修复 / 终止')])
d['edges'].append(edge('n4','n1',[(1240,300),(1240,410),(430,410),(430,300)],'允许继续才修复',(840,389)))
d['height']=520
nodes=[node('evidence','有效验证与审查','结构、版本已校验',100,200),node('passed-check','成功门禁？','机器 + 审查 + 需求',580,200,kind='diamond'),node('passed','passed','通过服务端判定',1060,200),node('repair-check','还能修复？','预算 / 轮次 / 进展',580,440,kind='diamond'),node('repair','继续 repair','生成下一版产物',1060,440),node('stop','终止并报告','保留实际失败原因',100,440)]
edges=[edge('evidence','passed-check',[(340,250),(580,250)]),edge('passed-check','passed',[(820,250),(1060,250)],'是',(940,221)),edge('passed-check','repair-check',[(700,300),(700,440)],'否',(770,379)),edge('repair-check','repair',[(820,490),(1060,490)],'是',(940,461)),edge('repair-check','stop',[(580,490),(340,490)],'否',(460,461))]
add('06-go-orchestration-03','服务端成功与修复门禁','这里只展开有效证据后的判定；模型审查不直接设置任务成功。',nodes,edges,660)

# 07：验收测试注入在编排层，容器退出和资源确认是不同步骤。
chain('07-go-sandbox-01','Go 代码进入隔离验证','验收测试由编排层注入；源码通过标准输入送入固定容器。',[
    ('代码包校验','实现与模型测试'),('注入验收测试','编排层负责'),('DockerGoRunner','发送代码包'),('固定容器','禁网 / 只读 / 限额'),('验证报告','包含清理结果')])
chain('07-go-sandbox-02','容器内的四阶段检查','顺序固定；任一步失败，就停止后续阶段。',[
    ('策略检查','policy / AST'),('编译检查','compile'),('静态检查','go vet'),('单元测试','go test'),('阶段报告','状态与日志')])
chain('07-go-sandbox-03','验证结束后的资源清理','成功、失败、超时、实际取消都要尝试清理；不回退到宿主执行。',[
    ('执行结束','收集实际状态'),('删除容器','docker rm -f'),('回收客户端','必要时终止并等待'),('确认清理结果','未确认不判成功'),('返回或继续抛出','取消继续传播')])

# 08：三个模式不可混画，enforce 只压缩模型视图。
nodes=[node('context','上下文接入','CONTEXT_MODE 默认 off',60,180,1280),node('off','off · 默认','最近历史，不做压缩',100,380),node('observe','observe','保持输入并计量',580,380),node('enforce','enforce','预算 / 摘要 / 证据',1060,380,optional=True),node('commit','执行并成功提交','按模式保存记忆或原文',60,600,1280)]
edges=[]
for key,cx in [('off',220),('observe',700),('enforce',1180)]:edges += [edge('context',key,[(cx,280),(cx,380)]),edge(key,'commit',[(cx,480),(cx,600)])]
add('08-context-management-01','上下文管理的三种模式','实验能力默认 off；enforce 压缩视图，不替代归档原文。',nodes,edges,800)
chain('08-context-management-02','摘要与模型输入预算','enforce：摘要失败保留原文；必要内容超预算时明确中止。',[
    ('历史与已有摘要','准备本轮上下文'),('按需增量摘要','成功前保留草稿'),('选择完整历史','按子开关处理'),('检查输入预算','必要内容不可硬删'),('模型消息视图','每次调用前构建')])
d=chain('08-context-management-03','工具结果精简与证据复用','仅 enforce 精简；原文另存，重复证据只增加引用。',[
    ('工具调用','进入工具执行层'),('复用或执行','会话 / 参数 / 版本'),('归档完整结果','保留 result_id'),('精简证据视图','正文去重与预算'),('ToolMessage','回填继续规划')])
d['edges'].append(edge('n0','n4',[(160,300),(160,410),(1240,410),(1240,300)],'off / observe：执行工具，保留原结果',(700,389)))
d['height']=520
chain('08-context-management-04','按需补读完整工具结果','仅 enforce；不存在则返回工具错误，预算不足则中止。',[
    ('出现补读线索','引用或 truncated'),('模型选择补读','read_tool_result'),('校验归属与参数','仅当前会话'),('按预算读取','返回 next_offset'),('回填继续规划','再次检查证据预算')])

# 09：三类证据独立，图中不把旧测试成绩当作当前模型质量。
nodes=[node('entry','选择验证范围','三类证据各自回答不同问题',60,180,1280),node('offline','离线机制','模拟外部依赖',100,380),node('integration','集成验证','Docker / 浏览器',580,380),node('live','真实模型评测','显式配置与预算',1060,380),node('decision','分别审查证据，人工决定启用','评测报告不自动修改功能开关',60,600,1280)]
edges=[]
for key,cx in [('offline',220),('integration',700),('live',1180)]:edges += [edge('entry',key,[(cx,280),(cx,380)]),edge(key,'decision',[(cx,480),(cx,600)])]
add('09-verification-evaluation-01','验证机制、集成与真实效果','三条支线独立；离线通过不等于真实模型质量达标。',nodes,edges,800)
chain('09-verification-evaluation-02','Go 多智能体对照评测','开发后留出；每次调用前预占费用，不自动启用功能。',[
    ('冻结版本','源码 / 数据 / 环境'),('预检与预算','不足则 blocked'),('运行对照','留痕并结算'),('独立评分','服务端探针与 Docker'),('人工验收','质量 / 费用 / 延迟')])
chain('09-verification-evaluation-03','上下文四组对照与验收','未完成才续跑，完整失败保留；门槛通过也不自动启用。',[
    ('A / B / C / D','生成各组原始报告'),('保存原始结果','质量 / 用量 / 延迟'),('按需续跑','原件与追加结果合并'),('自动比较门槛','可比性与质量效率'),('人工启用决策','未通过则保持 off')])

assert len(DIAGRAMS)==27
