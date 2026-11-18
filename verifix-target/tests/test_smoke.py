from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import init_db
from app.main import create_app


class TargetSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "target.db"
        init_db.create(self.db)
        self.app = create_app(str(self.db))
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_user_endpoint_returns_rows(self) -> None:
        response = self.client.get("/user?uid=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()), 1)

    def test_search_endpoint(self) -> None:
        response = self.client.get("/search?q=ali")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.get_json()), 1)

    def test_order_and_profile(self) -> None:
        self.assertEqual(self.client.get("/order?order_id=1").status_code, 200)
        self.assertEqual(self.client.get("/profile?id=1").status_code, 200)

    def test_login(self) -> None:
        response = self.client.post("/login", data={"username": "alice", "password": "alice-pass"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["matched"], 1)


if __name__ == "__main__":
    unittest.main()