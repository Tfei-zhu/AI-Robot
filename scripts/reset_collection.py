"""显式清理评测/基准集合；不提供生产集合删除入口。"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings


def validate_target(collection, confirm):
    if (collection != confirm or collection == settings.milvus_collection
            or not re.fullmatch(r"airobot_(eval|bench)_[0-9a-f]{32}", collection)):
        raise ValueError("仅允许清理明确确认的评测/基准集合；生产集合请采用新集合重建并切换")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--confirm", required=True, help="再次填写完全相同的集合名")
    args = parser.parse_args()
    validate_target(args.collection, args.confirm)
    from pymilvus import MilvusClient
    client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token)
    try:
        client.drop_collection(collection_name=args.collection)
        print(f"已删除评测集合：{args.collection}（可通过重新运行评测重建）")
    finally:
        client.close()


if __name__ == "__main__":
    main()
