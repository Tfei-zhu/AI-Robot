"""Inspect declared requirements and test configuration without importing tests."""
import ast
from importlib import metadata
import json
from pathlib import Path
import sys

from packaging.requirements import Requirement

root = Path(__file__).resolve().parents[3]


def requirements(path):
    result = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            result.extend(requirements(path.parent / line[3:]))
            continue
        req = Requirement(line)
        try:
            installed = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            installed = None
        result.append({"requirement": line, "installed": installed,
                       "satisfied": installed is not None and installed in req.specifier})
    return result


report = {"executable": sys.executable,
          "requirements": {name: requirements(root / name) for name in
                           ("requirements.txt", "requirements-dev.txt", "requirements-extra.txt", "requirements-eval.txt")},
          "test_inventory": {}}
for path in sorted((root / "tests").glob("test_*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    report["test_inventory"][path.name] = {
        "test_definitions_before_parametrization": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                                       and n.name.startswith("test_") for n in ast.walk(tree))}
report["config_files_present"] = [str(p.relative_to(root)) for p in
                                  (root / "pytest.ini", root / "pyproject.toml", root / "setup.cfg", root / "tox.ini",
                                   root / "tests/conftest.py", root / ".python-version") if p.exists()]
report["latest_dotenv_exists"] = (root / ".env").exists()
print(json.dumps(report, ensure_ascii=False, indent=2))
