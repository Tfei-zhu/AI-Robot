# -*- coding: utf-8 -*-
"""CLI 导入知识文件：python scripts/ingest.py data/knowledge_base.md [更多文件...]
注意：CLI 与 FastAPI 服务是独立进程，各自持有内存知识库；
推荐直接调用 POST /api/v1/ingest 上传，或把文件放入 data/ 由服务启动时自动导入。
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import KnowledgeBase
from app.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="默认导入隔离基准库；在线生产导入请使用 HTTP")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--production", action="store_true", help="显式离线维护生产知识库，执行前请停服")
    args = parser.parse_args()
    paths = args.paths
    kb = KnowledgeBase(purpose="production" if args.production else "bench",
                       manifest_path=settings.knowledge_state_db if args.production else None)
    print(f"目标集合：{kb.collection_name}")
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"跳过（不存在）: {path}")
            continue
        n = kb.ingest_file(path)
        print(f"导入 {path.name}: {n} 个分块，知识库共 {kb.chunk_count} 块")
    kb.close()


if __name__ == "__main__":
    main()
