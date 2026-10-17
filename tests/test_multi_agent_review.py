"""S1 server rejection/correct transition cases; reports are explicit fixtures."""
import unittest

from app.agents.go_workflow import WorkflowPhase, decide_after_review, transition
from multi_agent_fixtures import artifact, budget, issue, review, task, validation


class MultiAgentReviewTests(unittest.TestCase):
    def decide(self, *, art=None, machine=None, audited=None, remaining=None, **extra):
        art = art or artifact()
        return decide_after_review(task(), art, machine or validation(art),
                                   audited if audited is not None else review(art), remaining or budget(), **extra)

    def test_only_complete_matching_evidence_passes_and_suggestions_do_not_force_repair(self):
        self.assertEqual(self.decide().status, "passed")
        self.assertEqual(self.decide(audited=review(artifact(), issues=[issue(severity="suggestion")])).status, "passed")
        # Finishing an already successful last allowed call does not require another call.
        self.assertEqual(self.decide(remaining=budget(normal_calls=0, retries=0, model_calls=0, validations=0)).status, "passed")

    def test_failed_validation_cannot_be_overridden_by_model_approve(self):
        result = self.decide(machine=validation(artifact(), "failed"))
        self.assertEqual((result.action, result.status, result.reason), ("repair", "running", "validation_failed"))
        result = self.decide(art=artifact(2), machine=validation(artifact(2), "failed"))
        self.assertEqual((result.status, result.reason), ("failed", "repair_limit"))

    def test_invalid_approve_with_blocking_is_rejected_even_for_bypassed_model_instances(self):
        report = review(artifact(), verdict="revise", issues=[issue()]).model_copy(update={"verdict": "approve"})
        result = self.decide(audited=report)
        self.assertEqual((result.action, result.reason), ("retry_review", "review_error"))

    def test_mismatched_hash_missing_binding_and_old_round_never_pass(self):
        art = artifact()
        for key, value in [("artifact_hash", "0" * 64), ("artifact_id", "other"), ("task_id", "other"), ("round", 1)]:
            with self.subTest(report="review", key=key):
                self.assertEqual(self.decide(audited=review(art).model_copy(update={key: value})).reason, "review_error")
            with self.subTest(report="validation", key=key):
                self.assertEqual(self.decide(machine=validation(art).model_copy(update={key: value})).reason, "validation_report_error")
        self.assertEqual(self.decide(machine=validation(art).model_copy(update={"artifact_hash": None})).status, "failed")

    def test_missing_required_check_is_review_error_and_cannot_shrink_task_scope(self):
        report = review(artifact(), requirement_checks=[review(artifact()).requirement_checks[0]])
        self.assertEqual(self.decide(audited=report).action, "retry_review")
        exhausted = self.decide(audited=report, remaining=budget(retries=0, model_calls=7))
        self.assertEqual((exhausted.status, exhausted.reason), ("failed", "review_error"))

    def test_explicit_requirement_failure_or_blocker_forces_repair(self):
        art = artifact()
        for status in ("fail", "unknown"):
            checks = [c.model_dump() for c in review(art).requirement_checks]
            checks[0]["status"] = status
            self.assertEqual(self.decide(audited=review(art, requirement_checks=checks)).reason, "requirements_failed")
        result = self.decide(audited=review(art, verdict="revise", issues=[issue()]))
        self.assertEqual((result.action, result.reason), ("repair", "requirements_failed"))

    def test_invalid_review_unknown_requirement_file_and_line_cannot_pass(self):
        art = artifact()
        for changes in ({"requirement_id": "unknown"}, {"file": "missing.go"}, {"line": 1000}):
            report = review(art, verdict="revise", issues=[issue(**changes)])
            with self.subTest(changes=changes):
                self.assertEqual(self.decide(audited=report).reason, "review_error")
        report = review(art).model_dump()
        report["requirement_checks"][0]["requirement_id"] = "model-chosen-substitute"
        self.assertEqual(self.decide(audited=report).reason, "review_error")
        self.assertEqual(self.decide(audited={"verdict": "approve"}).reason, "review_error")

    def test_claimed_machine_pass_requires_actual_complete_stages_cleanup_and_version(self):
        good = validation(artifact())
        variants = [{"stages": []}, {"stages": list(reversed(good.stages))},
                    {"container_removed": False}, {"go_version": "1.26.5"},
                    {"stages": [*good.stages[:-1], good.stages[-1].model_copy(update={"exit_code": 1})]},
                    {"stages": [*good.stages[:-1], good.stages[-1].model_copy(update={"truncated": True})]}]
        for change in variants:
            with self.subTest(change=change):
                result = self.decide(machine=good.model_copy(update=change))
                self.assertEqual((result.status, result.reason), ("failed", "validation_report_error"))

    def test_environment_cancel_and_deadline_stop_without_review_retry(self):
        for status in ("unavailable", "timeout", "cancelled"):
            with self.subTest(status=status):
                result = self.decide(machine=validation(artifact(), status), audited={"bad": "review"})
                self.assertEqual((result.action, result.status), ("finish", status))
        self.assertEqual(self.decide(cancelled=True).status, "cancelled")
        self.assertEqual(self.decide(remaining=budget(seconds=0)).status, "timeout")

    def test_retry_shares_total_budget_and_failure_is_preserved_when_exhausted(self):
        report = review(artifact(), verdict="cannot_assess")
        for changes in ({"retries": 0, "model_calls": 7}, {"model_calls": 0}):
            with self.subTest(changes=changes):
                result = self.decide(audited=report, remaining=budget(**changes))
                self.assertEqual((result.status, result.reason), ("failed", "review_error"))

    def test_repair_needs_next_generation_review_and_validation_budget(self):
        for changes in ({"normal_calls": 1, "model_calls": 2}, {"model_calls": 1}, {"validations": 0}):
            with self.subTest(changes=changes):
                self.assertEqual(self.decide(machine=validation(artifact(), "failed"), remaining=budget(**changes)).status,
                                 "budget_exceeded")
        self.assertEqual(self.decide(machine=validation(artifact(), "failed"), max_repairs=0).reason, "repair_limit")
        with self.assertRaises(ValueError):
            self.decide(max_repairs=3)

    def test_unchanged_failed_artifact_stops_without_repair(self):
        result = self.decide(machine=validation(artifact(), "failed"), previous_failed_hash=artifact().artifact_hash)
        self.assertEqual((result.action, result.reason), ("finish", "no_progress"))

    def test_tampered_artifact_or_wrong_task_fails_closed(self):
        art = artifact()
        files = list(art.files)
        files[0] = files[0].model_copy(update={"content": "tampered"})
        self.assertEqual(self.decide(art=art.model_copy(update={"files": tuple(files)}),
                                     machine=validation(art), audited=review(art)).reason, "artifact_error")
        self.assertEqual(self.decide(art=art.model_copy(update={"task_id": "other-task"}),
                                     machine=validation(art), audited=review(art)).reason, "artifact_error")

    def test_legal_transitions_and_terminal_is_absorbing(self):
        p = WorkflowPhase
        for current, target in [(p.PLANNING, p.GENERATING), (p.GENERATING, p.VALIDATING),
                                (p.VALIDATING, p.REVIEWING), (p.REVIEWING, p.REVIEWING),
                                (p.REVIEWING, p.REPAIRING), (p.REPAIRING, p.VALIDATING)]:
            self.assertEqual(transition(current, target), target)
        for target in p:
            with self.subTest(target=target), self.assertRaises(ValueError):
                transition(p.FINISHED, target)
        with self.assertRaises(ValueError):
            transition(p.PLANNING, p.REVIEWING)


if __name__ == "__main__":
    unittest.main()
