"""Five reversible directed failures in an isolated source copy, never the checkout.

Passing control -> mutant assertion failure -> restored passing control is required.
Syntax/import errors, killed processes and timeouts do not count as mutation kills.
"""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from run_checks import OUT, ROOT, PYTHON, baseline, env, run


CASES = [
    ("machine-gate", "app/agents/go_workflow.py",
     'if machine_passed(validation) and review.verdict == "approve" and complete and not blocking:',
     'if True and review.verdict == "approve" and complete and not blocking:',
     "tests/test_multi_agent_review.py::MultiAgentReviewTests::test_failed_validation_cannot_be_overridden_by_model_approve"),
    ("review-hash", "app/go_validation/contracts.py",
     'if any(getattr(self, key) != getattr(artifact, key)\n               for key in ("task_id", "artifact_id", "artifact_hash", "round")):',
     'if any(getattr(self, key) != getattr(artifact, key)\n               for key in ("task_id", "artifact_id", "round")):',
     "tests/test_multi_agent_review.py::MultiAgentReviewTests::test_mismatched_hash_missing_binding_and_old_round_never_pass"),
    ("trusted-test", "app/go_validation/contracts.py",
     'if len(trusted) != 1 or trusted[0].content != ACCEPTANCE_TESTS[self.scenario]:',
     'if len(trusted) != 1:',
     "tests/test_multi_agent_contracts.py::MultiAgentContractsTests::test_hash_or_trusted_test_tampering_is_rejected_even_if_rehashed"),
    ("total-budget", "app/agents/go_workflow.py",
     'if total and self._used["model"] + 1 > self._max["model"]:',
     'if False and self._used["model"] + 1 > self._max["model"]:',
     "tests/test_multi_agent_acceptance.py::AcceptanceCounterexamples::test_total_guard_blocks_retry_with_unused_retry_quota"),
    ("cancel-propagation", "app/agents/role_runtime.py",
     'raise  # 取消必须向上传播，由编排层保存进度并清理。',
     'return ""  # S7 isolated mutant: swallow cancellation',
     "tests/test_multi_agent_workflow.py::ClosedLoopTests::test_cancellation_propagates_and_no_further_requests"),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    original = baseline["snapshot"](ROOT)
    rows = []
    copy = Path(tempfile.mkdtemp(prefix="airobot-s7-mutations-", dir="/private/tmp"))
    try:
        for relative in original["files_sha256"]:
            dest = copy / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, dest)
        overrides = {"PYTHONPATH":os.pathsep.join([str(OUT.parent / "s0.1-20261017/offline_guard"), str(copy), str(copy / "tests")]),
                     "PYTHONPYCACHEPREFIX":str(copy / "pycache")}

        def check(label, nodes):
            xml = OUT / (label + ".xml")
            code = run(label,[PYTHON,"-m","pytest",*nodes,"-q","-ra","--junitxml="+str(xml)],
                       extra=overrides,cwd=copy,timeout=60)
            parsed = ET.parse(xml)
            failures = [dict(name=t.attrib["name"], text=f.text or "")
                        for t in parsed.iter("testcase") for f in t.findall("failure")]
            errors = list(parsed.iter("error"))
            return code, failures, errors

        control, _, errors = check("mutations-control",[case[4] for case in CASES])
        assert control == 0 and not errors, "Unmodified controls must pass"
        for name, relative, old, new, node in CASES:
            path = copy / relative
            pristine = path.read_bytes()
            text = pristine.decode()
            assert text.count(old) == 1, (name, "mutation target must be unique")
            modified = text.replace(old,new)
            ast.parse(modified)
            diff = "".join(difflib.unified_diff(text.splitlines(True),modified.splitlines(True),
                           fromfile=relative,tofile=relative+" (isolated mutant)"))
            (OUT / (name+".patch")).write_text(diff)
            try:
                path.write_text(modified)
                code, failures, errors = check("mutation-"+name,[node])
                killed = code == 1 and bool(failures) and not errors and all("AssertionError" in f["text"] for f in failures)
                rows.append(dict(mutation=name,source=relative,test=node,exit_code=code,killed_by_assertion=killed,
                                 original_sha256=digest(pristine),mutant_sha256=digest(modified.encode()),failures=failures))
            finally:
                path.write_bytes(pristine)
            assert path.read_bytes() == pristine
            restored, _, errors = check("restored-"+name,[node])
            rows[-1]["restored_exit_code"] = restored
            rows[-1]["restored_sha256"] = digest(path.read_bytes())
            (OUT/"mutations.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n")
            assert killed and restored == 0 and not errors, (name,"mutation did not prove the defense")
        assert all(digest((copy / p).read_bytes()) == sha for p,sha in original["files_sha256"].items())
    finally:
        shutil.rmtree(copy)
        after = baseline["snapshot"](ROOT)
        proof = dict(original_manifest=original["source_manifest_sha256"],after_manifest=after["source_manifest_sha256"],
                     checkout_unchanged=original["files_sha256"] == after["files_sha256"],
                     isolated_copy_removed=not copy.exists(),rows=rows)
        (OUT/"mutation-preservation.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n")
        assert proof["checkout_unchanged"]


if __name__ == "__main__":
    main()
