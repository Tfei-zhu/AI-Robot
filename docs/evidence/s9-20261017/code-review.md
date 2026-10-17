# S9 源码/文档自查（非独立第三方审查）

绑定完整源码清单 `b0a72a1788389b3c883e50a7fa42fe56c5e0be4e13a8bbd947834badb8d77709`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`。本轮不改变产品核心或测试/评测源码，仅增加固定模型回退演练脚本、CI 配置和文档。

- 回退脚本在 fresh process 读取实际 enabled=false，拒绝 true；ASGI 请求使用真实 GoTaskService/SQLite/Docker，生成客户端为 FixtureModel，主/子角色为被调用即失败的 ForbiddenRole。JSON/SSE、修复成功、修复耗尽和当前账户旧报告均按业务字段检查，不以 HTTP200 通过。
- 旧报告直接插入既有原始 JSON 再重开库，保留源码/日志及 multi 审查；GET 不创建模型调用。没有将其称作任务恢复。生产 .env、data/go_tasks.sqlite3 和运行中的服务未修改。
- 普通聊天六个案例调用现有 graph，固定模型/工具替身，不是普通聊天自动委派。产品 app 与当前所有原有 tests/eval/sandbox 字节不变。
- 文档T05明确 clarification_needed 无可达路径；T26/T27阻塞；T28整体待验证；没有用枚举/通过机制测试承诺正式澄清、真实模型准确率或任务恢复。
- CI 修改只扩大固定模型/真实 Docker 回归与回退覆盖，移除原先仅凭 Secrets 就运行 RAGAS 的路径；真实评测仍需冻结金额与账本。只做本地 YAML/结构/源文件语法检查，不宣称远程 runner 通过。
- 完成项限制在本地机制范围，A10不代表真实模型抗注入、A03不代表任意需求识别，保持默认开关false。已知旧机制留出25%和数据效度限制保留。

最后实现修改后回归结果、实际回退重跑、节点映射、源码归档和旧证据保全将由 verify_delivery.py 检查；证据缺失则检查失败。

实际客户端计数断言已补强：GET前后比较8个保留客户端的 calls，而非已汇总表格；最终回退须 model_calls_during_report_reads=0。此前回退输出保留为中间版本。
