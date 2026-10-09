"""执行命令约束与真实 Docker 编译、测试、策略及清理验证。"""
import asyncio
import os
import json

import pytest

from app.go_validation.contracts import CodeBundle
from app.go_validation.runner import DockerGoRunner


def source(implementation="func Double(x int) int { return x * 2 }", test="if Double(2)!=4 {t.Fatal(\"wrong\")}", imports="", test_imports=""):
    return CodeBundle(files=[{"name":"solution.go","content":"package example\n"+imports+"\n"+implementation},
                             {"name":"solution_test.go","content":"package example\nimport \"testing\"\n"+test_imports+"\nfunc TestDouble(t *testing.T){"+test+"}"}])


def test_command_has_isolation_and_no_host_mounts():
    cmd = DockerGoRunner().command("airobot-go-test")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--memory=512m",
                 "--pids-limit=128", "--user=65532:65532", "--pull=never"):
        assert flag in cmd
    assert not any(s in cmd for s in ("-v", "--volume", "--mount", "--env", "--privileged"))


real = pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER") != "1", reason="显式启用真实 Docker 测试")


@real
@pytest.mark.parametrize("bundle,stage,status", [
    (source(), "test", "passed"),
    (source("func Double(x int) int { return missing }"), "compile", "failed"),
    (source(test="t.Fatal(\"expected failure\")"), "test", "failed"),
    (source(imports='import _ "github.com/example/dependency"'), "policy", "failed"),
    (source(imports='import _ "unsafe"'), "policy", "failed"),
    (source(test='t.Skip("skip")'), "test", "failed"),
    (source(implementation='func Double(x int) int { fmt.Printf("%d", "bad"); return x*2 }', imports='import "fmt"'), "vet", "failed"),
    (source(implementation='//go:build linux\nfunc Double(x int) int {return x*2}'), "policy", "failed"),
    (source(test='t.Log(strings.Repeat("x", 30000))', test_imports='import "strings"'), "test", "failed"),
])
def test_real_checks(bundle, stage, status):
    report = asyncio.run(DockerGoRunner().validate(bundle))
    assert report.status == status, report.model_dump()
    assert report.stages[-1].stage == stage
    assert report.container_removed


@real
def test_timeout_and_cancel_remove_container():
    async def run():
        runner= DockerGoRunner(timeout=2)
        report = await runner.validate(source(test="for {}"))
        assert report.status == "timeout" and report.container_removed
        task = asyncio.create_task(DockerGoRunner().validate(source(test="for {}")))
        await asyncio.sleep(2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())


@real
def test_real_identity_filesystem_and_secret_isolation(monkeypatch):
    monkeypatch.setenv("AIROBOT_TEST_SECRET", "must-never-enter-container")
    bundle = CodeBundle(files=[
        {"name":"solution.go", "content":"package example\nfunc Double(x int) int{return x*2}"},
        {"name":"solution_test.go", "content":'''package example
import ("testing"; "os"; "strings")
func TestIsolation(t *testing.T) {
    if os.Getuid()!=65532 {t.Fatal("not unprivileged")}
    if os.Getenv("AIROBOT_TEST_SECRET")!="" {t.Fatal("host secret leaked")}
    if err:=os.WriteFile("/etc/airobot-probe",[]byte("x"),0600); err==nil {t.Fatal("root filesystem writable")}
    raw,err:=os.ReadFile("/proc/self/status"); if err!=nil {t.Fatal(err)}
    if !strings.Contains(string(raw),"NoNewPrivs:\\t1") {t.Fatal("privilege escalation not disabled")}
    if !strings.Contains(string(raw),"CapEff:\\t0000000000000000") {t.Fatal("capabilities not dropped")}
}'''}])
    report=asyncio.run(DockerGoRunner().validate(bundle))
    assert report.status == "passed", report.model_dump()
    assert report.container_removed


@real
def test_real_container_resource_and_network_configuration():
    class InspectRunner(DockerGoRunner):
        async def _remove(self, name):
            proc = await asyncio.create_subprocess_exec("docker", "inspect", name,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            output, _ = await proc.communicate()
            self.observed = json.loads(output)[0]["HostConfig"]
            return await super()._remove(name)
    runner=InspectRunner()
    report=asyncio.run(runner.validate(source()))
    assert report.status == "passed", report.model_dump()
    host=runner.observed
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"]
    assert host["Memory"] == 512*1024*1024 and host["MemorySwap"] == host["Memory"]
    assert host["NanoCpus"] == 1000000000 and host["PidsLimit"] == 128
    assert not host["Binds"] and not host["Privileged"]


def test_missing_docker_never_runs_host_code(monkeypatch):
    async def missing(*args, **kwargs):
        assert args[0] == "docker"
        raise FileNotFoundError("Docker 不可用")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", missing)
    report=asyncio.run(DockerGoRunner().validate(source()))
    assert report.status == "unavailable"
    assert not report.container_removed


@real
def test_repeated_cancellation_still_waits_for_cleanup():
    class SlowCleanup(DockerGoRunner):
        def __init__(self):
            super().__init__()
            self.cleaning = asyncio.Event()
            self.removed = False
        async def _remove(self, name):
            self.cleaning.set()
            await asyncio.sleep(0.2)
            self.removed = await super()._remove(name)
            return self.removed
    async def run():
        runner = SlowCleanup()
        task = asyncio.create_task(runner.validate(source(test="for {}")))
        await asyncio.sleep(2)
        task.cancel()
        await runner.cleaning.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.removed
    asyncio.run(run())
