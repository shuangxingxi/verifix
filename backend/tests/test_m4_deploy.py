from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
from fastapi.testclient import TestClient

from app.config import load_config
from app.container import AppContainer
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


class DeployTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))

    def test_readyz_reports_five_dependencies(self) -> None:
        response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn(data["status"], {"ok", "degraded"})
        self.assertEqual(len(data["dependencies"]), 5)
        names = {item["name"] for item in data["dependencies"]}
        self.assertEqual(names, {"RDS", "Redis", "OBS", "MaaS", "CodeArts"})

    def test_console_is_mounted_when_dist_exists(self) -> None:
        dist = ROOT / "frontend" / "dist"
        if not dist.is_dir():
            self.skipTest("frontend dist not built")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<div id=\"app\">", response.text)

    def test_compose_uses_8443_and_has_four_services(self) -> None:
        compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
        services = compose["services"]
        self.assertEqual(set(services), {"api", "mcp", "sandbox", "gateway"})
        self.assertEqual(services["gateway"]["ports"], ["8443:8443"])
        self.assertNotIn("80:80", str(compose))
        self.assertNotIn("443:443", str(compose))

    def test_nginx_listens_8443_only(self) -> None:
        config = (ROOT / "deploy" / "nginx" / "verifix.conf").read_text(encoding="utf-8")
        self.assertIn("listen 8443 ssl", config)
        self.assertNotIn("listen 80", config)
        self.assertNotIn("listen 443", config)
        self.assertIn("proxy_buffering off", config)

    def test_cce_manifests_cover_required_objects(self) -> None:
        kinds = set()
        for path in sorted((ROOT / "deploy" / "cce").glob("*.yaml")):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            kinds.add(document["kind"])
            if document["kind"] == "Deployment" and document["metadata"]["name"] == "verifix-api":
                container = document["spec"]["template"]["spec"]["containers"][0]
                probes = container.get("readinessProbe", {}) | container.get("livenessProbe", {})
                self.assertTrue(probes)
        self.assertTrue({"ConfigMap", "Secret", "Deployment", "Service", "Ingress", "HorizontalPodAutoscaler"} <= kinds)

    def test_ingress_exposes_8443(self) -> None:
        ingress = yaml.safe_load((ROOT / "deploy" / "cce" / "06-ingress.yaml").read_text(encoding="utf-8"))
        self.assertEqual(ingress["metadata"]["annotations"]["kubernetes.io/elb.port"], "8443")
        self.assertIn("tls", ingress["spec"])


if __name__ == "__main__":
    unittest.main()