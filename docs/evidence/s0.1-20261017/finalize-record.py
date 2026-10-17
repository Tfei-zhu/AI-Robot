"""Append S0.1 results and verify immutable S0/source evidence. No application changes."""
import ast,datetime,hashlib,importlib.util,json,pathlib,re,sys,xml.etree.ElementTree as ET
ROOT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest'); OUT=ROOT/'docs/evidence/s0.1-20261017'
sha=lambda b:hashlib.sha256(b).hexdigest()
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
spec=importlib.util.spec_from_file_location('s0',ROOT/'docs/evidence/s0-20261017/run_baseline.py');s0=importlib.util.module_from_spec(spec);spec.loader.exec_module(s0)
before=json.loads((OUT/'source-before.json').read_text());after={'latest':s0.snapshot(ROOT),'old':s0.snapshot(s0.OLD)}
assert before['latest']['files_sha256']==after['latest']['files_sha256']
assert before['latest']['tracked_diff_sha256']==after['latest']['tracked_diff_sha256']
assert before['old']==after['old'],'Old repository changed'
save('source-after.json',after)
s0files=json.loads((OUT/'s0-evidence-before.json').read_text())
assert all(sha((ROOT/name).read_bytes())==value for name,value in s0files.items()),'Historical S0 evidence modified'
previous_log=(OUT/'execution-log-before.md').read_bytes();log=ROOT/'docs/multi-agent-execution-log.md'
assert log.read_bytes()==previous_log,'Execution log changed externally; reconcile append'
old_artifacts=json.loads((ROOT/'docs/evidence/s0-20261017/artifact-manifest.json').read_text())
assert old_artifacts['files_sha256']['docs/multi-agent-execution-log.md']==sha(previous_log)
# Keep raw per-phase records. The aggregate corrects one metadata label; no output is rewritten.
rows=[]
for p in sorted(OUT.glob('*-commands.json')):
 for row in json.loads(p.read_text()):
  row={**row,'record_file':p.name}
  assert sha((OUT/row['output']).read_bytes())==row['output_sha256'],row['id']
  if row['id']=='token-cache-download':
   row['network_guard']=False
   row['metadata_note']='Public resource preparation intentionally used root-only PYTHONPATH. Raw phase row incorrectly labeled guarded=True; no offline guard loaded for this download.'
  rows.append(row)
rows.sort(key=lambda r:r['started_utc']);save('commands.json',rows)
def count_xml(name):
 tree=ET.parse(OUT/name); suites=list(tree.getroot().iter('testsuite'))
 fields={k:sum(int(s.get(k,'0')) for s in suites) for k in ['tests','failures','errors','skipped']}
 fields['passed']=fields['tests']-fields['failures']-fields['errors']-fields['skipped'];return fields
