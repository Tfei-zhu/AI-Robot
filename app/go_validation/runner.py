"""仅通过 Docker 执行源码；引擎不可用时拒绝降级为宿主执行。"""
import asyncio
import json
import time
import uuid

from app.go_validation.contracts import CodeBundle, StageReport, ValidationReport

IMAGE = "airobot-go-validator:1.26.2"


class DockerGoRunner:
    def __init__(self, timeout: float = 90, log_limit: int = 80000):
        self.timeout = timeout
        self.log_limit = log_limit

    def command(self, name: str) -> list[str]:
        # 不传宿主路径、环境变量或 Docker socket；镜像只接收源码 JSON。
        return ["docker", "run", "--name", name, "--label", "airobot.go-validation=true",
                "--pull=never", "--network=none", "--read-only", "--user=65532:65532",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--cpus=1",
                "--memory=512m", "--memory-swap=512m", "--pids-limit=128",
                # Go 将测试二进制放在 /tmp，仅这个受限临时目录允许执行。
                "--ulimit", "nofile=256:256", "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=384m,mode=1777",
                "--tmpfs", "/work:rw,nosuid,nodev,size=16m,mode=1777",
                "--log-driver=none", "-i", IMAGE]

    async def _remove(self, name: str) -> bool:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec("docker", "rm", "-f", name,
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            return await asyncio.wait_for(proc.wait(), 15) == 0
        except (OSError, TimeoutError):
            return False
        finally:
            # Docker 客户端自身超时也要回收，避免遗留宿主进程。
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

    async def validate(self, bundle: CodeBundle) -> ValidationReport:
        # 即便内部调用者绕过 API，也重新校验完整契约。
        bundle = CodeBundle.model_validate(bundle.model_dump())
        started = time.perf_counter()
        name = "airobot-go-" + uuid.uuid4().hex
        proc = None
        report = ValidationReport(status="unavailable")
        async def read_bounded(stream):
            data = bytearray()
            while chunk := await stream.read(4096):
                # 容器日志也是不可信输入，超过上限立即中止整个验证。
                if len(data) + len(chunk) > self.log_limit:
                    raise ValueError("沙箱报告超过日志上限")
                data.extend(chunk)
            return bytes(data)

        async def execute():
            nonlocal proc
            proc = await asyncio.create_subprocess_exec(*self.command(name), stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            proc.stdin.write(bundle.model_dump_json().encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            output, error = await asyncio.gather(read_bounded(proc.stdout), read_bounded(proc.stderr))
            code = await proc.wait()
            if code != 0:
                return ValidationReport(status="unavailable" if code in (125, 126, 127) else "failed",
                        stages=[StageReport(stage="sandbox", exit_code=code,
                                output=error.decode("utf-8", "replace")[:2000] or "验证进程异常退出")])
            parsed = ValidationReport.model_validate(json.loads(output))
            expected = ["policy", "compile", "vet", "test"]
            if parsed.go_version != "1.26.2":
                raise ValueError("沙箱工具链版本不匹配")
            if parsed.status == "passed" and ([s.stage for s in parsed.stages] != expected
                                             or any(s.exit_code for s in parsed.stages)):
                raise ValueError("验证报告缺少规定阶段")
            return parsed

        try:
            report = await asyncio.wait_for(execute(), self.timeout)
        except TimeoutError:
            report = ValidationReport(status="timeout", stages=[StageReport(stage="sandbox", exit_code=124,
                                      output="验证超过总时间预算")])
        except asyncio.CancelledError:
            # shield 保证取消请求也会等待容器清理，再将取消传播给调用者。
            raise
        except (OSError, ValueError) as exc:
            report = ValidationReport(status="unavailable", stages=[StageReport(stage="sandbox", exit_code=1,
                                      output=str(exc)[:2000])])
        finally:
            cleanup = asyncio.create_task(self._remove(name))
            interrupted = False
            while True:
                try:
                    removed = await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    # 客户端断开与任务总超时可能同时取消；继续等同一个清理任务。
                    interrupted = True
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
            report.container_removed = removed
            report.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            if report.status == "passed" and not removed:
                report.status = "unavailable"
                report.stages.append(StageReport(stage="sandbox", exit_code=1,
                                    output="无法确认容器清理完成，验证结果不予通过"))
            if interrupted:
                raise asyncio.CancelledError
        return report
