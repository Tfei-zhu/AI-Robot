"""Resolve every A01-A18 selector to actual JUnit records; missing != passed."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def matches(case, selector):
    parts = selector.split("::")
    module = parts[0].removesuffix(".py").replace("/", ".")
    classname, name = case.get("classname", ""), case.get("name", "")
    if len(parts) == 1:
        return classname == module or classname.startswith(module + ".")
    expected = module + ("." + parts[1] if len(parts) == 3 else "")
    function = parts[-1]
    return classname == expected and (name == function or name.startswith(function + "["))


def main():
    final = OUT / "all-docker-final.xml"
    inputs = [final] if final.exists() else [OUT/"all-docker.xml", OUT/"early-interruptions.xml"]
    cases = [case for path in inputs for case in ET.parse(path).iter("testcase")]
    rows = json.loads((OUT/"acceptance-map.json").read_text())
    for row in rows:
        row["resolved"] = []
        for selector in row["tests"]:
            selected = [case for case in cases if matches(case,selector)]
            states = ["failed" if case.find("failure") is not None else
                      "error" if case.find("error") is not None else
                      "skipped" if case.find("skipped") is not None else "passed" for case in selected]
            row["resolved"].append(dict(selector=selector,records=len(selected),
                nodes=sorted(set(case.get("classname")+"::"+case.get("name") for case in selected)),
                status="not_run" if not selected else "passed" if set(states)=={"passed"} else ",".join(sorted(set(states)))))
        row["status"] = "passed" if all(r["status"]=="passed" for r in row["resolved"]) else "not_passed"
    result=dict(inputs=[p.name for p in inputs],rows=rows,
                all_18_passed=len(rows)==18 and all(row["status"]=="passed" for row in rows))
    (OUT/"matrix-results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    doc = """# S7 验收映射（T22–T25）

本表的“通过”来自本次实际 JUnit 节点解析。每个选择器必须存在，且所有匹配记录（包括参数和子测试）均通过；缺失、跳过、错误、失败不能算通过。完整节点、逐项状态和输入报告见 [机器核对结果](evidence/s7-20261017/matrix-results.json)。最终完整重跑报告为 [all-docker-final.xml](evidence/s7-20261017/all-docker-final.xml)，命令、退出码和源码指纹见 [commands.json](evidence/s7-20261017/commands.json)。矩阵不是生产模型的质量评测。

| 编号 | 验收条件 | 本次实际测试（可直接用 pytest 节点执行） | 结果 | 证据类型与边界 |
| --- | --- | --- | --- | --- |
"""
    for row in rows:
        tests = "<br>".join("`"+test+"`" for test in row["tests"])
        doc += f"| {row['id']} | {row['criterion']} | {tests} | {'通过' if row['status']=='passed' else '未通过：见机器结果'} | {row['scope']} |\n"
    doc += """
定向失效仅在 `/private/tmp/airobot-s7-mutations-*` 的隔离副本中进行，原应用代码从未改写。机器门禁、审查 hash、可信测试原文、共享总额、取消传播共五处防线逐个失效，要求对应测试以断言失败退出 1；每处恢复后同一测试退出 0。语法错误、导入错误、运行超时不算成功检出。逐处差异、失败断言、恢复摘要和原目录未变证明见 [mutations.json](evidence/s7-20261017/mutations.json) 与 [mutation-preservation.json](evidence/s7-20261017/mutation-preservation.json)。这五项预期失败与最终正常版本的失败数分开统计。

模型及检索采用固定替身；真实 Docker 项使用本机固定 Go 1.26.2 镜像，实际执行 build/vet/test 和容器隔离/清理。缺失 Docker 的故障注入不代表本机缺失 Docker。A10 证明模型输出不能改权限、预算、终态，不能推出真实模型不会被诱导。A03 证明服务端执行必要需求检查，不证明固定模型识别任意自然语言需求的能力。

审查格式错误和 cannot_assess 共享最多一次异常重试；角色或整体截止时间超时直接返回 timeout，不为超时重置截止时间。A12 覆盖计划、检索、生成、验证、审查、修复生成，以及排队和写入/清理阶段。JSON 和 SSE 均核对业务终态、持久化、底层调用数和占用释放；HTTP 200 或连接结束不能判成功。

旧报告的本次服务端兼容性已实际检查，界面展示沿用 S6 已保存的真实浏览器证据；本步未修改前端，也未重跑浏览器。Python 3.11 与远程 CI 未运行；本次使用仓库 Python 3.13.13。真实付费模型评测未运行：尚无用户给出的累计费用上限。未知用量不补零，无模型能力或效果改善结论。
"""
    (ROOT/"docs/multi-agent-acceptance-matrix.md").write_text(doc)
    print(json.dumps({"inputs":result["inputs"],"rows":len(rows),"all_18_passed":result["all_18_passed"]}))
    assert result["all_18_passed"], "Missing/skipped/failed acceptance evidence"


if __name__ == "__main__":
    main()
