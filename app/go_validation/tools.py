"""服务端验证工具不接受模型提供的命令、路径或容器参数。"""
from langchain_core.tools import tool

from app.go_validation.contracts import CodeBundle
from app.go_validation.runner import DockerGoRunner


@tool("validate_go_code")
async def validate_go_code(files: list[dict]) -> dict:
    """在受限 Docker 沙箱编译、静态检查并测试 Go 标准库单包代码。"""
    bundle = CodeBundle.model_validate({"files": files})
    return (await DockerGoRunner().validate(bundle)).model_dump()
