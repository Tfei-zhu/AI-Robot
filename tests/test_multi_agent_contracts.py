"""S1 real contract/hash behavior; standard unittest, no model or sandbox calls."""
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from app.go_validation.contracts import (
    CodeArtifact, GoTaskResult, RepairRequest, ReviewIssue, TaskSpec, artifact_hash,
    ValidationReport, bind_validation, freeze_artifact,
)
from app.go_validation.fixtures import ACCEPTANCE_FILE, ACCEPTANCE_TESTS
from multi_agent_fixtures import artifact, budget, bundle, issue, review, task, validation


class MultiAgentContractsTests(unittest.TestCase):
    def test_task_preserves_original_and_server_interface(self):
        spec = task()
        self.assertEqual(spec.original_requirement, "等待取消并传播错误，不能提前返回")
        self.assertIn("WaitForCancel(ctx context.Context) error", spec.server_contract)
        self.assertEqual(TaskSpec.model_validate_json(spec.model_dump_json()), spec)

    def test_task_rejects_duplicate_dangling_missing_and_bad_types(self):
        changes = [
            {"requirements": [task().requirements[0].model_dump()] * 2},
            {"acceptance_criteria": [{"criterion_id": "a", "requirement_id": "unknown", "text": "check"}]},
            {"acceptance_criteria": [task().acceptance_criteria[0].model_dump()]},
            {"requirements": [{**r.model_dump(), "required": False} for r in task().requirements]},
            {"original_requirement": "   "}, {"task_id": "../task"}, {"task_id": "x" * 129},
            {"requirements": [{"requirement_id": "r", "text": "x", "required": "false"}]},
            {"extra_privilege": "shell"},
        ]
        for update in changes:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskSpec.model_validate({**task().model_dump(), **update})

    def test_hash_is_computed_after_trusted_test_injection(self):
        raw, art = bundle(), artifact()
        self.assertNotEqual(artifact_hash(raw.files), art.artifact_hash)
        self.assertEqual(artifact_hash(art.files), art.artifact_hash)
        self.assertEqual(next(f.content for f in art.files if f.name == ACCEPTANCE_FILE),
                         ACCEPTANCE_TESTS[task().scenario])
        self.assertEqual(CodeArtifact.model_validate_json(art.model_dump_json()), art)

    def test_hash_ignores_order_but_covers_names_source_tests_and_exact_utf8(self):
        art = artifact()
        self.assertEqual(artifact_hash(reversed(art.files)), art.artifact_hash)
        for index, field, suffix in [(0, "content", "\n// 更改"), (1, "content", "\n"),
                                     (2, "content", "\n// trusted test changed")]:
            files = [f.model_dump() for f in art.files]
            files[index][field] += suffix
            with self.subTest(index=index):
                self.assertNotEqual(artifact_hash(files), art.artifact_hash)
        files = [f.model_dump() for f in art.files]
        files[0]["name"] = "renamed.go"
        self.assertNotEqual(artifact_hash(files), art.artifact_hash)

    def test_hash_or_trusted_test_tampering_is_rejected_even_if_rehashed(self):
        art = artifact()
        modified = art.model_dump()
        modified["files"][0]["content"] += "\n// changed"
        with self.assertRaises(ValidationError):
            CodeArtifact.model_validate(modified)
        modified = json.loads(art.model_dump_json())
        modified["files"][-1]["content"] = "package example\n"
        modified["artifact_hash"] = artifact_hash(modified["files"])
        with self.assertRaises(ValidationError):
            CodeArtifact.model_validate(modified)
        raw = bundle()
        raw.files.append(art.bundle().files[-1])
        with self.assertRaisesRegex(ValueError, "不能提交"):
            freeze_artifact(task(), raw, round=0)

    def test_snapshot_and_nested_files_are_immutable_and_runner_gets_copy(self):
        art = artifact()
        with self.assertRaises(ValidationError):
            art.round = 1
        with self.assertRaises(ValidationError):
            art.files[0].content = "changed"
        mutable = art.bundle()
        mutable.files[0].content = "changed"
        self.assertEqual(artifact_hash(art.files), art.artifact_hash)

    def test_validation_binding_never_relabels_a_previous_execution(self):
        art = artifact()
        report = validation(art)
        other = artifact(round=1)
        with self.assertRaises(ValueError):
            bind_validation(report, other)
        with self.assertRaises(ValueError):
            bind_validation(ValidationReport(status="passed", container_removed=True), art)
        self.assertEqual(bind_validation(report, art), report)

    def test_review_rejects_blocking_approval_duplicates_and_invalid_location(self):
        art = artifact()
        for changes in ({"issues": [issue()]},
                        {"requirement_checks": [review(art).requirement_checks[0]] * 2},
                        {"verdict": "revise", "issues": [issue(), issue()]}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                review(art, **changes)
        for changes in ({"line": 0}, {"line": 1, "file": None}, {"file": "../x.go"},
                        {"severity": "critical"}, {"evidence": " "}, {"repair_instruction": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ReviewIssue.model_validate(issue(**changes))

    def test_repair_request_binds_task_round_both_reports_and_full_source(self):
        art = artifact()
        data = dict(task_spec=task(), previous_artifact=art, validation_report=validation(art, "failed"),
                    review_report=review(art, verdict="revise", issues=[issue()]), remaining_budget=budget(), round=1)
        request = RepairRequest(**data)
        self.assertEqual(request.previous_artifact.files, art.files)
        self.assertEqual(RepairRequest.model_validate_json(request.model_dump_json()), request)
        for change in ({"round": 2}, {"review_report": review(artifact(1))},
                       {"validation_report": validation(artifact(1))},
                       {"validation_report": validation(art, "unavailable")},
                       {"remaining_budget": budget(model_calls=1)},
                       {"review_report": review(art, verdict="cannot_assess")}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                RepairRequest(**{**data, **change})
        with self.assertRaises(ValidationError):
            RepairRequest(**{**data, "validation_report": validation(art), "review_report": review(art)})

    def test_actual_legacy_report_json_remains_readable_with_nested_defaults(self):
        rows = json.loads((Path(__file__).resolve().parents[1] / "docs/go-validation-fixture-report.json").read_text())["results"]
        for row in rows:
            with self.subTest(run_id=row["run_id"]):
                result = GoTaskResult.model_validate(row)
                self.assertEqual(result.status, row["status"])
                self.assertEqual(result.workflow_version, "single-v1")
                self.assertIsNone(result.task_spec)
                self.assertEqual(result.reviews, [])
                self.assertEqual(result.agent_calls, [])
                self.assertIsNone(result.attempts[0].validation.artifact_hash)
                self.assertEqual(GoTaskResult.model_validate_json(result.model_dump_json()), result)

    def test_multi_result_cannot_self_declare_passed_without_evidence(self):
        with self.assertRaises(ValidationError):
            GoTaskResult(run_id="run", status="passed", scenario="context_cancel", workflow_version="multi-v1")
        art = artifact()
        data = dict(run_id="run", status="passed", scenario="context_cancel", workflow_version="multi-v1",
                    task_spec=task(), artifacts=[art], reviews=[review(art)],
                    attempts=[dict(number=0, bundle=art.bundle(), validation=validation(art))])
        result = GoTaskResult(**data)
        self.assertEqual(GoTaskResult.model_validate_json(result.model_dump_json()), result)
        data["attempts"][0]["validation"] = validation(art, "failed")
        with self.assertRaises(ValidationError):
            GoTaskResult(**data)


if __name__ == "__main__":
    unittest.main()
