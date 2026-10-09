"""范围契约的正向与边界测试。"""
import pytest
from pydantic import ValidationError

from app.go_validation.contracts import CodeBundle, GoTaskRequest, GO_VERSION, MAX_REPAIRS, SCENARIO_SPECS, SourceFile


def test_scope_and_budget():
    assert GO_VERSION == "1.26.2"
    assert MAX_REPAIRS == 2
    for scenario in ("context_cancel", "worker_pool", "channel"):
        assert GoTaskRequest(requirement="生成可运行示例", scenario=scenario).scenario == scenario
        assert SCENARIO_SPECS[scenario].startswith("package example")
    with pytest.raises(ValidationError):
        GoTaskRequest(requirement="生成可运行示例", scenario="web_server")


@pytest.mark.parametrize("name", ["../x.go", "x/y.go", "C:x.go", ".x.go", "go.mod", "x.go;cmd", "x\\y.go"])
def test_rejects_unsafe_names(name):
    with pytest.raises(ValidationError):
        SourceFile(name=name, content="package example")


def test_requires_implementation_tests_and_unique_names():
    good = [{"name": "solution.go", "content": "package example"},
            {"name": "solution_test.go", "content": "package example"}]
    assert len(CodeBundle(files=good).files) == 2
    for files in ([good[0]], [good[1]], good + [good[0]], good + [{**good[0], "name": "Solution.go"}]):
        with pytest.raises(ValidationError):
            CodeBundle(files=files)


def test_total_utf8_size_limit():
    with pytest.raises(ValidationError):
        CodeBundle(files=[{"name": "solution.go", "content": "中" * 22000},
                          {"name": "solution_test.go", "content": "package example"}])
