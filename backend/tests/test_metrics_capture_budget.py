from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import load_config
from app.container import AppContainer
from app.domain.models import MetricSnapshotRef, RecalcRun
from app.evidence.store import LocalEvidenceStore
from app.main import create_app
from app.metrics.capture_health import (
    CAPTURE_WARNINGS,
    WRITE_BLOCK_BUDGET_MS,
    CaptureMetrics,
    evaluate_capture_health,
)
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.types import RecalcTrigger
from app.metrics.snapshot import (
    SNAPSHOT_KEY_PREFIX,
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotBuilder,
    SnapshotVerifier,
    encode_payload,
)
from app.repo.memory import MemoryStore
from tests.support.perf_fixture import NOW, TIER, WINDOW, build_perf02_store, build_small_store

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "backend" / "tests" / "support"
GOLDEN = json.loads((SUPPORT / "snapshot_golden.json").read_text(encoding="utf-8"))
SMALL_GOLDEN = json.loads((SUPPORT / "snapshot_golden_small.json").read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def metrics_with(
    *,
    write_block_ms: int = 1,
    capture_ms: int | None = None,
    capture_total_ms: int | None = None,
    encode_count: int = 1,
) -> CaptureMetrics:
    if capture_total_ms is None:
        capture_total_ms = max(20, write_block_ms + 1)
    if capture_ms is None:
        capture_ms = max(write_block_ms, capture_total_ms)
    capture_ms = max(capture_ms, write_block_ms)
    capture_total_ms = max(capture_total_ms, capture_ms)
    return CaptureMetrics(
        write_block_ms=write_block_ms,
        capture_ms=capture_ms,
        capture_total_ms=capture_total_ms,
        encode_count=encode_count,
        segment_ms={"clone": write_block_ms, "build": 2, "encode": 3, "archive": 4, "chain": 5},
    )


class GoldenSnapshotTest(unittest.TestCase):
    """PB-05 / NB-06：改造前后 payload/digest/snapshot_id/归档字节逐字节等价。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.root = Path(cls.tmp.name)
        cls.store, cls.scale = build_perf02_store()
        cls.evidence = LocalEvidenceStore(cls.root / "evidence")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _capture(self):
        return SnapshotBuilder(self.store, self.evidence).capture(WINDOW, TIER)

    def test_golden_four_targets_match_frozen_baseline(self) -> None:
        envelope = self._capture()
        payload_bytes = encode_payload(envelope.payload)
        archive = (self.root / "evidence" / SNAPSHOT_KEY_PREFIX / f"{envelope.ref.snapshot_id}.json").read_bytes()
        self.assertEqual(sha256_bytes(payload_bytes), GOLDEN["payload_sha256"], "payload_sha256 漂移")
        self.assertEqual(envelope.ref.digest, GOLDEN["digest"], "digest 漂移")
        self.assertEqual(envelope.ref.snapshot_id, GOLDEN["snapshot_id"], "snapshot_id 漂移")
        self.assertEqual(sha256_bytes(archive), GOLDEN["archive_sha256"], "archive_sha256 漂移")
        self.assertEqual(len(payload_bytes), GOLDEN["payload_bytes"], "payload_bytes 漂移")
        self.assertEqual(len(archive), GOLDEN["archive_bytes"], "archive_bytes 漂移")

    def test_payload_key_set_and_order_frozen(self) -> None:
        payload = self._capture().payload
        self.assertEqual(list(payload.keys()), GOLDEN["payload_keys_ordered"], "payload 键序漂移")
        self.assertEqual(sorted(payload.keys()), GOLDEN["payload_keys"], "payload 键集合漂移")
        self.assertEqual(payload["schema_version"], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(payload["schema_version"], 1)

    def test_encode_payload_is_digest_source(self) -> None:
        envelope = self._capture()
        self.assertEqual(sha256_bytes(encode_payload(envelope.payload)), envelope.ref.digest)
        self.assertEqual(envelope.ref.issue_count, 1100)
        self.assertEqual(envelope.ref.event_count, 12000)

    def test_fixture_scale_is_frozen(self) -> None:
        self.assertEqual(self.scale["issues"], 1100)
        self.assertEqual(self.scale["runs"], 1000)
        self.assertEqual(self.scale["events"], 12000)
        self.assertEqual(self.scale["events_per_run"], 12)


class SingleEncodingTest(unittest.TestCase):
    """F-07：同一 payload 的 canonical 编码次数恒为 1。"""

    def test_json_dumps_called_once_per_capture(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            builder = SnapshotBuilder(store, LocalEvidenceStore(Path(tmp) / "evidence"))
            with mock.patch("app.metrics.snapshot.json.dumps", wraps=json.dumps) as spy:
                envelope = builder.capture(WINDOW, TIER)
            self.assertEqual(spy.call_count, 1, "同一 payload 被重复编码")
        self.assertEqual(sha256_bytes(encode_payload(envelope.payload)), envelope.ref.digest)


class CaptureMetricsTest(unittest.TestCase):
    """P2-2.1：纳秒边界换算与三条自洽等式。"""

    def test_three_equations_hold(self) -> None:
        t0 = 1_000_000
        t1 = t0 + 3_000_000
        t2 = t1 + 7_000_000
        t3 = t2 + 11_000_000
        t4 = t3 + 13_000_000
        t5 = t4 + 17_000_000
        metrics = CaptureMetrics.from_ns(t0, t1, t2, t3, t4, t5, 1)
        segment = metrics.segment_ms
        self.assertLessEqual(abs(sum(segment.values()) - metrics.capture_total_ms), 1, "segment_sum == capture_total_ms")
        self.assertEqual(segment["clone"], metrics.write_block_ms, "segment.clone == write_block_ms")
        self.assertLessEqual(
            abs(segment["build"] + segment["encode"] + segment["archive"] - (metrics.capture_ms - metrics.write_block_ms)),
            1,
            "build+encode+archive == capture_ms - write_block_ms",
        )
        self.assertEqual(metrics.capture_total_ms, (t5 - t0) // 1_000_000)
        self.assertEqual(metrics.encode_count, 1)

    def test_milliseconds_are_floored(self) -> None:
        metrics = CaptureMetrics.from_ns(0, 199_600_000, 199_600_000, 199_600_000, 199_600_000, 199_600_000, 1)
        self.assertEqual(metrics.write_block_ms, 199, "向下取整失败：199.6ms 不得报成 200ms")
        self.assertEqual(evaluate_capture_health(metrics, 200), [])

    def test_non_monotonic_boundaries_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CaptureMetrics.from_ns(0, 10, 9, 12, 13, 14, 1)

    def test_zero_encode_count_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CaptureMetrics.from_ns(0, 1, 2, 3, 4, 5, 0)
        with self.assertRaises(ValueError):
            metrics_with(encode_count=0)

    def test_segment_keys_frozen(self) -> None:
        with self.assertRaises(ValueError):
            CaptureMetrics(
                write_block_ms=1,
                capture_ms=2,
                capture_total_ms=3,
                encode_count=1,
                segment_ms={"clone": 1, "build": 1, "encode": 1, "archive": 1},
            )


class CaptureHealthTest(unittest.TestCase):
    """P2-2.1：告警纯函数边界与固定顺序。"""

    def test_write_block_boundary(self) -> None:
        self.assertEqual(evaluate_capture_health(metrics_with(write_block_ms=201), 10_000), ["WRITE_BLOCK_EXCEEDED"])
        self.assertEqual(evaluate_capture_health(metrics_with(write_block_ms=200), 10_000), [])

    def test_capture_slow_boundary(self) -> None:
        self.assertEqual(evaluate_capture_health(metrics_with(capture_total_ms=201), 200), ["CAPTURE_SLOW"])
        self.assertEqual(evaluate_capture_health(metrics_with(capture_total_ms=200), 200), [])

    def test_both_warnings_keep_fixed_order(self) -> None:
        warnings = evaluate_capture_health(metrics_with(write_block_ms=201, capture_total_ms=201), 200)
        self.assertEqual(warnings, ["WRITE_BLOCK_EXCEEDED", "CAPTURE_SLOW"])
        self.assertEqual(tuple(CAPTURE_WARNINGS), ("WRITE_BLOCK_EXCEEDED", "CAPTURE_SLOW"))
        self.assertEqual(WRITE_BLOCK_BUDGET_MS, 200)

    def test_invalid_budget_rejected(self) -> None:
        for budget in (0, -1):
            with self.assertRaises(ValueError):
                evaluate_capture_health(metrics_with(), budget)


class _StepClock:
    """确定性纳秒时钟：每次取时前进固定步长，避免机器抖动影响断言。"""

    def __init__(self, step_ns: int) -> None:
        self.step_ns = step_ns
        self.value = 0

    def __call__(self) -> int:
        current = self.value
        self.value += self.step_ns
        return current


class CaptureSegmentationTest(unittest.TestCase):
    """P2-3.3：真实 capture 的分段自洽与预算告警回填。"""

    def _capture(self, *, step_ns: int, budget: int):
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            builder = SnapshotBuilder(
                store,
                LocalEvidenceStore(Path(tmp) / "evidence"),
                capture_budget_ms=budget,
                clock_ns=_StepClock(step_ns),
            )
            return builder.capture(WINDOW, TIER)

    def test_segment_equations_on_real_capture(self) -> None:
        envelope = self._capture(step_ns=2_000_000, budget=200)
        segment = envelope.ref.segment_ms
        self.assertEqual(
            segment["clone"], envelope.ref.write_block_ms, "segment.clone != write_block_ms"
        )
        self.assertLessEqual(
            abs(sum(segment.values()) - envelope.ref.capture_total_ms), 1, "segment_sum != capture_total_ms"
        )
        self.assertLessEqual(
            abs(
                segment["build"] + segment["encode"] + segment["archive"]
                - (envelope.ref.capture_ms - envelope.ref.write_block_ms)
            ),
            1,
            "build+encode+archive != capture_ms - write_block_ms",
        )
        self.assertEqual(envelope.ref.write_block_ms, 2)
        self.assertEqual(envelope.ref.capture_total_ms, 10)
        self.assertEqual(envelope.ref.encode_count, 1)
        self.assertEqual(envelope.ref.write_block_budget_ms, 200)

    def test_metrics_envelope_matches_ref(self) -> None:
        envelope = self._capture(step_ns=2_000_000, budget=200)
        metrics = envelope.metrics
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.write_block_ms, envelope.ref.write_block_ms)
        self.assertEqual(metrics.capture_ms, envelope.ref.capture_ms)
        self.assertEqual(metrics.capture_total_ms, envelope.ref.capture_total_ms)
        self.assertEqual(metrics.encode_count, envelope.ref.encode_count)
        self.assertEqual(metrics.segment_ms, envelope.ref.segment_ms)
        self.assertFalse(envelope.ref.write_block_exceeded)
        self.assertFalse(envelope.ref.capture_slow)
        self.assertEqual(evaluate_capture_health(metrics, 200), [])

    def test_tiny_budget_only_marks_capture_slow(self) -> None:
        envelope = self._capture(step_ns=2_000_000, budget=1)
        self.assertTrue(envelope.ref.capture_slow)
        self.assertFalse(envelope.ref.write_block_exceeded)
        self.assertEqual(envelope.ref.capture_budget_ms, 1)
        self.assertEqual(evaluate_capture_health(envelope.metrics, 1), ["CAPTURE_SLOW"])

    def test_both_warnings_follow_fixed_order(self) -> None:
        envelope = self._capture(step_ns=300_000_000, budget=1)
        self.assertEqual(envelope.ref.write_block_ms, 300)
        self.assertTrue(envelope.ref.write_block_exceeded)
        self.assertTrue(envelope.ref.capture_slow)
        self.assertEqual(
            evaluate_capture_health(envelope.metrics, 1), ["WRITE_BLOCK_EXCEEDED", "CAPTURE_SLOW"]
        )

    def test_invalid_budget_rejected_at_construction(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            evidence = LocalEvidenceStore(Path(tmp) / "evidence")
            for budget in (0, -1):
                with self.assertRaises(ValueError):
                    SnapshotBuilder(store, evidence, capture_budget_ms=budget)


class ReuseStabilityTest(unittest.TestCase):
    """PB-03 / PB-04：重复抓取与跨版本归档复用。"""

    def test_repeat_capture_reuses_archive_without_rewrite(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            builder = SnapshotBuilder(store, LocalEvidenceStore(Path(tmp) / "evidence"))
            first = builder.capture(WINDOW, TIER)
            self.assertFalse(first.reused)
            path = Path(tmp) / "evidence" / SNAPSHOT_KEY_PREFIX / f"{first.ref.snapshot_id}.json"
            before_bytes = path.read_bytes()
            before_mtime = path.stat().st_mtime_ns
            second = builder.capture(WINDOW, TIER)
            self.assertTrue(second.reused)
            self.assertEqual(second.ref.digest, first.ref.digest)
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(path.stat().st_mtime_ns, before_mtime, "归档文件被重写")

    def test_legacy_archive_reused_by_current_code(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            evidence_root = Path(tmp) / "evidence"
            key_dir = evidence_root / SNAPSHOT_KEY_PREFIX
            key_dir.mkdir(parents=True)
            archive = SUPPORT / "snapshot_golden" / SMALL_GOLDEN["archive_name"]
            shutil.copyfile(archive, key_dir / archive.name)
            envelope = SnapshotBuilder(store, LocalEvidenceStore(evidence_root)).capture(WINDOW, TIER)
            self.assertTrue(envelope.reused)
            self.assertEqual(envelope.ref.digest, SMALL_GOLDEN["digest"])
            report = SnapshotVerifier(LocalEvidenceStore(evidence_root)).verify(
                envelope.ref.snapshot_id, SMALL_GOLDEN["digest"]
            )
            self.assertTrue(report.digest_match)
            self.assertTrue(report.chain_valid)


class LegacyCompatibilityTest(unittest.TestCase):
    """NB-10 / RP-10：旧 ref、旧 run 与旧 API 客户端兼容。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        config = load_config()
        metrics = config.metrics.model_copy(
            update={
                "snapshot_dir": str(self.root / "evidence"),
                "self_run_sample_path": str(self.root / "samples.jsonl"),
            }
        )
        self.config = config.model_copy(update={"metrics": metrics})
        self.store = MemoryStore()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_legacy_ref_defaults_without_warnings(self) -> None:
        legacy = {
            "snapshot_id": "SNAP-2026-12-PRELIMINARY-legacy",
            "window": WINDOW,
            "tier": TIER.value,
            "digest": "a" * 64,
            "capture_ms": 184,
            "chain_valid": True,
            "issue_count": 1,
            "event_count": 2,
        }
        ref = MetricSnapshotRef.model_validate(legacy)
        self.assertEqual(ref.write_block_ms, 0)
        self.assertEqual(ref.write_block_budget_ms, 200)
        self.assertFalse(ref.write_block_exceeded)
        self.assertEqual(ref.capture_total_ms, 0)
        self.assertEqual(ref.capture_budget_ms, 200)
        self.assertFalse(ref.capture_slow)
        self.assertEqual(ref.segment_ms, {})
        self.assertEqual(ref.encode_count, 1)

    def test_legacy_run_warnings_default_empty(self) -> None:
        run = RecalcRun.model_validate(
            {
                "recalc_id": "RC-LEGACY",
                "window": WINDOW,
                "tier": TIER.value,
                "trigger": "MANUAL",
                "actor": "ops",
                "status": "SUCCESS",
                "started_at": NOW.isoformat(),
            }
        )
        self.assertEqual(run.warnings, [])

    def test_api_reads_legacy_run_with_empty_warnings(self) -> None:
        run = RecalcRun(
            recalc_id="RC-LEGACY",
            window=WINDOW,
            tier=TIER,
            trigger="MANUAL",
            actor="ops",
            status="SUCCESS",
            started_at=NOW,
            finished_at=NOW,
        )
        self.store.put_recalc(run)
        box = AppContainer(self.config)
        box.store = self.store
        client = TestClient(create_app(self.config, box))
        response = client.get("/api/v1/metrics/recalc/RC-LEGACY")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["warnings"], [])

    def test_normal_capture_has_no_write_block_false_alarm(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            envelope = SnapshotBuilder(store, LocalEvidenceStore(Path(tmp) / "evidence")).capture(WINDOW, TIER)
        self.assertFalse(envelope.ref.write_block_exceeded, "正常抓取不得误报写阻塞")
        self.assertEqual(envelope.ref.encode_count, 1)
        expected = [
            code
            for code, flag in (
                ("WRITE_BLOCK_EXCEEDED", envelope.ref.write_block_exceeded),
                ("CAPTURE_SLOW", envelope.ref.capture_slow),
            )
            if flag
        ]
        self.assertEqual(_warnings_of(envelope.ref), expected)
        self.assertEqual(_warnings_of(envelope.ref), evaluate_capture_health(envelope.metrics, 200))


class _CountingStore:
    """代理 MemoryStore：记录 snapshot_copy 次数与其后对共享容器的访问次数。"""

    COLLECTIONS = frozenset(
        (
            "issues",
            "alerts",
            "verdicts",
            "proofs",
            "patches",
            "gate_results",
            "dispositions",
            "runs",
            "events",
            "reproduction_attempts",
            "patch_attempts",
            "gate_attempts",
            "disposition_history",
        )
    )

    def __init__(self, inner) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "copy_calls", 0)
        object.__setattr__(self, "access_after_copy", 0)
        object.__setattr__(self, "_copied", False)

    def snapshot_copy(self):
        object.__setattr__(self, "copy_calls", self.copy_calls + 1)
        clone = self._inner.snapshot_copy()
        object.__setattr__(self, "_copied", True)
        return clone

    def __getattr__(self, name: str):
        if name in self.COLLECTIONS and self._copied:
            object.__setattr__(self, "access_after_copy", self.access_after_copy + 1)
        return getattr(self._inner, name)


