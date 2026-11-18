from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ErrorCode
from app.config import load_config
from app.domain.enums import DefectClass, IssueStatus, Severity, SourceKind, VerdictConclusion
from app.domain.models import Alert, Issue, Location
from app.repo.memory import MemoryStore
from app.tracing.callgraph import build_callgraph
from app.tracing.entrypoints import EntryKind, discover_entrypoints
from app.tracing.service import ReachabilityService, compute_priority
from app.tracing.taint import trace_taint

REACHABLE_APP = """import os

from flask import Flask

app = Flask(__name__)


@app.get("/run")
def run(host):
    os.system("ping " + host)
"""

UNREACHABLE_APP = """import os

from flask import Flask

app = Flask(__name__)


@app.get("/run")
def run(host):
    return "ok"


def unused_helper(host):
    os.system("ping " + host)
"""

DYNAMIC_APP = """import os

from flask import Flask

app = Flask(__name__)


@app.get("/dyn")
def dyn(payload):
    return dispatch(payload)


def dispatch(payload):
    getattr(os, "system")("ping " + payload)
"""

NO_ENTRY_APP = """import os


def plain(host):
    os.system("ping " + host)
"""


def write_project(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


def make_issue(store: MemoryStore, issue_id: str, file: str, line: int, severity: Severity = Severity.HIGH) -> Issue:
    issue = Issue(
        issue_id=issue_id,
        repo="demo",
        code_version="abc123",
        defect_class=DefectClass.COMMAND_INJECTION,
        severity=severity,
        status=IssueStatus.RECEIVED,
        fingerprint=("f" * 63) + issue_id[-1],
    )
    store.add(issue)
    store.link_alert(
        issue_id,
        Alert(
            alert_ref=f"check:{issue_id}",
            source_kind=SourceKind.CHECK,
            rule_id="py/command-injection",
            location=Location(file=file, line=line),
            raw_severity=severity,
            snippet_fingerprint="s" * 64,
            defect_class=DefectClass.COMMAND_INJECTION,
        ),
    )
    return issue


class EntryPointTest(unittest.TestCase):
    def test_http_and_scheduler_entries_discovered(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": REACHABLE_APP})
            entries, errors = discover_entrypoints(root)
            self.assertEqual(errors, [])
            self.assertEqual(len(entries), 1)
            self.assertIs(entries[0].kind, EntryKind.HTTP_ROUTE)
            self.assertEqual(entries[0].route, "/run")

    def test_no_entrypoints_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"plain.py": NO_ENTRY_APP})
            entries, _ = discover_entrypoints(root)
            self.assertEqual(entries, [])

    def test_callgraph_builds_nodes_and_edges(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": DYNAMIC_APP})
            graph = build_callgraph(root)
            self.assertGreaterEqual(graph.function_count(), 2)
            self.assertTrue(graph.has_dynamic_calls())
            entry_node = graph.node_for_function("app.py", "dyn")
            self.assertIsNotNone(entry_node)


class TaintTest(unittest.TestCase):
    def test_direct_sink_is_reachable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": REACHABLE_APP})
            entries, _ = discover_entrypoints(root)
            graph = build_callgraph(root)
            sink = graph.node_for_file_line("app.py", 10)
            result = trace_taint(graph, entries[0], sink)
            self.assertIs(result.conclusion, VerdictConclusion.REACHABLE)
            self.assertTrue(result.path)
            self.assertGreaterEqual(result.confidence, 0.6)

    def test_dynamic_call_downgrades_to_suspected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": DYNAMIC_APP})
            entries, _ = discover_entrypoints(root)
            graph = build_callgraph(root)
            sink = graph.node_for_file_line("app.py", 13)
            result = trace_taint(graph, entries[0], sink)
            self.assertIs(result.conclusion, VerdictConclusion.SUSPECTED)
            self.assertTrue(result.incomplete)
            self.assertIn("不完整", result.basis)


class ReachabilityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.store = MemoryStore()
        self.service = ReachabilityService(self.store, self.config)

    def test_reachable_issue_transitions_to_reachable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": REACHABLE_APP})
            issue = make_issue(self.store, "ISS-1", "app.py", 10)
            outcome = self.service.analyze(issue, root)
            self.assertIs(outcome.issue_status, IssueStatus.REACHABLE)
            self.assertIs(outcome.verdict.conclusion, VerdictConclusion.REACHABLE)
            self.assertTrue(outcome.taint_path)
            self.assertEqual(self.store.get("ISS-1").status, IssueStatus.REACHABLE)
            effective = self.store.effective("ISS-1")
            self.assertIsNotNone(effective)

    def test_unreachable_issue_is_archived_with_basis(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": UNREACHABLE_APP})
            issue = make_issue(self.store, "ISS-2", "app.py", 14)
            outcome = self.service.analyze(issue, root)
            self.assertIs(outcome.issue_status, IssueStatus.ARCHIVED)
            self.assertIs(outcome.verdict.conclusion, VerdictConclusion.UNREACHABLE)
            self.assertIn("未找到", outcome.verdict.basis)
            self.assertEqual(self.store.get("ISS-2").status, IssueStatus.ARCHIVED)

    def test_empty_entrypoints_marks_suspected_not_archived(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"plain.py": NO_ENTRY_APP})
            issue = make_issue(self.store, "ISS-3", "plain.py", 5)
            outcome = self.service.analyze(issue, root)
            self.assertIs(outcome.issue_status, IssueStatus.SUSPECTED)
            self.assertIn("入口点识别为空", outcome.message)

    def test_timeout_downgrades_to_suspected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": REACHABLE_APP})
            issue = make_issue(self.store, "ISS-4", "app.py", 10)
            outcome = self.service.analyze(issue, root, timeout_seconds=-1)
            self.assertIs(outcome.issue_status, IssueStatus.SUSPECTED)
            self.assertIs(outcome.error_code, ErrorCode.VERDICT_TIMEOUT)
            self.assertIn("判定超时", outcome.message)

    def test_priority_prefers_reachable_high_confidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": REACHABLE_APP})
            reachable = make_issue(self.store, "ISS-5", "app.py", 10, Severity.HIGH)
            other = make_issue(self.store, "ISS-6", "app.py", 10, Severity.HIGH)
            reachable_outcome = self.service.analyze(reachable, root)
            suspected = self.store.add_verdict(
                __import__("app.domain.models", fromlist=["Verdict"]).Verdict(
                    verdict_id="V-suspect",
                    issue_id="ISS-6",
                    conclusion=VerdictConclusion.SUSPECTED,
                    confidence=0.4,
                    basis="dynamic calls",
                    decided_by="tracer",
                )
            )
            self.assertIsNotNone(self.store.get("ISS-6"))
            self.assertGreater(
                reachable_outcome.priority,
                compute_priority(self.store.get("ISS-6"), suspected),
            )
            del other

    def test_review_creates_new_effective_verdict(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_project(root, {"app.py": UNREACHABLE_APP})
            issue = make_issue(self.store, "ISS-7", "app.py", 14)
            outcome = self.service.analyze(issue, root)
            original = outcome.verdict
            assert original is not None
            reviewed = self.service.review(
                original.verdict_id,
                actor="security-lead",
                reason="人工复核：存在动态入口未纳入",
                conclusion=VerdictConclusion.SUSPECTED,
                confidence=0.5,
            )
            history = self.store.history("ISS-7")
            self.assertEqual(len(history), 2)
            self.assertFalse(history[0].is_effective)
            self.assertTrue(reviewed.is_effective)
            self.assertIs(reviewed.conclusion, VerdictConclusion.SUSPECTED)

    def test_review_unknown_verdict_raises(self) -> None:
        with self.assertRaises(Exception):
            self.service.review("V-missing", "actor", "reason")


if __name__ == "__main__":
    unittest.main()