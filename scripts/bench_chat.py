# -*- coding: utf-8 -*-
"""对话服务基准：对运行中的 AI 服务做批量提问，输出 P95 / 均值 / 语义缓存命中率。

用法（服务需已启动；建议启动时临时调高限流，避免压测被 429 拦截）：
    AIROBOT_RATELIMIT_PER_MINUTE=10000 uvicorn app.main:app --port 8000
    python scripts/bench_chat.py [--base http://127.0.0.1:8000] [--limit 20]

流程：评测集每个问题问两遍——第一遍走真实生成，第二遍应命中语义缓存。
session_id 每次随机：缓存只对「无会话历史」的首轮问题生效。
读数：GET /api/v1/traces 的 summary（p95_ms / avg_ms / cache_hit_rate）。
对比实验：AIROBOT_CACHE_ENABLED=false 重启服务再跑一遍，两轮 summary 相减即缓存收益。
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from pathlib import Path


def load_questions(limit: int) -> list[str]:
    """复用 RAGAS 评测集的问题，保证压测问题覆盖知识库真实主题。"""
    path = Path(__file__).resolve().parent.parent / "eval" / "dataset" / "qa.jsonl"
    items = [json.loads(line)["question"] for line in path.open(encoding="utf-8") if line.strip()]
    return items[:limit] if limit else items


def post(base: str, path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(base: str, path: str, timeout: float) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="AI 服务地址")
    parser.add_argument("--limit", type=int, default=20, help="取评测集前 N 个问题")
    parser.add_argument("--timeout", type=float, default=120.0, help="单次请求超时（秒）")
    args = parser.parse_args()

    questions = load_questions(args.limit)
    total = len(questions) * 2
    print(f"开始压测：{len(questions)} 个问题 × 2 遍 = {total} 次对话（第一遍生成，第二遍应命中缓存）")

    health = get(args.base, "/health", args.timeout)
    print(f"服务正常：llm={health['llm_model']} embedding={health['embedding_model']}")

    done = 0
    t0 = time.perf_counter()
    for i, q in enumerate(questions, 1):
        for _ in range(2):
            # 随机 session_id 保证每次都是「首轮问题」，走 语义缓存 → 意图 → 生成 完整链路
            sid = f"bench-{random.randrange(1 << 30)}"
            post(args.base, "/api/v1/chat", {"message": q, "session_id": sid}, args.timeout)
            done += 1
        print(f"  [{done}/{total}] {q[:30]}")
    print(f"压测完成，耗时 {time.perf_counter() - t0:.0f}s\n")

    summary = get(args.base, "/api/v1/traces?limit=100000", args.timeout)["summary"]
    print("==== traces summary ====")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n提示：对比 AIROBOT_CACHE_ENABLED=false 轮次的 p95_ms / avg_ms，差值即语义缓存收益。")


if __name__ == "__main__":
    sys.exit(main())