_METRIC_COMPARE_FIELDS = (
    "value",
    "computable",
    "reason_code",
    "numerator",
    "denominator",
    "covered_count",
    "excluded_count",
    "channel_excluded_count",
    "not_applicable_count",
    "snapshot_digest",
    "definition_version",
    "trial",
    "unverified",
)


def _metric_view(store: MemoryStore) -> dict[str, dict]:
    view: dict[str, dict] = {}
    for record in store.metrics_for(WINDOW, TIER):
        data = record.model_dump()
        view[record.metric_id.value] = {name: data[name] for name in _METRIC_COMPARE_FIELDS}
    return view


class NonBlockingWarningTest(unittest.TestCase):
    """NB-01 / RP-04：告警非阻断且不污染指标口径。"""

    def _service(self, store: MemoryStore, root: Path, budget: int) -> RecalcService:
        evidence = LocalEvidenceStore(root / "evidence")
        builder = SnapshotBuilder(
            store, evidence, capture_budget_ms=budget, clock_ns=_StepClock(2_000_000)
        )
        sample_reader = SelfRunSampleReader(root / "samples.jsonl")
        sample_reader.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 7200.0,
                "interruptions": 0,
                "heartbeat_ok": True,
            }
        )
        expected = read_expected_digest(ROOT / "eval" / "eval_set.sha256")
        collector = MainFlowEvidenceCollector(
            sample_reader, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected
        )
        return RecalcService(
            store,
            evidence,
            load_config(),
            builder=builder,
            guard=RecalcGuard(),
            collector=collector,
            clock=lambda: NOW,
        )

    def test_capture_slow_is_visible_but_not_blocking(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            first = self._service(store, root, 200).recalc(
                WINDOW, TIER, RecalcTrigger.MANUAL, "nb01", now=NOW
            )
            self.assertTrue(first.succeeded)
            self.assertEqual(first.warnings, [])
            first_ref = store.get_snapshot(first.snapshot.snapshot_id)
            self.assertFalse(first_ref.capture_slow)
            first_metrics = _metric_view(store)

            second = self._service(store, root, 1).recalc(
                WINDOW, TIER, RecalcTrigger.MANUAL, "nb01", now=NOW
            )
            self.assertTrue(second.succeeded, "告警不得改变复算成功状态")
            self.assertEqual(second.warnings, ["CAPTURE_SLOW"])
            self.assertEqual(second.snapshot.snapshot_id, first.snapshot.snapshot_id, "payload 未变，快照应相同")
            second_ref = store.get_snapshot(second.snapshot.snapshot_id)
            self.assertTrue(second_ref.capture_slow)
            self.assertFalse(second_ref.write_block_exceeded)
            self.assertEqual(store.get_recalc(second.recalc_id).warnings, ["CAPTURE_SLOW"])
            self.assertEqual(_metric_view(store), first_metrics, "告警污染了指标口径")
            self.assertEqual(len(store.metrics_for(WINDOW, TIER)), 9)


class CriticalSectionTest(unittest.TestCase):
    """RP-03 / F-01：snapshot_copy 是唯一临界段，其后不得再访问共享容器。"""

    def test_snapshot_copy_called_once_and_no_later_access(self) -> None:
        inner, _ = build_small_store()
        proxy = _CountingStore(inner)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            envelope = SnapshotBuilder(proxy, LocalEvidenceStore(Path(tmp) / "evidence")).capture(WINDOW, TIER)
        self.assertEqual(proxy.copy_calls, 1, "snapshot_copy 必须且只能调用一次")
        self.assertEqual(proxy.access_after_copy, 0, "snapshot_copy 之后仍在访问共享容器")
        self.assertEqual(envelope.ref.segment_ms["clone"], envelope.ref.write_block_ms)
        self.assertEqual(envelope.ref.write_block_budget_ms, WRITE_BLOCK_BUDGET_MS)


def _warnings_of(ref: MetricSnapshotRef) -> list[str]:
    flags = {"WRITE_BLOCK_EXCEEDED": ref.write_block_exceeded, "CAPTURE_SLOW": ref.capture_slow}
    return [code for code in CAPTURE_WARNINGS if flags.get(code)]


if __name__ == "__main__":
    unittest.main()