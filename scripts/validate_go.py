"""读取源码 JSON 并执行独立沙箱验证，供 B 部分验收使用。"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.go_validation.contracts import CodeBundle
from app.go_validation.runner import DockerGoRunner


def main():
    parser = argparse.ArgumentParser(description="隔离验证 Go 标准库单包代码")
    parser.add_argument("bundle", type=Path, help="包含 files 数组的 JSON 文件")
    args = parser.parse_args()
    # CLI 同样执行契约校验，不接受文件中的任何命令字段。
    bundle = CodeBundle.model_validate_json(args.bundle.read_text(encoding="utf-8"))
    report = asyncio.run(DockerGoRunner().validate(bundle))
    print(report.model_dump_json(indent=2))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
