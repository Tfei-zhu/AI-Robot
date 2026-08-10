# -*- coding: utf-8 -*-
"""RAG 评测入口：RAGAS 四指标 + LLM-as-Judge + 关键词命中基线。

用法（需配置 AIROBOT_LLM_API_KEY / AIROBOT_EMBEDDING_API_KEY）：
    python eval/run_eval.py                     # 全量评测集（52 条）
    python eval/run_eval.py --limit 5           # 冒烟：只跑前 5 条
    python eval/run_eval.py --no-ragas          # 跳过 RAGAS（只跑 Judge + 基线）
    python eval/run_eval.py --top-k 3 --ingest data/knowledge_base.md

流程：
1) 解析评测集（eval/dataset/qa.jsonl：id/category/question/reference/keywords）；
2) 重建知识库（进程内独立实例）并逐条跑 RAG：检索 -> 生成；
3) RAGAS 指标：Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall；
4) LLM-as-Judge：对每条回答打 1-5 分并给理由；
5) 基线：检索命中率（关键词出现在召回的 top-k 上下文中）；
6) 输出控制台表格 + JSON/Markdown 报告到 eval/reports/。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from langchain_core.output_parsers import StrOutputParser  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402

from app.config import settings  # noqa: E402


def load_dataset(path: Path) -> list[dict]:
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def build_kb(files: list[Path], top_k: int):
    """独立知识库实例：评测不污染运行中的服务。"""
    from app.rag.retriever import KnowledgeBase

    kb = KnowledgeBase()
    for f in files:
        n = kb.ingest_file(f)
        print(f"  导入 {f.name}: {n} 块")
    print(f"  知识库共 {kb.chunk_count} 块 | top_k={top_k}")
    return kb


def run_rag(kb, question: str, top_k: int) -> tuple[str, list[str]]:
    """检索 -> 生成，返回 (回答, 检索上下文列表)。"""
    from app.rag.retriever import RAG_PROMPT, build_llm

    docs = kb.search(question, top_k=top_k)
    contexts = [d.page_content for d in docs]
    chain = RAG_PROMPT | build_llm() | StrOutputParser()
    answer = chain.invoke({"context": "\n\n".join(contexts), "question": question, "history": []})
    return answer, contexts


JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是 RAG 效果评测员。根据标准答案判断助手回答的正确性与完整性，只输出 JSON："
     "{{\"score\": 1-5 的整数, \"reason\": \"一句话理由\"}}。"
     "评分标准：5=完全正确且完整；4=基本正确略缺细节；3=部分正确；2=错误较多；1=错误或答非所问。"),
    ("human", "问题：{question}\n\n标准答案：{reference}\n\n助手回答：{answer}\n\n请评分。"),
])


def judge_answer(question: str, reference: str, answer: str, llm=None) -> tuple[int, str]:
    """LLM-as-Judge：返回 (1-5 分, 理由)。"""
    from app.rag.retriever import build_llm

    chain = JUDGE_PROMPT | (llm or build_llm()) | StrOutputParser()
    raw = chain.invoke({"question": question, "reference": reference, "answer": answer})
    try:
        data = json.loads(raw.strip().strip("`"))
        score = int(data.get("score", 1))
        reason = str(data.get("reason", ""))[:150]
    except Exception:
        match = re.search(r"[1-5]", raw)
        score = int(match.group(0)) if match else 1
        reason = raw[:150].replace("\n", " ")
    return max(1, min(5, score)), reason


def keyword_hit(contexts: list[str], keywords: list[str]) -> bool:
    text = " ".join(contexts)
    return any(kw in text for kw in keywords)


def ragas_metrics(samples: list[dict]) -> dict:
    """RAGAS 四指标：Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall。"""
    from ragas import evaluate
    from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (answer_relevancy, context_precision,
                               context_recall, faithfulness)
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    llm = LangchainLLMWrapper(ChatOpenAI(
        model=settings.llm_model, api_key=settings.llm_api_key,
        base_url=settings.llm_base_url, temperature=0))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
        model=settings.embedding_model, api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url, check_embedding_ctx_length=False))

    ds = EvaluationDataset(samples=[
        SingleTurnSample(
            user_input=s["question"],
            response=s["answer"],
            retrieved_contexts=s["contexts"],
            reference=s["reference"],
        )
        for s in samples
    ])
    result = evaluate(
        dataset=ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=llm, embeddings=embeddings, show_progress=True,
    )
    df = result.to_pandas()
    per_sample = []
    for i, row in df.iterrows():
        per_sample.append({
            "id": samples[i]["id"],
            "faithfulness": _num(row.get("faithfulness")),
            "answer_relevancy": _num(row.get("answer_relevancy")),
            "context_precision": _num(row.get("context_precision")),
            "context_recall": _num(row.get("context_recall")),
        })
    return {
        "per_sample": per_sample,
        "avg": {
            "faithfulness": _mean([p["faithfulness"] for p in per_sample]),
            "answer_relevancy": _mean([p["answer_relevancy"] for p in per_sample]),
            "context_precision": _mean([p["context_precision"] for p in per_sample]),
            "context_recall": _mean([p["context_recall"] for p in per_sample]),
        },
    }


def _num(v) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # NaN -> None
    except (TypeError, ValueError):
        return None


def _mean(values: list) -> float:
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 4) if valid else None


def write_report(report: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    lines = ["# RAG 评测报告", ""]
    avg = report["summary"]["avg"]
    lines.append(f"- 评测时间: {report['meta']['timestamp']}")
    lines.append(f"- 评测集: {report['meta']['dataset']}（{report['meta']['total']} 条）")
    lines.append(f"- LLM: {report['meta']['llm_model']} | Embedding: {report['meta']['embedding_model']} | top_k: {report['meta']['top_k']}")
    lines.append("")
    lines.append("## 总览")
    lines.append("")
    lines.append("| 指标 | 得分 |")
    lines.append("|---|---|")
    for key, label in [("faithfulness", "Faithfulness"),
                       ("answer_relevancy", "AnswerRelevancy"),
                       ("context_precision", "ContextPrecision"),
                       ("context_recall", "ContextRecall"),
                       ("judge_score", "LLM-as-Judge(1-5)"),
                       ("baseline_hit_rate", "关键词命中率")]:
        v = avg.get(key)
        lines.append(f"| {label} | {v if v is not None else '-'} |")
    lines.append("")
    lines.append("## 分档统计")
    lines.append("")
    for row in report["summary"]["judge_buckets"]:
        lines.append(f"- Judge {row['bucket']} 分: {row['count']} 条")
    lines.append("")
    worst = report["summary"]["worst_cases"][:5]
    if worst:
        lines.append("## 低分样本（Top 5）")
        lines.append("")
        for w in worst:
            lines.append(f"- **{w['id']}** {w['category']}：Judge {w['judge_score']} 分 - {w['question']}")
            lines.append(f"  - 理由: {w['judge_reason']}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 评测（RAGAS + LLM-as-Judge + 基线）")
    parser.add_argument("--dataset", default=str(BASE_DIR / "eval" / "dataset" / "qa.jsonl"))
    parser.add_argument("--ingest", nargs="*", default=[str(BASE_DIR / "data" / "knowledge_base.md")])
    parser.add_argument("--top-k", type=int, default=settings.top_k)
    parser.add_argument("--limit", type=int, default=0, help="只评测前 N 条（0=全部）")
    parser.add_argument("--no-ragas", action="store_true", help="跳过 RAGAS 指标（只跑 Judge+基线）")
    parser.add_argument("--out", default=None, help="报告输出路径")
    args = parser.parse_args()

    if not settings.llm_api_key or not settings.embedding_api_key:
        print("未配置 AIROBOT_LLM_API_KEY / AIROBOT_EMBEDDING_API_KEY，无法评测。请先复制 .env.example 为 .env 并填入密钥。")
        sys.exit(1)

    items = load_dataset(Path(args.dataset))
    if args.limit > 0:
        items = items[: args.limit]
    print(f"评测集: {Path(args.dataset).name} 共 {len(items)} 条")

    files = [Path(f) for f in args.ingest if Path(f).exists()]
    if not files:
        print("没有可用的知识文件，请检查 --ingest。")
        sys.exit(1)
    kb = build_kb(files, args.top_k)

    # 1) 逐条跑 RAG + Judge + 基线
    from app.rag.retriever import build_llm
    llm = build_llm()
    rows = []
    print("\n逐条评测中...\n")
    t0 = time.perf_counter()
    for i, item in enumerate(items, 1):
        question = item["question"]
        answer, contexts = run_rag(kb, question, args.top_k)
        score, reason = judge_answer(question, item["reference"], answer, llm)
        hit = keyword_hit(contexts, item.get("keywords", []))
        rows.append({**item, "answer": answer, "contexts": contexts,
                     "judge_score": score, "judge_reason": reason, "hit": hit})
        print(f"[{i}/{len(items)}] {item['id']} judge={score} hit={hit} | {question}")

    elapsed = time.perf_counter() - t0

    # 2) RAGAS
    ragas = ragas_metrics(rows) if not args.no_ragas else None
    if ragas:
        for i, p in enumerate(ragas["per_sample"]):
            rows[i].update(p)

    # 3) 汇总
    judge_scores = [r["judge_score"] for r in rows]
    hit_rate = sum(1 for r in rows if r["hit"]) / len(rows)
    buckets = [{"bucket": b, "count": sum(1 for s in judge_scores if b <= s < b + 1)}
               for b in range(1, 6)]
    worst = sorted(rows, key=lambda r: r["judge_score"])[:5]
    avg = {
        "judge_score": round(sum(judge_scores) / len(judge_scores), 2),
        "baseline_hit_rate": round(hit_rate, 4),
    }
    if ragas:
        avg.update(ragas["avg"])

    by_category = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r["judge_score"])
    cat_summary = {k: {"count": len(v), "judge_avg": round(sum(v) / len(v), 2)}
                   for k, v in sorted(by_category.items())}

    report = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "dataset": str(Path(args.dataset)),
            "total": len(rows),
            "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model,
            "top_k": args.top_k,
            "elapsed_sec": round(elapsed, 1),
            "ragas": not args.no_ragas,
        },
        "summary": {"avg": avg, "judge_buckets": buckets, "worst_cases": [
            {"id": w["id"], "category": w["category"], "question": w["question"],
             "judge_score": w["judge_score"], "judge_reason": w["judge_reason"]}
            for w in worst]},
        "by_category": cat_summary,
        "samples": [{k: r.get(k) for k in
                     ("id", "category", "question", "judge_score", "judge_reason",
                      "hit", "faithfulness", "answer_relevancy",
                      "context_precision", "context_recall")} for r in rows],
    }

    out = Path(args.out) if args.out else (BASE_DIR / "eval" / "reports"
                                           / f"report_{time.strftime('%Y%m%d_%H%M%S')}.json")
    write_report(report, out)

    print("\n===== 评测结果 =====")
    print(f"评测 {len(rows)} 条，耗时 {elapsed:.1f}s")
    print(f"| 指标 | 得分 |")
    print(f"|---|---|")
    print(f"| LLM-as-Judge(1-5) | {avg['judge_score']} |")
    print(f"| 关键词命中率 | {avg['baseline_hit_rate']:.2%} |")
    if ragas:
        for k in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            print(f"| {k} | {avg[k] if avg[k] is not None else '-'} |")
    print(f"\n分档: " + ", ".join(f"{b['bucket']}分×{b['count']}" for b in buckets))
    print(f"\n报告已保存: {out}（含 Markdown 版）")


if __name__ == "__main__":
    main()
