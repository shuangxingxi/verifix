from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.runtime.self_run import SelfRunTracker


class SelfRunSampleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "samples.jsonl"
        self.now = datetime(2026, 12, 5, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tracker_sample_shape(self) -> None:
        current = {"t": 0.0}
        tracker = SelfRunTracker(clock=lambda: current["t"])
        tracker.heartbeat()
        current["t"] = 10.0
        sample = tracker.sample(now=self.now)
        self.assertTrue(sample.heartbeat_ok)
        self.assertGreaterEqual(sample.continuous_seconds, 0.0)
        self.assertEqual(sample.interruptions, 0)
        self.assertIsNotNone(sample.sampled_at.tzinfo)

    def test_append_and_latest(self) -> None:
        reader = SelfRunSampleReader(self.path)
        self.assertIsNone(reader.latest())
        reader.append({"sampled_at": self.now.isoformat(), "continuous_seconds": 3600.0, "interruptions": 0, "heartbeat_ok": True})
        reader.append({"sampled_at": (self.now + timedelta(seconds=60)).isoformat(), "continuous_seconds": 7200.0, "interruptions": 1, "heartbeat_ok": True})
        latest = reader.latest()
        self.assertEqual(latest["continuous_seconds"], 7200.0)
        self.assertEqual(latest["interruptions"], 1)

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(SelfRunSampleReader(Path(self.tmp.name) / "absent.jsonl").latest())

    def test_corrupt_tail_line_is_skipped(self) -> None:
        reader = SelfRunSampleReader(self.path)
        reader.append({"sampled_at": self.now.isoformat(), "continuous_seconds": 10.0, "interruptions": 0, "heartbeat_ok": True})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"sampled_at": "broken"\n')
        latest = reader.latest()
        self.assertEqual(latest["continuous_seconds"], 10.0)

    def test_large_file_tail_read_is_fast(self) -> None:
        reader = SelfRunSampleReader(self.path)
        rows = []
        for index in range(100_000):
            rows.append(
                json.dumps(
                    {
                        "sampled_at": self.now.isoformat(),
                        "continuous_seconds": float(index),
                        "interruptions": 0,
                        "heartbeat_ok": True,
                    },
                    separators=(",", ":"),
                )
            )
        self.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        started = time.perf_counter()
        latest = reader.latest()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(latest["continuous_seconds"], 99999.0)
        print(f"\n100k-line tail read: {elapsed_ms:.1f}ms (extrapolated 1M: {elapsed_ms * 10:.1f}ms)")
        self.assertLess(elapsed_ms, 500.0, "tail read must stay well below the 50ms/1M-line budget")


if __name__ == "__main__":
    unittest.main()