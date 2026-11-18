from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.adapters.repo import ForbiddenBranchError, LocalRepoAdapter
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DefectClass, SourceKind
from app.main import create_app


def _app(config):
    return create_app(config, AppContainer(config))


def _routes(app) -> set[str]:
    return {route.path for route in app.routes}


class FrozenDecisionsTest(unittest.TestCase):
    def test_main_auto_merge_path_is_unreachable(self) -> None:
        adapter = LocalRepoAdapter()
        for action in (
            lambda: adapter.create_branch("repo", "main", "sha"),
            lambda: adapter.commit_files("repo", "main", {"a.py": "x"}, "m"),
            lambda: adapter.merge_to_release_auto("repo", "main"),
            lambda: adapter.open_pull_request("repo", "main", "release/auto", "t", "b"),
        ):
            with self.assertRaises(ForbiddenBranchError):
                action()
        adapter.create_branch("repo", "verifix/ISS-1", "sha")
        reference = adapter.open_pull_request("repo", "verifix/ISS-1", "main", "人工评审", "body")
        self.assertEqual(reference.target, "main")
        merged = adapter.merge_to_release_auto("repo", "verifix/ISS-1")
        self.assertIn(merged.branch if hasattr(merged, "branch") else "release/auto", {"release/auto"})

    def test_t1_brand_change_keeps_api_surface(self) -> None:
        base = load_config()
        baseline_routes = _routes(_app(base))
        renamed = base.model_copy(update={"product": base.product.model_copy(update={"brand": "Renamed"})})
        client = TestClient(_app(renamed))
        meta = client.get("/api/v1/meta")
        self.assertEqual(meta.status_code, 200)
        data = meta.json()["data"]
        self.assertEqual(data["brand"], "Renamed")
        self.assertEqual(data["branch_namespace"], base.branch.namespace)
        self.assertEqual(data["release_auto_branch"], base.release.auto_branch)
        self.assertEqual(_routes(_app(renamed)), baseline_routes)

    def test_t5_provider_switch_keeps_api_surface(self) -> None:
        base = load_config()
        baseline_routes = _routes(_app(base))
        switched = base.model_copy(update={"model": base.model.model_copy(update={"provider": "plugin-alt"})})
        client = TestClient(_app(switched))
        data = client.get("/api/v1/meta").json()["data"]
        self.assertEqual(data["model_provider"], "plugin-alt")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(_routes(_app(switched)), baseline_routes)

    def test_mvp_and_data_source_decisions(self) -> None:
        self.assertEqual({item.value for item in DefectClass}, {"C01", "C02", "C03", "C05"})
        sources = {item.value for item in SourceKind}
        self.assertIn("OSV", sources)
        self.assertIn("CNVD", sources)
        config = load_config()
        self.assertEqual(config.release.auto_branch, "release/auto")
        self.assertEqual(config.branch.namespace, "verifix/")
        self.assertTrue((Path(__file__).resolve().parents[2] / "verifix-target" / "ground_truth.json").is_file())
        self.assertTrue((Path(__file__).resolve().parents[2] / "deliverables" / "CodeArts方案.md").is_file())

    def test_frozen_defaults_are_registered(self) -> None:
        config = load_config()
        self.assertEqual(config.patch.max_lines, 30)
        self.assertEqual(config.patch.max_files, 3)
        self.assertEqual(config.patch.strength_l0_l1_min, 0.60)
        self.assertEqual(config.branch.namespace, "verifix/")
        self.assertEqual(config.release.auto_branch, "release/auto")


if __name__ == "__main__":
    unittest.main()