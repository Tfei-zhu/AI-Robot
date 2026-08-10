# -*- coding: utf-8 -*-
"""检索策略对比：vector / bm25 / hybrid(RRF) / hybrid+rerank 在评测集上的 hit@k。

用法（需配置 AIROBOT_EMBEDDING_API_KEY；rerank 首次会加载 bge-reranker 模型，约 10 秒）：
    python scripts/bench_retrieval.py [--top-k 5] [--limit 52]
                                     [--out data/bench_retrieval_result.csv]

评测集：eval/dataset/qa.jsonl（question + 期望关键词），指标 = 关键词命中率（hit@k）。
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.rag.retriever import KnowledgeBase  # noqa: E402


def load_queries(limit: int) -> list[dict]:
    path = Path(__file__).resolve().parent.parent / "eval" / "dataset" / "qa.jsonl"
    items = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    return items[:limit] if limit else items


def hit_at_k(docs, keywords: list[str]) -> bool:
    text = " ".join(d.page_content for d in docs)
    return any(kw in text for kw in keywords)


def main() -> None:
    parser = argparse.ArgumentParser(description="检索策略对比（hit@k）")
    parser.add_argument("--top-k", type=int, default=5, help="召回条数（默认 5）")
    parser.add_argument("--limit", type=int, default=0, help="评测条数（0=全部）")
    parser.add_argument("--out", default="data/bench_retrieval_result.csv",
                        help="结果 CSV 输出路径")
    args = parser.parse_args()

    if not settings.embedding_api_key:
        print("未配置 AIROBOT_EMBEDDING_API_KEY，无法向量化。请复制 .env.example 为 .env 并填入密钥。")
        sys.exit(1)

    items = load_queries(args.limit)
    print(f"评测集: {len(items)} 条 | top_k={args.top_k}")

    kb = KnowledgeBase()
    for f in Path("data").glob("knowledge_base.md"):
        n = kb.ingest_file(f)
        print(f"  导入 {f.name}: {n} 块")
    print(f"  知识库共 {kb.chunk_count} 块 | BM25 ready={kb.bm25_ready}\n")

    strategies = {
        "vector": lambda q: kb.search_vector(q, args.top_k),
        "bm25": lambda q: kb.search_bm25(q, args.top_k),
        "hybrid_rrf": lambda q: kb.search_hybrid(q, args.top_k),
        "hybrid_rerank": lambda q: kb.search(q, args.top_k),
    }

    rows = []
    for name, fn in strategies.items():
        hits = 0
        t0 = time.perf_counter()
        for item in items:
            docs = fn(item["question"])
            if hit_at_k(docs, item.get("keywords", [])):
                hits += 1
        elapsed = time.perf_counter() - t0
        rows.append({
            "strategy": name,
            "hit_rate": hits / len(items),
            "avg_ms": round(elapsed / len(items) * 1000, 1),
        })
        print(f"  {name:<14} hit@{args.top_k}={hits}/{len(items)} "
              f"({hits/len(items):.0%})  avg={elapsed/len(items)*1000:.1f}ms")

    print("\n| 策略 | 命中率 | 平均耗时/条 |")
    print("|---|---|---|")
    for r in rows:
        print(f"| {r['strategy']} | {r['hit_rate']:.0%} | {r['avg_ms']} ms |")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["strategy", "hit_rate", "avg_ms"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
