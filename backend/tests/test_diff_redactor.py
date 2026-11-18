from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.diff import DiffAnalyzer
from app.tools.redactor import MASK, SecretRedactor

SAMPLE_DIFF = """diff --git a/app/user.py b/app/user.py
index 1111111..2222222 100644
--- a/app/user.py
+++ b/app/user.py
@@ -40,7 +40,9 @@ def get_user(uid):
-    sql = "SELECT * FROM users WHERE id = '%s'" % uid
-    return db.execute(sql)
+    sql = "SELECT * FROM users WHERE id = %s"
+    if not uid:
+        raise ValueError("uid required")
+    return db.execute(sql, (uid,))
 
diff --git a/requirements.txt b/requirements.txt
index 3333333..4444444 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,2 +1,2 @@
 flask==2.0.1
-requests==2.25.1
+requests==2.32.3
"""


class DiffAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = DiffAnalyzer()

    def test_counts_match_git_stat(self) -> None:
        analysis = self.analyzer.parse(SAMPLE_DIFF)
        self.assertEqual(analysis.files_changed, 2)
        self.assertEqual(analysis.lines_added, 5)
        self.assertEqual(analysis.lines_removed, 3)
        self.assertEqual(analysis.lines_changed, 8)

    def test_counts_match_real_git_diff_stat(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "dev"], cwd=repo, check=True)
            target = repo / "sample.py"
            target.write_text("a = 1\nb = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
            target.write_text("a = 1\nb = 3\nc = 4\n", encoding="utf-8")
            diff_text = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, check=True).stdout
            stat = subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True, check=True).stdout
            analysis = self.analyzer.parse(diff_text)
            self.assertIn("1 file changed", stat)
            self.assertEqual(analysis.files_changed, 1)
            self.assertEqual(analysis.lines_added + analysis.lines_removed, 3)

    def test_locations_are_recorded(self) -> None:
        analysis = self.analyzer.parse(SAMPLE_DIFF)
        added = analysis.added[0]
        self.assertEqual(added.file, "app/user.py")
        self.assertEqual(added.line_no, 40)

    def test_backdoor_probes(self) -> None:
        analysis = self.analyzer.parse(SAMPLE_DIFF)
        self.assertTrue(self.analyzer.adds_conditional(analysis))
        diff_io = """--- a/app/user.py
+++ b/app/user.py
@@ -1 +1 @@
-x = 1
+import requests
+requests.get("https://example.com")
"""
        self.assertTrue(self.analyzer.adds_io_or_network(self.analyzer.parse(diff_io)))
        diff_cmp = """--- a/app/user.py
+++ b/app/user.py
@@ -1 +1 @@
-x = 1
+if token == "dbg-9f3a2c":
+    pass
"""
        self.assertTrue(self.analyzer.adds_string_const_cmp(self.analyzer.parse(diff_cmp)))
        diff_auth = """--- a/app/user.py
+++ b/app/user.py
@@ -1 +1 @@
-AUTH_MODE = "user"
+AUTH_MODE = "admin"
"""
        self.assertTrue(self.analyzer.touches_auth_constants(self.analyzer.parse(diff_auth)))

    def test_clean_diff_passes_probes(self) -> None:
        clean = """--- a/app/user.py
+++ b/app/user.py
@@ -1 +1 @@
-sql = "SELECT * FROM users WHERE id = '%s'" % uid
+sql = "SELECT * FROM users WHERE id = %s"
"""
        analysis = self.analyzer.parse(clean)
        self.assertFalse(self.analyzer.adds_io_or_network(analysis))
        self.assertFalse(self.analyzer.adds_string_const_cmp(analysis))


class SecretRedactorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.redactor = SecretRedactor()

    def test_four_export_channels_are_scrubbed(self) -> None:
        secret_url = "postgres://user:secret-password@db.example.com/app"
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        payload = f"DATABASE_URL={secret_url} token={token} AKIAABCDEFGHIJKLMNOP"
        channels = {
            "log": f"connecting {payload}",
            "pr_body": f"evidence {payload}",
            "dashboard": f"detail {payload}",
            "report": f"summary {payload}",
        }
        sanitized, combined = self.redactor.sanitize_exports(channels)
        self.assertTrue(combined.redacted)
        for channel, text in sanitized.items():
            self.assertNotIn("secret-password", text, channel)
            self.assertNotIn("AKIAABCDEFGHIJKLMNOP", text, channel)
            self.assertNotIn("dozjgNryP4J3jVmNHl0w5N", text, channel)
            self.assertIn(MASK, text, channel)
        self.assertIn("credentialed_url", combined.rules())
        self.assertIn("aws_access_key", combined.rules())

    def test_private_key_block_masked(self) -> None:
        block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
        result = self.redactor.redact(block)
        self.assertTrue(result.redacted)
        self.assertNotIn("MIIEowIBAAKCAQEA", result.text)

    def test_clean_text_untouched(self) -> None:
        text = "def get_user(uid):\n    return db.execute('SELECT 1')\n"
        result = self.redactor.redact(text)
        self.assertFalse(result.redacted)
        self.assertEqual(result.text, text)

    def test_redaction_event_payload(self) -> None:
        result = self.redactor.redact("password=hunter2hunter2")
        payload = self.redactor.redaction_event_payload(result, "run-1")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertGreaterEqual(payload["hit_count"], 1)
        self.assertNotIn("hunter2hunter2", str(payload))


if __name__ == "__main__":
    unittest.main()