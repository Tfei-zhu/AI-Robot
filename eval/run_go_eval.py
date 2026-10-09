"""对比首次生成与最多两轮修复；固定输出和配置模型分别标记。"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.go_validation.contracts import GoTaskRequest
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from eval.go_fixtures import FixtureModel


async def empty_retrieval(query):
    return {"chunks": [], "sources": [], "warning": "固定评测不使用社区检索"}


def aggregate(rows, final):
    n = len(rows)
    return {
        "cases": n,
        "compile_pass_rate": sum(r["final_compile" if final else "initial_compile"] for r in rows)/n,
        "test_pass_rate": sum(r["final_pass" if final else "initial_pass"] for r in rows)/n,
        "mean_elapsed_ms": round(sum(r["elapsed_ms" if final else "initial_elapsed_ms"] for r in rows)/n, 1),
        "mean_model_calls": round(sum(r["model_calls"] if final else 1 for r in rows)/n, 2),
    }


async def evaluate(args):
    if args.live and not settings.llm_api_key:
        raise RuntimeError("真实模型评测需要在本地 .env 配置 AIROBOT_LLM_API_KEY；未运行，也不会使用固定输出替代")
    cases = json.loads((ROOT/"eval/go_cases.json").read_text(encoding="utf-8"))
    if args.live:
        # 真实生成使用同样需求和验收；variant 注入只对固定输出有效。
        cases = [c for c in cases if c["variant"] == "correct"]
        if args.repeat > 1:
            # 重复运行同一组需求测通过率稳定性；每轮是独立任务，id 加轮次后缀。
            cases = [{**c, "id": f"{c['id']}#{i}"} for i in range(1, args.repeat+1) for c in cases]
    if args.limit:
        cases = cases[:args.limit]
    task_store = GoTaskStore(":memory:")
    rows, results = [], []
    try:
        for case in cases:
            service = GoTaskService(task_store=task_store,
                model=None if args.live else FixtureModel(case["scenario"], case["variant"]),
                retrieve=None if args.live else empty_retrieval,
                # 真实模型单次生成 15~60s，3 轮生成加验证在 180s 内放不下；固定输出不受影响。
                timeout=360 if args.live else 180)
            result = await service.run(GoTaskRequest(scenario=case["scenario"], requirement=case["requirement"]),
                                       "go-eval", case["id"])
            attempts = result.attempts
            def compiled(a):
                return any(s.stage == "compile" and s.exit_code == 0 for s in a.validation.stages)
            rows.append({"id": case["id"], "initial_pass": bool(attempts and attempts[0].validation.status == "passed"),
                "final_pass": result.status == "passed", "initial_compile": bool(attempts and compiled(attempts[0])),
                "final_compile": bool(attempts and compiled(attempts[-1])), "final_status": result.status,
                "initial_elapsed_ms": attempts[0].validation.elapsed_ms if attempts else 0,
                "elapsed_ms": result.elapsed_ms, "model_calls": result.model_calls,
                "validation_calls": result.validation_calls, "token_usage": result.token_usage or None})
            results.append(result.model_dump())
            print(case["id"], "=>", result.status, f"({len(attempts)} 次验证)", flush=True)
    finally:
        task_store.close()
    repairable = [r for r in rows if not r["initial_pass"]]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
        "model_source": "configured" if args.live else "fixture",
        "model": settings.llm_model if args.live else "人工固定输出，无模型请求",
        "verification": "Docker Go 1.26.2，真实 build/vet/test，服务端固定行为测试",
        "scope": "固定输出结果用于验证流程与缺陷拦截，不代表真实模型生成或修复质量。" if not args.live else "当前三个固定需求的真实模型样本，不能代表所有 Go 任务。",
        "baseline": aggregate(rows, False), "with_repair": aggregate(rows, True),
        "repair_success_rate": sum(r["final_pass"] for r in repairable)/len(repairable) if repairable else None,
        "token_note": "固定输出无 token；真实模型只记录服务商返回的用量，未返回时为空。",
        "latency_note": "固定输出 baseline 耗时仅验证器；修复耗时含整个流程。真实模型逐次延迟未单独测量。",
        "rows": rows, "results": results}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", target.resolve())
    if not args.live:
        # 固定正确样例必须通过，既定行为/编译缺陷必须被首次验收拒绝。
        return 0 if all(r["final_pass"] and (c["variant"] == "correct" or not r["initial_pass"])
                        for c, r in zip(cases, rows)) else 1
    return 0 if all(r["final_pass"] for r in rows) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--fixtures", action="store_true", help="人工固定输出，真实 Docker 验证")
    modes.add_argument("--live", action="store_true", help="使用 .env 中配置的真实模型")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1,
                        help="live 模式下重复运行同一组需求的轮数（扩充样本量）")
    parser.add_argument("--output", default="eval/reports/go/report.json")
    args = parser.parse_args()
    try:
        sys.exit(asyncio.run(evaluate(args)))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
