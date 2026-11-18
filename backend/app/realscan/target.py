from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.realscan.models import TargetView

INCLUDED_PATHS = ("app", "init_db.py", "requirements.txt")
EXCLUDED_PATHS = ("ground_truth.json", "tests", "tools", "__pycache__", ".git", "target.db")

P4_FIXTURE_MAIN = (
    "from flask import Flask, request\n"
    "\n"
    "app = Flask(__name__)\n"
    "\n"
    "\n"
    "@app.get(\"/user\")\n"
    "def user():\n"
    "    uid = request.args.get(\"uid\", \"1\")\n"
    "    return uid\n"
)

P4_FIXTURE_GIT_CONFIG = "[core]\n\trepositoryformatversion = 0\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_index(root: Path) -> tuple[dict[str, str], str]:
    digests: dict[str, str] = {}
    for item in sorted(root.rglob("*")):
        if item.is_file():
            digests[item.relative_to(root).as_posix()] = _sha256(item)
    joined = "\n".join(f"{name}:{digest}" for name, digest in sorted(digests.items()))
    return digests, hashlib.sha256(joined.encode("utf-8")).hexdigest()


class TargetViewBuilder:
    def build(self, source_root: Path, work_root: Path) -> TargetView:
        source = Path(source_root)
        if not source.is_dir():
            raise FileNotFoundError(f"target source missing: {source}")
        view_root = Path(work_root) / "view"
        if view_root.exists():
            shutil.rmtree(view_root)
        view_root.mkdir(parents=True)
        included: list[str] = []
        for name in INCLUDED_PATHS:
            candidate = source / name
            if not candidate.exists():
                continue
            if candidate.is_dir():
                for item in sorted(candidate.rglob("*")):
                    if not item.is_file() or _excluded(item, source):
                        continue
                    relative = item.relative_to(source)
                    target = view_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                    included.append(relative.as_posix())
            else:
                shutil.copy2(candidate, view_root / name)
                included.append(name)
        digests, view_digest = _digest_index(view_root)
        return TargetView(
            view_id=f"view-{view_digest[:8]}",
            source_root=str(source.resolve()),
            view_root=str(view_root.resolve()),
            included_paths=sorted(included),
            excluded_paths=list(EXCLUDED_PATHS),
            file_digests=digests,
            view_digest=view_digest,
            truth_present=(view_root / "ground_truth.json").exists(),
        )

    def build_p4_fixture(self, work_root: Path) -> TargetView:
        fixture = Path(work_root) / "fixtures" / "p4-01"
        if fixture.exists():
            shutil.rmtree(fixture)
        (fixture / "app").mkdir(parents=True)
        (fixture / ".git").mkdir()
        (fixture / "app" / "main.py").write_text(P4_FIXTURE_MAIN, encoding="utf-8")
        (fixture / ".git" / "config").write_text(P4_FIXTURE_GIT_CONFIG, encoding="utf-8")
        view_root = fixture / "view"
        (view_root / "app").mkdir(parents=True)
        shutil.copy2(fixture / "app" / "main.py", view_root / "app" / "main.py")
        digests, view_digest = _digest_index(view_root)
        return TargetView(
            view_id=f"p4-{view_digest[:8]}",
            source_root=str(fixture.resolve()),
            view_root=str(view_root.resolve()),
            included_paths=["app/main.py"],
            excluded_paths=[".git", "ground_truth.json", "tests", "tools", "__pycache__", "target.db"],
            file_digests=digests,
            view_digest=view_digest,
            truth_present=False,
        )


def _excluded(item: Path, source_root: Path) -> bool:
    parts = set(item.relative_to(source_root).parts)
    return bool(parts.intersection(EXCLUDED_PATHS))

LAUNCH_FAILURE_REASONS = ("MISSING_DEPENDENCY", "PORT_UNAVAILABLE", "DB_NOT_WRITABLE", "HEALTH_TIMEOUT", "IMAGE_UNAVAILABLE")


class TargetLaunchError(RuntimeError):
    def __init__(self, reason: str, detail: str = ""):
        if reason not in LAUNCH_FAILURE_REASONS:
            raise ValueError(f"unsupported launch failure reason: {reason}")
        self.reason = reason
        self.detail = detail
        super().__init__(f"target launch failed: {reason} {detail}".strip())


@dataclass
class TargetRuntime:
    container_name: str
    listen_port: int
    port_source: str
    health_ok: bool
    health_elapsed_ms: int
    db_path: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    detections: list[dict[str, object]]
    dynamic_checks: list[dict[str, object]]
    truth_reads: int


class TargetLauncher:
    def __init__(
        self,
        transport,
        view: TargetView,
        image,
        policy: PolicyFile,
        bundle_builder=None,
        path_mapper=None,
    ) -> None:
        from app.realscan.worker import build_worker_bundle

        self.transport = transport
        self.view = view
        self.image = image
        self.policy = policy
        self.bundle_builder = bundle_builder or build_worker_bundle
        self.path_mapper = path_mapper

    def prepare(self):
        if not self.image.image_id:
            raise TargetLaunchError("IMAGE_UNAVAILABLE", self.image.policy_image)
        return self.image

    def launch(self, scan_id: str, payload: dict[str, object], timeout_seconds: float = 180.0) -> TargetRuntime:
        from app.realscan.policy import RunSpecBuilder, sanitize_name
        from app.realscan.worker import parse_events

        self.prepare()
        bundle = self.bundle_builder(payload)
        name = sanitize_name(f"vf-scan-{scan_id}")
        from dataclasses import replace

        effective = replace(self.policy, image=self.image.resolved_image or self.image.policy_image)
        spec = RunSpecBuilder(effective, name, self.path_mapper).build(
            Path(self.view.view_root), stdin_mode=True, workdir="/src"
        )
        argv = list(spec.argv)
        argv[1] = "run"
        argv.insert(2, "-i")
        result = self.transport.run(argv, timeout_seconds, stdin_text=bundle)
        events = parse_events(result.stdout)
        ready = next((event for event in events if event.get("event") == "target_ready"), None)
        if ready is None or not ready.get("ok"):
            reason = str((ready or {}).get("reason") or ("HEALTH_TIMEOUT" if result.timed_out else "HEALTH_TIMEOUT"))
            if result.timed_out:
                reason = "HEALTH_TIMEOUT"
            raise TargetLaunchError(reason if reason in LAUNCH_FAILURE_REASONS else "HEALTH_TIMEOUT", result.stderr[:200])
        summary = next((event for event in events if event.get("event") == "summary"), {})
        return TargetRuntime(
            container_name=name,
            listen_port=int(ready.get("port", 0)),
            port_source=str(ready.get("port_source", "DYNAMIC")),
            health_ok=bool(ready.get("ok")),
            health_elapsed_ms=int(ready.get("health_elapsed_ms", 0)),
            db_path=str(ready.get("db_path", "/tmp/target.db")),
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            detections=[event for event in events if event.get("event") == "detection"],
            dynamic_checks=[event for event in events if event.get("event") == "dynamic"],
            truth_reads=int(summary.get("truth_reads", 0)),
        )