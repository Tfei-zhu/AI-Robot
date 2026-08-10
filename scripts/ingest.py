# -*- coding: utf-8 -*-
"""CLI 导入知识文件：python scripts/ingest.py data/knowledge_base.md [更多文件...]
注意：CLI 与 FastAPI 服务是独立进程，各自持有内存知识库；
推荐直接调用 POST /api/v1/ingest 上传，或把文件放入 data/ 由服务启动时自动导入。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import kb  # noqa: E402


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        print("用法: python scripts/ingest.py <file1> [file2 ...]")
        return
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"跳过（不存在）: {path}")
            continue
        n = kb.ingest_file(path)
        print(f"导入 {path.name}: {n} 个分块，知识库共 {kb.chunk_count} 块")


if __name__ == "__main__":
    main()
