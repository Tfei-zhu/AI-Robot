# -*- coding: utf-8 -*-
"""分块参数对比实验：不同 chunk_size/overlap（及 Markdown 标题分块）对检索命中率的影响。

用法（需配置 AIROBOT_EMBEDDING_API_KEY）：
    python scripts/bench_splitter.py [--files data/knowledge_base.md ...] [--top-k 3]
                                    [--out data/bench_splitter_result.csv]

输出：控制台 Markdown 表格 + CSV；每个配置会重新向量化知识库（少量 Embedding 调用）。
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document  # noqa: E402
from langchain_core.vectorstores import InMemoryVectorStore  # noqa: E402
from langchain_text_splitters import (  # noqa: E402
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import settings  # noqa: E402
from app.rag.loader import parse_file  # noqa: E402
from app.rag.retriever import build_embeddings  # noqa: E402

# (问题, 期望命中的关键词) —— 与 data/knowledge_base.md 内容对应
EVAL_QUERIES = [
    ("怎么发布商品？", ["发布商品", "审核"]),
    ("怎么联系卖家？", ["联系卖家", "站内聊天"]),
    ("退货邮费谁承担？", ["运费由卖家承担", "运费由买家承担"]),
    ("七天无理由退货有什么条件？", ["不影响二次销售", "7 天"]),
    ("平台服务费怎么收取？", ["1%", "服务费"]),
    ("订单支付支持哪些方式？", ["微信", "支付宝", "平台余额"]),
]

# (chunk_size, overlap, 是否 Markdown 标题分块)
CONFIGS = [
    (200, 40, False),
    (400, 80, False),
    (600, 120, False),
    (800, 160, False),
    (400, 80, True),
]


def _label(chunk_size: int, overlap: int, use_markdown: bool) -> str:
    mode = "markdown" if use_markdown else "recursive"
    return f"{mode}-{chunk_size}/{overlap}"


def run_config(files: list[Path], chunk_size: int, overlap: int,
               use_markdown: bool, top_k: int) -> dict:
    """用指定分块策略重建向量库并跑评测集，返回命中率与平均 Top1 相似度。"""
    separator = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
    recursive = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=overlap, separators=separator)

    if use_markdown:
        markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4")],
            strip_headers=False,
        )
        docs: list[Document] = []
        for path in files:
            sections = markdown_splitter.split_text(parse_file(path))
            for section in sections:
                if len(section.page_content) <= chunk_size * 2:
                    docs.append(section)
                else:
                    docs.extend(recursive.split_documents([section]))
    else:
        docs = [
            Document(page_content=chunk)
            for path in files
            for chunk in recursive.split_text(parse_file(path))
        ]

    store = InMemoryVectorStore(embedding=build_embeddings())
    store.add_documents(docs)

    hits = 0
    top1_sim_sum = 0.0
    for query, keywords in EVAL_QUERIES:
        found = store.similarity_search(query, k=top_k)
        if any(any(kw in d.page_content for kw in keywords) for d in found):
            hits += 1
        top1 = store.similarity_search_with_score(query, k=1)
        if top1:
            top1_sim_sum += float(top1[0][1])

    return {
        "label": _label(chunk_size, overlap, use_markdown),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "markdown": use_markdown,
        "total_chunks": len(docs),
        "hit_rate": hits / len(EVAL_QUERIES),
        "avg_top1_sim": top1_sim_sum / len(EVAL_QUERIES),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="分块参数对比实验")
    parser.add_argument("--files", nargs="*", default=["data/knowledge_base.md"],
                        help="参与实验的知识文件（默认 data/knowledge_base.md）")
    parser.add_argument("--top-k", type=int, default=3, help="召回条数（默认 3）")
    parser.add_argument("--out", default="data/bench_splitter_result.csv",
                        help="结果 CSV 输出路径（默认 data/bench_splitter_result.csv）")
    args = parser.parse_args()

    if not settings.embedding_api_key:
        print("未配置 AIROBOT_EMBEDDING_API_KEY，无法向量化。请复制 .env.example 为 .env 并填入密钥。")
        sys.exit(1)

    files = [Path(f) for f in args.files if Path(f).exists()]
    if not files:
        print("没有可用的知识文件，请检查 --files 路径。")
        sys.exit(1)

    print(f"评测集: {len(EVAL_QUERIES)} 条查询 | top_k={args.top_k} | "
          f"文件: {[f.name for f in files]}")
    print("开始逐配置向量化与检索（每个配置一次 Embedding 批量调用）...\n")

    rows = [
        run_config(files, size, overlap, markdown, args.top_k)
        for size, overlap, markdown in CONFIGS
    ]

    print("| 配置 | chunk_size | overlap | Markdown | 总块数 | 命中率 | 平均Top1相似度 |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        md = "是" if row["markdown"] else "否"
        print(f"| {row['label']} | {row['chunk_size']} | {row['overlap']} | {md} "
              f"| {row['total_chunks']} | {row['hit_rate']:.0%} | {row['avg_top1_sim']:.4f} |")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["label", "chunk_size", "overlap", "markdown",
                            "total_chunks", "hit_rate", "avg_top1_sim"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n结果已保存: {out}")


if __name__ == "__main__":
    main()
