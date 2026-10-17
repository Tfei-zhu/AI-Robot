"""S0 final check: source preservation, saved results and artifact identifiers."""
import ast
import hashlib
import json
from pathlib import Path
import re
import runpy

base = Path(__file__).resolve().parent
runtime = runpy.run_path(str(base / "run_baseline.py"))
root = runtime["ROOT"]
before = json.loads((base / "source-before.json").read_text())
current = {"latest": runtime["snapshot"](root), "old": runtime["snapshot"](runtime["OLD"])}
assert before["latest"]["head"] == current["latest"]["head"]
assert before["latest"]["source_manifest_sha256"] == current["latest"]["source_manifest_sha256"]
assert before["old"] == current["old"], "Old source or Git status changed"
assert before["latest"]["tracked_diff_sha256"] == current["latest"]["tracked_diff_sha256"]
assert before["latest"]["staged_diff_sha256"] == current["latest"]["staged_diff_sha256"]
assert all(line.startswith(("#", "?")) for line in current["latest"]["status"].splitlines())
rows = []
for name in ("commands.json", "supplementary-commands.json"):
    rows.extend(json.loads((base / name).read_text()))
for row in rows:
    assert runtime["sha"]((base / row["output"]).read_bytes()) == row["output_sha256"], row["id"]
for source in base.rglob("*.py"):
    ast.parse(source.read_text())
log = root / "docs/multi-agent-execution-log.md"
for link in re.findall(r"\]\((evidence/[^)]+)\)", log.read_text()):
    if link.endswith(("artifact-manifest.json", "final-checks.txt")):
        continue  # Produced after these checks.
    assert (root / "docs" / link).is_file(), link
lines = ["S0 final checks: PASS (evidence consistency, not full behavioral acceptance)",
         "command: python3 docs/evidence/s0-20261017/verify_evidence.py", "exit_code: 0",
         f"Verified command/output records: {len(rows)}",
         "Latest HEAD/branch/tracked diff/staged diff/source + original untracked plans: unchanged",
         "Old HEAD/Git status/declared source manifest: unchanged",
         "Evidence helpers: AST parse passed; log evidence links present",
         "Latest final Git status:", current["latest"]["status"],
         "Source hashes exclude ignored files and execution evidence/log; see source-before.json",
         "Required pytest/wordlist/Docker checks remain blocked; no live model evaluation executed"]
(base / "final-checks.txt").write_text("\n".join(lines) + "\n")
files = [log, *sorted(p for p in base.rglob("*") if p.is_file()
                     and p.name != "artifact-manifest.json" and "__pycache__" not in p.parts)]
manifest = {"algorithm": "sha256", "excluded": ["artifact-manifest.json itself", "__pycache__"],
            "tested_source_manifest_sha256": current["latest"]["source_manifest_sha256"],
            "files_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
canonical = json.dumps(manifest["files_sha256"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
manifest["artifact_set_sha256"] = hashlib.sha256(canonical).hexdigest()
(base / "artifact-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print("\n".join(lines))
print("artifact_set_sha256:", manifest["artifact_set_sha256"])
