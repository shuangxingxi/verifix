from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.tools.errors import ForbiddenBranchError, PathEscapeError, ToolArgumentError, ToolNotFoundError
from app.tools.mcp import ALLOWED_TOOLS, JsonRpcRequest, McpServer
from app.tools.sandbox import SandboxInfraError, SandboxPolicy, SandboxRunner
from app.tools.workspace import LocalRepoPublisher, LocalWorkspace


class SandboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SandboxPolicy.from_config(load_config())
        self.runner = SandboxRunner(self.policy)

    def test_policy_reflects_config_constraints(self) -> None:
        self.assertEqual(self.policy.memory_mb, 1024)
        self.assertEqual(self.policy.timeout_seconds, 60)
        self.assertEqual(self.policy.uid, 10001)
        self.assertLessEqual(self.policy.cpu, 1.0)

    def test_argv_carries_all_six_isolation_flags(self) -> None:
        with TemporaryDirectory() as tmp:
            argv = self.runner.build_argv(Path(tmp), "tests/security/test_iss_001.py")
        rendered = " ".join(argv)
        self.assertIn("--network=none", rendered)
        self.assertIn(":/src:ro", rendered)
        self.assertIn("--user=10001:10001", rendered)
        self.assertIn("--memory=1024m", rendered)
        self.assertIn("--cap-drop=ALL", rendered)
        self.assertIn("--read-only", rendered)
        self.assertIn("--security-opt=no-new-privileges", rendered)
        self.assertIn("--pids-limit=128", rendered)
        self.assertIn("--cpus=1.0", rendered)

    def test_isolation_report_satisfied(self) -> None:
        report = self.runner.isolation_report()
        self.assertTrue(report.satisfied)
        self.assertEqual(len(report.checks), 6)

    def test_report_detects_tampered_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            argv = self.runner.build_argv(Path(tmp), "t")
        poisoned = [arg for arg in argv if arg != "--network=none"]
        report = self.runner.isolation_report(poisoned)
        self.assertFalse(report.satisfied)
        self.assertIn("network_disabled", report.failures())

    def test_preflight_requires_backend(self) -> None:
        if shutil.which(self.policy.docker_bin) is None:
            with self.assertRaises(SandboxInfraError):
                self.runner.preflight()
        else:
            self.assertTrue(self.runner.preflight().satisfied)

    def test_policy_digest_is_stable(self) -> None:
        self.assertEqual(self.policy.digest(), SandboxPolicy.from_config(load_config()).digest())


class McpServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app").mkdir()
        (self.root / "app" / "user.py").write_text("def get_user(uid):\n    return db.query(uid)\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_user.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        self.runner = SandboxRunner(SandboxPolicy.from_config(load_config()))
        self.workspace = LocalWorkspace(self.root, self.runner)
        self.publisher = LocalRepoPublisher()
        self.server = McpServer(self.workspace, self.publisher)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exactly_eight_whitelisted_tools(self) -> None:
        names = [tool["name"] for tool in self.server.tools()]
        self.assertEqual(len(names), 8)
        self.assertEqual(tuple(names), ALLOWED_TOOLS)
        for tool in self.server.tools():
            self.assertRegex(tool["tool_id"], r"^TOOL-0[1-8]$")
            self.assertEqual(tool["tool_version"], "1.0.0")

    def test_unknown_tool_rejected(self) -> None:
        with self.assertRaises(ToolNotFoundError):
            self.server.invoke("shell.exec", {"cmd": "rm -rf /"})
        response = self.server.handle(JsonRpcRequest(method="tools/call", params={"name": "shell.exec", "arguments": {}}))
        self.assertEqual(response.error.code, -32601)

    def test_read_tree_and_file(self) -> None:
        self.assertIn("app/user.py", self.server.invoke("repo.read_tree", {})["entries"])
        content = self.server.invoke("repo.read_file", {"path": "app/user.py"})["content"]
        self.assertIn("def get_user", content)

    def test_path_escape_rejected(self) -> None:
        with self.assertRaises(PathEscapeError):
            self.server.invoke("repo.read_file", {"path": "../outside.py"})

    def test_search_symbol(self) -> None:
        hits = self.server.invoke("repo.search_symbol", {"symbol": "get_user"})["hits"]
        self.assertEqual(hits[0]["file"], "app/user.py")

    def test_write_file_records_digest(self) -> None:
        result = self.server.invoke("workspace.write_file", {"path": "app/new.py", "content": "x = 1\n"})
        self.assertEqual(result["size_bytes"], 6)
        self.assertEqual(len(result["sha256"]), 64)

    def test_publish_branch_namespace(self) -> None:
        ok = self.server.invoke("repo.publish_branch", {"branch": "verifix/ISS-1", "commit_message": "[step-2]", "diff_ref": "obs://d/1"})
        self.assertEqual(ok["branch"], "verifix/ISS-1")
        with self.assertRaises(ForbiddenBranchError):
            self.server.invoke("repo.publish_branch", {"branch": "main", "commit_message": "x", "diff_ref": "obs://d/2"})
        with self.assertRaises(ForbiddenBranchError):
            self.server.invoke("repo.publish_branch", {"branch": "hotfix/x", "commit_message": "x", "diff_ref": "obs://d/3"})

    def test_open_pr_requires_published_branch(self) -> None:
        with self.assertRaises(ToolArgumentError):
            self.server.invoke("repo.open_pr", {"branch": "verifix/ISS-9", "title": "t", "body_ref": "obs://b/1"})
        self.server.invoke("repo.publish_branch", {"branch": "verifix/ISS-9", "commit_message": "m", "diff_ref": "obs://d/9"})
        pr = self.server.invoke("repo.open_pr", {"branch": "verifix/ISS-9", "title": "t", "body_ref": "obs://b/1"})
        self.assertEqual(pr["base"], "main")

    def test_merge_release_auto_only(self) -> None:
        with self.assertRaises(ForbiddenBranchError):
            self.publisher.merge_release_auto("main")
        with self.assertRaises(ForbiddenBranchError):
            self.publisher.merge_release_auto("verifix/ISS-1")
        merged = self.publisher.merge_release_auto("release/auto")
        self.assertEqual(merged["merged_into"], "release/auto")

    def test_run_tests_goes_through_sandbox(self) -> None:
        if shutil.which(self.runner.policy.docker_bin) is None:
            with self.assertRaises(SandboxInfraError):
                self.server.invoke("workspace.run_tests", {"test_path": "tests/test_user.py"})
        else:
            self.assertIn("exit_code", self.server.invoke("workspace.run_tests", {"test_path": "tests/test_user.py"}))

    def test_run_tests_rejects_missing_path(self) -> None:
        with self.assertRaises(ToolArgumentError):
            self.server.invoke("workspace.run_tests", {})


if __name__ == "__main__":
    unittest.main()