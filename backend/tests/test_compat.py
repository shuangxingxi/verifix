from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.check import FIELD_MAP, CheckAdapter
from app.domain.enums import EventType
from app.domain.models import SCHEMA_VERSION, Event
from app.eval.models import EvalSetManifest
from app.eval.service import TOTAL_MIN
from app.repo.memory import MemoryStore


class FieldRenameCompatTest(unittest.TestCase):
    def test_field_rename_only_touches_mapping_table(self) -> None:
        mapping = dict(FIELD_MAP)
        renamed = {
            "file_path": "source_file",
            "rule_id": "rule_name",
            "line": "line_no",
            "severity": "level",
            "snippet": "code_excerpt",
            "alert_ref": "alert_uid",
            "component": "package",
            "component_version": "package_version",
        }
        for logical, physical in renamed.items():
            mapping[logical] = physical
        record = {
            "alert_uid": "check:renamed:1",
            "rule_name": "py/sql-injection",
            "source_file": "app/main.py",
            "line_no": 31,
            "level": "high",
            "code_excerpt": "conn.execute(...)",
            "package": None,
            "package_version": None,
        }
        alert = CheckAdapter(client=object(), field_map=mapping).map_alert(record)
        self.assertEqual(alert.alert_ref, "check:renamed:1")
        self.assertEqual(alert.rule_id, "py/sql-injection")
        self.assertEqual(alert.file_path, "app/main.py")
        self.assertEqual(alert.line, 31)
        self.assertEqual(alert.severity.value, "HIGH")

    def test_default_mapping_is_unchanged_after_custom_adapter(self) -> None:
        self.assertEqual(FIELD_MAP["file_path"], "filePath")
        self.assertEqual(FIELD_MAP["rule_id"], "ruleId")
        record = {
            FIELD_MAP["alert_ref"]: "check:default:1",
            FIELD_MAP["rule_id"]: "py/command-injection",
            FIELD_MAP["file_path"]: "app/main.py",
            FIELD_MAP["line"]: 81,
            FIELD_MAP["severity"]: "high",
            FIELD_MAP["snippet"]: "os.popen(...)",
        }
        alert = CheckAdapter(client=object()).map_alert(record)
        self.assertEqual(alert.file_path, "app/main.py")
        self.assertEqual(alert.line, 81)


class EvalScaleCompatTest(unittest.TestCase):
    def test_manifest_structure_is_scale_independent(self) -> None:
        base = {
            "set_version": "1.0.0",
            "cases_digest": "a" * 64,
            "expected_digest": "b" * 64,
            "binding_digest": "c" * 64,
            "actor": "compat",
        }
        fifty = EvalSetManifest(
            case_count=50,
            category_distribution={"POSITIVE": 20, "NEGATIVE": 15, "BOUNDARY": 10, "ADVERSARIAL": 5},
            **base,
        )
        hundred = EvalSetManifest(
            case_count=100,
            category_distribution={"POSITIVE": 40, "NEGATIVE": 30, "BOUNDARY": 20, "ADVERSARIAL": 10},
            **base,
        )
        self.assertEqual(set(fifty.model_fields), set(hundred.model_fields))
        self.assertEqual(fifty.set_version, hundred.set_version)
        self.assertEqual(hundred.case_count, 100)
        self.assertEqual(TOTAL_MIN, 50)
        self.assertGreaterEqual(hundred.case_count, TOTAL_MIN)


class SchemaVersionCompatTest(unittest.TestCase):
    def test_legacy_event_schema_is_readable_and_chain_valid(self) -> None:
        store = MemoryStore()
        legacy = Event(
            event_id="EVT-legacy-1",
            run_id="run-legacy",
            seq=1,
            event_type=EventType.INGEST,
            actor="legacy-writer",
            schema_version=0,
        )
        store.append(legacy)
        events = store.list_for_run("run-legacy")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].schema_version, 0)
        self.assertEqual(events[0].actor, "legacy-writer")
        self.assertTrue(store.verify_chain("run-legacy"))

    def test_new_event_uses_current_schema_version(self) -> None:
        store = MemoryStore()
        store.append(
            Event(
                event_id="EVT-old-1",
                run_id="run-mixed",
                seq=1,
                event_type=EventType.INGEST,
                actor="legacy",
                schema_version=0,
            )
        )
        store.append(
            Event(
                event_id="EVT-new-1",
                run_id="run-mixed",
                seq=2,
                event_type=EventType.VERDICT,
                actor="current",
            )
        )
        events = store.list_for_run("run-mixed")
        self.assertEqual([item.schema_version for item in events], [0, SCHEMA_VERSION])
        self.assertTrue(store.verify_chain("run-mixed"))
        self.assertGreaterEqual(SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()