stats={name:count_xml(name+'.xml') for name in ['go-pytest','context-pytest','full-pytest','docker-pytest'] if (OUT/(name+'.xml')).exists()}
oldpackages=json.JSONDecoder().raw_decode((ROOT/'docs/evidence/s0-20261017/borrowed-packages.txt').read_text())[0]
packages=json.JSONDecoder().raw_decode((OUT/'packages.txt').read_text())[0]
normalize=lambda s:s.lower().replace('_','-').replace('.','-')
oldversions={normalize(p['name']):p['version'] for p in oldpackages}
newversions={normalize(p['name']):p['version'] for p in packages}
changes=[{'package':n,'before':v,'after':newversions[n]} for n,v in oldversions.items() if n in newversions and v!=newversions[n]]
added=[{'package':n,'version':v} for n,v in newversions.items() if n not in oldversions]
assert not changes,changes
witness=json.loads((OUT/'exception-witness-v2.json').read_text());assert not witness['missing']
token=json.loads((OUT/'token-cache.json').read_text());assert sha(pathlib.Path(token['cache_file']).read_bytes())==token['expected_sha256']
assert all((OUT/name).read_bytes()==b'' for name in ['offline-network-audit.txt','witness-v2-network-audit.txt','docker-test-network-audit.txt'])
image=json.loads((OUT/'docker-image-ready.txt').read_text())[0]
fixtures=json.loads((OUT/'go-fixtures-report.json').read_text())
assert len(fixtures['rows'])==len(json.loads((ROOT/'eval/go_cases.json').read_text()))
fixture_stats={'cases':len(fixtures['rows']),'final_passed':sum(r['final_pass'] for r in fixtures['rows']),'initial_passed':sum(r['initial_pass'] for r in fixtures['rows']),'validation_calls':sum(r['validation_calls'] for r in fixtures['rows']),'model_calls_fixture_only':sum(r['model_calls'] for r in fixtures['rows']),'all_containers_removed':all(a['validation']['container_removed'] for r in fixtures['results'] for a in r['attempts'])}
# Fixture calls count invocations of injected local models; they are not provider calls.
summary={'stage':'S0.1','completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(ROOT),'head':after['latest']['head'],'source_manifest_sha256':after['latest']['source_manifest_sha256'],'source_unchanged':True,'s0_evidence_unchanged':True,'s0_log_archived_sha256':sha(previous_log),'old_repository_unchanged':True,'environment':{'python':'3.13.13','path':str(ROOT/'.venv'),'core_version_changes':changes,'added_dev_packages':added,'venv_config':(ROOT/'.venv/pyvenv.cfg').read_text()},'pytest':stats,'hardening':{k:witness[k] for k in ['tests_run','failures','errors','skips','missing']},'go_fixtures':fixture_stats,'image':{k:image.get(k) for k in ['Id','RepoTags','RepoDigests','Os','Architecture']},'paid_model_embedding_ragas_calls':0,'unverified':['Playwright Dashboard','Python 3.11','remote CI','live models/Embedding/RAGAS (no cumulative spending cap)'],'operational_limitation':'Docker daemon direct Docker Hub manifest fetch timed out. Same official locked base successfully fetched with verified host HTTPS and supplied as OCI named context; persistent fixed validator image is ready.'}
save('summary.json',summary)
codes={r['id']:r['exit_code'] for r in rows}
core=['pip-check','token-cache-download','token-cache-offline','script-stability','script-integration','script-agent','script-tracing','hardening','agent-fixtures','go-pytest','context-pytest','full-pytest','hardening-exception-witness-v2','docker-build-oci','docker-pytest','go-fixtures']
assert all(codes.get(k)==0 for k in core),{k:codes.get(k) for k in core if codes.get(k)!=0}
assert fixture_stats['final_passed']==fixture_stats['cases'] and fixture_stats['all_containers_removed']
assert stats['docker-pytest']['failures']==stats['docker-pytest']['errors']==stats['docker-pytest']['skipped']==0
rootstr=str(ROOT)
start=min(r['started_utc'] for r in rows);end=summary['completed_at']
section=f'''

## S0.1 / T01 补验：独立环境、真实 Token 计量与基线恢复

执行日期：2026-10-17，Asia/Shanghai。本轮命令 UTC 起点 `{start}`，完成 `{end}`（当地时间约 11:28 起）。本轮记录追加于原 S0，不改写其失败、阻塞或通过结论；原日志完整快照见 [execution-log-before.md](evidence/s0.1-20261017/execution-log-before.md)。原 S0 证据文件逐一 SHA-256 校验未变，原 artifact-manifest 内日志摘要对应此快照；追加日志后不重生成旧清单。完整本轮结果见 [summary.json](evidence/s0.1-20261017/summary.json)，实际命令/起止/退出码/输出摘要见 [commands.json](evidence/s0.1-20261017/commands.json)。

目标与范围：恢复新版独立开发环境与真实 cl100k_base 计量，补跑原基线及真实 Docker 验收。仅新增本轮证据、独立 `.venv`（含可复用词表缓存/激活脚本）并追加本日志；没有实施 S1，没有修改生产代码、测试、依赖声明、CI 或项目 Dockerfile；旧项目只读，未安装包、未作为本轮验收解释器。没有裁剪测试集、pytest 替身、计数器替换或词表伪造。

### 源码与环境

HEAD/分支保持 `1ea7e6b7abbde3bd1a5963f03cd142fac553685a` / `main`。开始和结束的 tracked/staged diff 都为空，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；沿用 S0 指纹算法，132 文件清单 SHA-256 仍为 `{summary['source_manifest_sha256']}`，逐文件与原 S0 一致。新旧目录的前后快照见 [source-before.json](evidence/s0.1-20261017/source-before.json) / [source-after.json](evidence/s0.1-20261017/source-after.json)，原 S0 证据指纹见 [s0-evidence-before.json](evidence/s0.1-20261017/s0-evidence-before.json)。原有未跟踪计划文档及全部历史结果保留，未创建提交。

新版解释器：`{rootstr}/.venv/bin/python`，Python 3.13.13，`include-system-site-packages = false`。先从 S0 `borrowed-packages.txt` 生成 [s0-constraints.txt](evidence/s0.1-20261017/s0-constraints.txt)，运行 `python3 -m venv .venv`，再以有效 certifi CA、官方 PyPI、`-r requirements-dev.txt -c docs/evidence/s0.1-20261017/s0-constraints.txt` 安装。与 S0 共有的全部已安装包版本均未变化，关键版本保持 FastAPI 0.141.1、Pydantic 2.13.5、LangChain 1.3.18、langchain-core 1.6.1、langchain-openai 1.1.9、LangGraph 1.2.11、tiktoken 0.14.0、httpx 0.28.1、tenacity 8.5.0。新增缺失的开发依赖 pytest 9.1.1、pluggy 1.7.0、iniconfig 2.3.1；原因是原 S0 未安装 pytest。可选 RAGAS/重排依赖未安装。安装、`pip check` 均退出 0；实际解析/下载记录见 [pip-install-report.json](evidence/s0.1-20261017/pip-install-report.json)，完整版本见 [freeze.txt](evidence/s0.1-20261017/freeze.txt)。

网络分类：沙箱内 PyPI/词表域名 `gaierror [Errno 8]`，失败发生在 DNS 阶段，不能称为 TLS 错误；沙箱外两域名 DNS 成功，使用 pip 自带 certifi CA 访问公共资源均 HTTP 200，证明此前是沙箱内解析限制。安装后的真实词表下载改用新版 `.venv` 的 certifi。记录见 [network-sandbox.txt](evidence/s0.1-20261017/network-sandbox.txt)、[network-outside-sandbox.txt](evidence/s0.1-20261017/network-outside-sandbox.txt)。没有关闭 TLS 校验，没有 trusted-host；没有向旧环境安装包。

### 真实词表与离线边界

从当前安装的 `tiktoken_ext.openai_public.cl100k_base` AST 读取官方 URL 和 `expected_hash`，从 `https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken` 实际下载 {token['bytes']} 字节。词表 SHA-256 `{token['actual_sha256']}` 与该版本声明完全一致；缓存键按 tiktoken URL SHA-1 为 `{token['cache_key']}`。来源、CA 摘要、声明源码摘要和缓存路径见 [token-cache.json](evidence/s0.1-20261017/token-cache.json)。缓存位于新版 `.venv/tiktoken-cache`；可在项目根执行 `source .venv/activate-s01.sh` 复用解释器、缓存和 CA，未改 `.env`。

新进程在 DNS/IPv4/IPv6 connect 全部拦截条件下实际加载 cl100k_base（词表规模 100277），完成中英文 encode/decode 往返；见 [token-cache-offline.txt](evidence/s0.1-20261017/token-cache-offline.txt)，退出 0。断网保护自检实际触发预期拒绝，单独记账；业务测试的 [offline-network-audit.txt](evidence/s0.1-20261017/offline-network-audit.txt)、异常观测及 Docker Python 测试审计均为 0 字节，即没有业务外连尝试。公共资源准备与 Docker 镜像下载明确不属于离线测试；聚合 commands 对词表下载行的原始 `network_guard=true` 误标进行了透明更正，原始分阶段记录未覆盖。

测试子进程清除继承的 AIROBOT/OPENAI/LangChain/LangSmith 配置、禁止 dotenv、清空模型/Embedding 密钥及外部 Go/MQ 配置、关闭追踪与重排；固定模型与检索替身由原测试注入。真实模型、Embedding、RAGAS、live 和真实模型对照均未执行，费用调用 0；未得到累计费用上限，不据替身结果声称真实模型效果提升。

### 本轮实际运行结果

下表 `P` 为新版 `.venv/bin/python`，不是旧项目解释器。完整参数以 commands.json 为准；统计来自原脚本输出和实际 pytest JUnit XML，不把重叠运行次数相加作为独立覆盖量。

| 检查 / 实际命令 | 退出码 | 本次通过 / 失败 / 跳过 | 独立证据 |
| --- | --- | --- | --- |
| `P -m compileall -q app eval scripts tests`；服务导入冒烟 | 0 / 0 | 语法通过；新版模块路径确认、14 路由 | `syntax.txt`、`import-smoke.txt` |
| `P tests/test_stability.py` | 0 | 6 / 0 / 0 | `script-stability.txt` |
| `P tests/test_integration.py` | 0 | 12 / 0 / 0 | `script-integration.txt`；模拟 HTTP/检索 |
| `P tests/test_agent.py` | 0 | 5 / 0 / 0 | `script-agent.txt`；真实 LangGraph、固定模型 |
| `P tests/test_tracing.py` | 0 | 3 / 0 / 0 | `script-tracing.txt` |
| `P -m unittest discover -s tests -p test_hardening.py -v` | 0 | 26 / 0 / 0 | `hardening.txt` |
| `P eval/run_agent_eval.py` | 0 | 6 路径通过 / 0 / 0 | `agent-fixtures.txt`；knowledge/article/combined/failure/budget/direct |
| Go 专项 `P -m pytest tests/test_go_*.py -q -ra`（实际参数为四个文件逐一展开） | 0 | {stats['go-pytest']['passed']} / 0 / {stats['go-pytest']['skipped']} | `go-pytest.txt`、`go-pytest.xml`；真实沙箱开关未启用时的独立记录 |
| 上下文专项 `P -m pytest tests/test_context_*.py -q -ra`（实际逐一展开十个文件） | 0 | {stats['context-pytest']['passed']} / 0 / 0 | `context-pytest.txt`、`context-pytest.xml` |
| 完整离线 `P -m pytest tests -q -ra` | 0 | {stats['full-pytest']['passed']} / 0 / {stats['full-pytest']['skipped']}（共 {stats['full-pytest']['tests']}） | `full-pytest.txt`、`full-pytest.xml`；跳过仅原有真实 Docker 开关，下一行另行全部实际执行 |
| `AIROBOT_TEST_DOCKER=1 P -m pytest` 全部四个 Go 模块 | {codes['docker-pytest']} | {stats['docker-pytest']['passed']} / {stats['docker-pytest']['failures']+stats['docker-pytest']['errors']} / {stats['docker-pytest']['skipped']}（含上述 22 个真实沙箱用例） | `docker-pytest.txt`、`docker-pytest.xml` |
| `AIROBOT_TEST_DOCKER=1 P eval/run_go_eval.py --fixtures --output docs/evidence/s0.1-20261017/go-fixtures-report.json` | {codes['go-fixtures']} | {fixture_stats['final_passed']}/{fixture_stats['cases']} 最终通过；首次 {fixture_stats['initial_passed']}/{fixture_stats['cases']}，其余编译/行为缺陷被拦截并修复 | [go-fixtures-report.json](evidence/s0.1-20261017/go-fixtures-report.json)、`go-fixtures.txt`；真实 Docker，固定输出无模型请求 |

异常分支特别复核：保留原加固测试断言，额外通过源码异常事件和 SSE 观测记录：`test_stream_failure_does_not_commit_partial_answer` 实际输出 token `部分答案`，命中原 `tests/test_hardening.py:340` 的 `RuntimeError("流中断")` 后只发出 1 个 error，原内存未提交断言通过；没有以词表缺失替代预期错误。向量服务失败（42）、工作线程临时故障（249）、文章服务不可用（279）也都实际命中。见 [exception-witness-v2.json](evidence/s0.1-20261017/exception-witness-v2.json)。首次观测脚本只设置主线程 trace，漏记 249 的线程异常，补充观测命令退出 1（原 26 项仍通过），该失败原样保留于 `hardening-exception-witness.txt` / `exception-witness.json`。v2 新增 threading trace 后原 26 项通过、四处异常全部观测到、命令退出 0；这是证据脚本修正，没有修改基线测试或应用。本轮未发现需要修复的基线代码失败。

### 真实 Linux 沙箱与镜像恢复

Docker Desktop `desktop-linux` 引擎实际启动，Server 29.7.2、Linux/aarch64。原 `docker build -t airobot-go-validator:1.26.2 sandbox/go` 首次退出 1，原因是守护进程请求 Docker Hub 固定摘要 manifest 超时（约 121 秒）；不是 Go 编译失败，不是观察到的证书错误。失败与初始镜像缺失证据分别保留为 `docker-build.txt`、`docker-image.txt`。

宿主使用有效 CA 访问官方 registry/auth 成功，官方索引 SHA-256 与项目 Dockerfile 锁定值 `47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19` 完全一致；从此索引选择 Linux ARM64/v8 manifest `3fc85666d679424f406bbe27d9ffb24df50d5d800380f365c9e7cf6778072a75`，逐个校验 config 和全部 layers 摘要/长度，构建本地 OCI layout。随后使用 `docker build --build-context <原锁定镜像引用>=oci-layout:///<已校验目录>@sha256:<该平台manifest> -t airobot-go-validator:1.26.2 sandbox/go`，原项目 Dockerfile 和 runner/entrypoint 原样执行，退出 0。没有换基础版本、没有改源码、没有重置 Docker 数据、没有宿主 Go 验收或降级 TLS。两处镜像源探测只返回 HTTP 401，未用于最终镜像。实际源链与恢复命令见 [golang-oci-provenance.json](evidence/s0.1-20261017/golang-oci-provenance.json)、`oci-download.txt`、`docker-build-oci.txt`、`oci-recovery-commands.json`。

固定验证镜像 ID `{image['Id']}`，平台 linux/arm64，实际 inspect 见 [docker-image-ready.txt](evidence/s0.1-20261017/docker-image-ready.txt)。镜像已保存在 Docker 引擎中；OCI 中间下载目录 `/private/tmp/airobot-s01-golang-oci` 是临时资源，恢复脚本和完整摘要链保存在本轮证据中。Docker 守护进程直连 Hub 路径仍有网络限制，这是后续重新拉取镜像的操作限制，当前实际沙箱验收已完成。

真实沙箱测试覆盖编译/测试/vet/策略拦截、取消/超时/重复取消清理、非特权身份、只读文件系统、宿主秘密隔离、资源与断网配置、可信服务端测试保留，以及实际 JSON/SSE/账户隔离。9 条固定输出 Go 评测共 {fixture_stats['validation_calls']} 次实际验证、{fixture_stats['model_calls_fixture_only']} 次本地 FixtureModel 调用（不是外部模型请求），全部 attempt 的 `container_removed=true`；`docker-containers-after.txt` 中没有残留 `airobot-go-*` 容器。

### S1 条件与仍待验证项

S0.1 环境恢复与基线补验完成。S1（T04–T06）可开始：独立依赖/真实计量/原 Go 与上下文回归/固定真实沙箱已具备，可实现 TaskSpec、CodeArtifact、ReviewReport、RepairRequest 及旧报告默认值兼容；可实现最终可信文件 hash、绑定版本的审查/验证、必要需求完整性与无 blocking 的确定性判定；可实现角色配置、共享调用/重试/验证/截止时间预算和非法配置拒绝，并在本环境运行反例测试。上述是进入条件，不是声明 S1 已实现或 M1–M5 已完成。

仍待完成：Playwright 当前 MODULE_NOT_FOUND，Dashboard 浏览器验收未运行；本机仅 Python 3.13.13，Python 3.11 未安装/未验证；远程 CI 未触发/未验证；真实模型/Embedding/RAGAS/模型对照未执行，需明确累计费用上限后另行授权和记录。费用/延迟与真实模型质量无本轮结论；S1–S9 新增多 Agent 契约、闭环、预算、UI 等仍按实施计划逐步开发验证。操作性限制是 Docker 引擎直连 Hub manifest 超时，已有同摘要验证镜像可继续本地开发与验收。
'''
with log.open('ab') as f:f.write(section.encode())
assert log.read_bytes().startswith(previous_log)
(OUT/'finalize-record.py').write_bytes(pathlib.Path(__file__).read_bytes())
(OUT/'final-checks.txt').write_text('S0.1 final consistency: PASS\nSource and old repository unchanged; original S0 evidence files unchanged.\nOriginal execution log preserved as exact prefix and archived snapshot matching S0 manifest.\nAll command outputs verified by SHA-256; raw command metadata preserved, public-download guard label corrected in aggregate.\nIndependent environment core versions unchanged; real vocabulary expected_hash verified.\nOffline baseline and real Docker test/eval gates exited 0.\nNo paid provider calls; Docker test containers removed.\nCommand: PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/airobot_s01_finalize.py\nExit code: 0\n')
save('finalization-command.json',{'argv':[sys.executable,'/private/tmp/airobot_s01_finalize.py'],'cwd':str(ROOT),'exit_code':0,'record_script':'finalize-record.py','scope':'append execution log; snapshot and artifact checks; no behavior tests repeated'})
# All output files and the appended execution log get a new artifact manifest; original manifest is untouched.
artifacts={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json' and '__pycache__' not in p.parts}
artifacts['docs/multi-agent-execution-log.md']=sha(log.read_bytes())
save('artifact-manifest.json',{'algorithm':'sha256','source_manifest_sha256':summary['source_manifest_sha256'],'files_sha256':artifacts,'artifact_set_sha256':sha(json.dumps(artifacts,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())})
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('PASS: S0 historical files unchanged, original log prefix preserved, sources unchanged, new command output hashes verified, both baseline and real Docker gates passed.')
