"""S1 strict configuration and import-time rejection tests, without external services."""
import os
import subprocess
import sys
import unittest

from pydantic import ValidationError

from app.config import GoMultiAgentSettings


class MultiAgentConfigTests(unittest.TestCase):
    def test_defaults_and_separate_role_models_inherit_existing_default(self):
        config = GoMultiAgentSettings.from_environment({})
        self.assertFalse(config.enabled)
        self.assertEqual((config.max_normal_calls, config.max_retries, config.max_model_calls,
                          config.max_repairs, config.max_validations), (7, 1, 8, 2, 3))
        self.assertEqual(config.role_model("code", "current-model"), "current-model")
        configured = GoMultiAgentSettings(supervisor_model="review-model", code_model="code-model")
        self.assertEqual(configured.role_model("supervisor", "default"), "review-model")
        self.assertEqual(configured.role_model("code", "default"), "code-model")
        with self.assertRaises(ValueError):
            config.role_model("shell", "default")
        with self.assertRaises(ValueError):
            config.role_model("code", " ")

    def test_illegal_limits_types_nonfinite_time_and_model_rejected(self):
        updates = [{"max_repairs": 3}, {"max_repairs": -1}, {"max_model_calls": 9},
                   {"max_normal_calls": 8}, {"max_retries": 2}, {"max_validations": 4}, {"max_retrievals": 2},
                   {"max_model_calls": 6}, {"max_normal_calls": 6}, {"max_retries": 0},
                   {"max_model_calls": 0}, {"max_model_calls": True}, {"enabled": "yes"},
                   {"task_timeout": float("nan")}, {"task_timeout": float("inf")},
                   {"task_timeout": 0}, {"task_timeout": 361}, {"code_timeout": 121},
                   {"validation_timeout": -1}, {"supervisor_timeout": 0}, {"cleanup_timeout": 16},
                   {"task_timeout": 60}, {"code_window": -1}, {"supervisor_model": " "}, {"code_model": "a\nb"},
                   {"code_model": "x" * 257}, {"code_input_tokens": 0}, {"supervisor_output_tokens": 0},
                   {"safety_tokens": -1}, {"enabled": True}, {"code_window": 100}, {"unknown_limit": 9}]
        for update in updates:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                GoMultiAgentSettings(**update)

    def test_valid_reduced_limits_and_windows_are_independent_of_context_feature(self):
        config = GoMultiAgentSettings.from_environment({
            "AIROBOT_GO_MULTI_AGENT_ENABLED": "true", "AIROBOT_GO_MULTI_AGENT_SUPERVISOR_WINDOW": "32768",
            "AIROBOT_GO_MULTI_AGENT_CODE_WINDOW": "32768", "AIROBOT_CONTEXT_MODE": "off",
            "AIROBOT_GO_MULTI_AGENT_MAX_RETRIES": "0", "AIROBOT_GO_MULTI_AGENT_MAX_MODEL_CALLS": "7",
        })
        self.assertTrue(config.enabled)
        self.assertEqual(config.max_retries, 0)
        self.assertEqual(config.max_model_calls, 7)
        # Retaining a shared retry ceiling while tightening the total is also legal.
        self.assertEqual(GoMultiAgentSettings(max_model_calls=7).max_retries, 1)

    def test_environment_rejects_typographical_boolean_numeric_and_nan_values(self):
        for key, value in [("ENABLED", "yes"), ("MAX_REPAIRS", "-1"), ("MAX_REPAIRS", "1.5"),
                           ("MAX_MODEL_CALLS", "nine"), ("MAX_MODEL_CALLS", "９"),
                           ("TASK_TIMEOUT", "nan"), ("CODE_TIMEOUT", "inf"), ("MAX_RETRIES", ""),
                           ("MISSPELLED_LIMIT", "1")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                GoMultiAgentSettings.from_environment({"AIROBOT_GO_MULTI_AGENT_" + key: value})

    def test_invalid_configuration_rejects_application_import_before_startup(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AIROBOT_GO_MULTI_AGENT_")}
        env.update(PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1")
        cases = [({"AIROBOT_GO_MULTI_AGENT_MAX_MODEL_CALLS": "9"}, "max_model_calls"),
                 ({"AIROBOT_GO_MULTI_AGENT_ENABLED": "true", "AIROBOT_LLM_MODEL": " ",
                   "AIROBOT_GO_MULTI_AGENT_SUPERVISOR_WINDOW": "32768",
                   "AIROBOT_GO_MULTI_AGENT_CODE_WINDOW": "32768"}, "at least 1 character")]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                result = subprocess.run([sys.executable, "-c", "import app.config"], env={**env, **changes},
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
