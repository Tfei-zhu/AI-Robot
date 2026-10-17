"""S1 actual Python Docker adapter with substituted client process; no real Docker."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.go_validation.runner import DockerGoRunner
from multi_agent_fixtures import artifact


class RunnerBindingTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, claimed_hash=None):
        art = artifact()
        payload = {"status": "passed", "go_version": "1.26.2", "stages": [
            {"stage": stage, "exit_code": 0} for stage in ("policy", "compile", "vet", "test")]}
        if claimed_hash is not None:
            payload["artifact_hash"] = claimed_hash
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        stdout.feed_data(json.dumps(payload).encode()); stdout.feed_eof(); stderr.feed_eof()
        written = bytearray()
        proc = SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr, wait=AsyncMock(return_value=0),
                               stdin=SimpleNamespace(write=written.extend, drain=AsyncMock(), close=lambda: None))
        runner = DockerGoRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as create, \
             patch.object(runner, "_remove", AsyncMock(return_value=True)):
            result = await runner.validate(art.bundle())
        self.assertEqual(create.await_args.args[0], "docker")
        self.assertEqual(json.loads(written), art.bundle().model_dump())
        return art, result

    async def test_report_hash_is_computed_from_exact_submitted_copy(self):
        art, report = await self.execute()
        self.assertEqual(report.status, "passed")
        self.assertEqual(report.artifact_hash, art.artifact_hash)
        self.assertTrue(report.container_removed)

    async def test_conflicting_sandbox_hash_cannot_override_server_version(self):
        art, report = await self.execute("0" * 64)
        self.assertEqual(report.status, "unavailable")
        self.assertEqual(report.artifact_hash, art.artifact_hash)
        self.assertIn("版本不匹配", report.stages[-1].output)

    async def test_missing_docker_still_binds_failure_without_host_execution(self):
        art = artifact()
        async def missing(*args, **kwargs):
            self.assertEqual(args[0], "docker")
            raise FileNotFoundError("fixture missing Docker")
        with patch("asyncio.create_subprocess_exec", missing):
            report = await DockerGoRunner().validate(art.bundle())
        self.assertEqual(report.status, "unavailable")
        self.assertFalse(report.container_removed)
        self.assertEqual(report.artifact_hash, art.artifact_hash)


if __name__ == "__main__":
    unittest.main()
