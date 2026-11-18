from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from app.api.envelope import ApiError, ErrorCode
from app.realscan.models import ImageResolution, RuntimeFacts
from app.realscan.runtime import CommandResult, RuntimeTransport

ISOLATION_KEYS = (
    "network",
    "source_mount",
    "root_filesystem",
    "timeout_seconds",
    "memory_mb",
    "cpu",
    "user",
    "cap_drop",
    "no_new_privileges",
    "pids_limit",
    "tmpfs",
)

EXPECTED_VALUES = {
    "network": "none",
    "source_mount": "read-only",
    "root_filesystem": "read-only",
}

JUDGEMENT_CLASSES = (
    "network",
    "source_mount",
    "filesystem_writable_surface",
    "timeout_termination",
    "memory_limit",
    "cpu_limit",
    "exec_user",
    "capability_set",
    "no_new_privileges",
    "pids_limit",
)

KEY_TO_CLASS = {
    "network": "network",
    "source_mount": "source_mount",
    "root_filesystem": "filesystem_writable_surface",
    "tmpfs": "filesystem_writable_surface",
    "timeout_seconds": "timeout_termination",
    "memory_mb": "memory_limit",
    "cpu": "cpu_limit",
    "user": "exec_user",
    "cap_drop": "capability_set",
    "no_new_privileges": "no_new_privileges",
    "pids_limit": "pids_limit",
}

DEFAULT_TMPFS_SIZE_MB = {"/tmp": 64, "/workspace": 256}


def sanitize_name(value: str) -> str:
    cleaned = __import__("re").sub(r"[^a-zA-Z0-9_.-]", "-", str(value)).strip("-")
    return cleaned[:120] or "vf-container"


class PolicyInvalidError(ApiError):
    def __init__(self, detail: str):
        super().__init__(ErrorCode.EVAL_INVALID, detail)


@dataclass(frozen=True)
class EscapeCase:
    case_id: str
    goal: str
    expect: str


@dataclass(frozen=True)
class PolicyFile:
    policy_version: str
    isolation: dict[str, object]
    escape_cases: tuple[EscapeCase, ...]
    image: str
    sha256: str
    path: Path

    @classmethod
    def load(cls, path: Path) -> "PolicyFile":
        import hashlib

        candidate = Path(path)
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyInvalidError(f"policy file is not readable: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise PolicyInvalidError("policy file must contain a mapping")
        isolation = payload.get("isolation")
        if not isinstance(isolation, dict):
            raise PolicyInvalidError("policy file requires an isolation mapping")
        missing = [key for key in ISOLATION_KEYS if key not in isolation]
        if missing:
            raise PolicyInvalidError("policy isolation is missing keys: " + ",".join(missing))
        for key, expected in EXPECTED_VALUES.items():
            if isolation.get(key) != expected:
                raise PolicyInvalidError(f"policy isolation.{key} must be {expected!r}")
        cap_drop = isolation.get("cap_drop")
        if not isinstance(cap_drop, list) or [str(item).upper() for item in cap_drop] != ["ALL"]:
            raise PolicyInvalidError("policy isolation.cap_drop must be ['ALL']")
        if isolation.get("no_new_privileges") is not True:
            raise PolicyInvalidError("policy isolation.no_new_privileges must be true")
        cases = payload.get("escape_cases") or []
        if not isinstance(cases, list) or not cases:
            raise PolicyInvalidError("policy file requires escape_cases")
        escape_cases = tuple(
            EscapeCase(
                case_id=str(item.get("id", "")),
                goal=str(item.get("goal", "")),
                expect=str(item.get("expect", "")),
            )
            for item in cases
        )
        if any(not case.case_id for case in escape_cases):
            raise PolicyInvalidError("each escape case requires an id")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return cls(
            policy_version=str(payload.get("policy_version", "")),
            isolation=dict(isolation),
            escape_cases=escape_cases,
            image=str(payload.get("image", "")),
            sha256=digest,
            path=candidate,
        )


@dataclass(frozen=True)
class RunSpec:
    argv: tuple[str, ...]
    container_name: str
    view_dir: str
    workdir: str
    stdin_mode: bool


class RunSpecBuilder:
    def __init__(self, policy: PolicyFile, container_name: str, path_mapper: Callable[[Path], str] | None = None):
        if not container_name:
            raise ValueError("container_name must not be empty")
        self.policy = policy
        self.container_name = container_name
        self.path_mapper = path_mapper or (lambda item: str(Path(item).resolve()))

    def build(
        self,
        view_dir: Path,
        *,
        stdin_mode: bool,
        workdir: str = "/src",
        mount_target: str | None = None,
    ) -> RunSpec:
        isolation = self.policy.isolation
        tmpfs = isolation.get("tmpfs") or []
        if not isinstance(tmpfs, list) or not tmpfs:
            raise PolicyInvalidError("policy isolation.tmpfs must be a non-empty list")
        argv: list[str] = [
            "docker",
            "create",
            "--name",
            self.container_name,
            f"--network={isolation['network']}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--user={isolation['user']}",
            f"--memory={isolation['memory_mb']}m",
            f"--memory-swap={isolation['memory_mb']}m",
            f"--cpus={isolation['cpu']}",
            f"--pids-limit={isolation['pids_limit']}",
        ]
        for mount in tmpfs:
            size = DEFAULT_TMPFS_SIZE_MB.get(str(mount), 64)
            argv.append(f"--tmpfs={mount}:rw,noexec,nosuid,size={size}m,mode=1777")
        target_mount = mount_target or workdir
        argv.extend([f"--volume={self.path_mapper(view_dir)}:{target_mount}:ro", f"--workdir={workdir}"])
        argv.extend(["--entrypoint", "python", self.policy.image])
        argv.append("-" if stdin_mode else "-c")
        return RunSpec(
            argv=tuple(argv),
            container_name=self.container_name,
            view_dir=str(Path(view_dir).resolve()),
            workdir=workdir,
            stdin_mode=stdin_mode,
        )

    def build_run(self, view_dir: Path, command: str, workdir: str = "/src", mount_target: str | None = None) -> RunSpec:
        spec = self.build(view_dir, stdin_mode=False, workdir=workdir, mount_target=mount_target)
        argv = list(spec.argv)
        argv[1] = "run"
        argv.insert(2, "--rm")
        argv.append(command)
        return RunSpec(
            argv=tuple(argv),
            container_name=self.container_name,
            view_dir=spec.view_dir,
            workdir=workdir,
            stdin_mode=False,
        )


def parse_image_inspect(stdout: str) -> tuple[str, list[str], int]:
    parts = stdout.strip().split("|")
    image_id = parts[0].strip()
    digests: list[str] = []
    size = 0
    if len(parts) > 1:
        raw = parts[1].strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    digests = [str(item) for item in parsed]
            except json.JSONDecodeError:
                digests = []
    if len(parts) > 2 and parts[2].strip().isdigit():
        size = int(parts[2].strip())
    return image_id, digests, size


class ImageResolver:
    def __init__(self, transport: RuntimeTransport, candidates: Sequence[str]):
        cleaned = [str(item) for item in candidates if str(item).strip()]
        if not cleaned:
            raise ValueError("image candidates must not be empty")
        self.transport = transport
        self.candidates = tuple(cleaned)

    def inspect(self, image: str) -> ImageResolution:
        result = self.transport.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}|{{json .RepoDigests}}|{{.Size}}", image],
            3.0,
        )
        if not result.ok:
            return ImageResolution(policy_image=image, source="MISSING")
        image_id, digests, _size = parse_image_inspect(result.stdout)
        if not image_id:
            return ImageResolution(policy_image=image, source="MISSING")
        return ImageResolution(
            policy_image=image,
            resolved_image=image,
            image_id=image_id,
            repo_digests=digests,
            local_build=not digests,
            alias_used=False,
            source="POLICY_IMAGE",
        )

    def resolve(self, policy_image: str) -> ImageResolution:
        primary = self.inspect(policy_image)
        if primary.image_id:
            return primary
        for candidate in self.candidates:
            if candidate == policy_image:
                continue
            alias = self.inspect(candidate)
            if alias.image_id:
                return alias.model_copy(
                    update={
                        "policy_image": policy_image,
                        "alias_used": True,
                        "source": "LOCAL_ALIAS",
                    }
                )
        return ImageResolution(policy_image=policy_image, source="MISSING")


def runtime_facts_from_info(info: CommandResult | None, user: str, docker_version: str) -> RuntimeFacts:
    driver = "unknown"
    cgroup = "unknown"
    if info is not None and info.ok and info.stdout.strip():
        parts = info.stdout.strip().split("|")
        if parts and parts[0].strip():
            driver = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            cgroup = parts[1].strip()
    return RuntimeFacts(
        network_mode="NONE_LOOPBACK",
        read_only_rootfs=True,
        cap_drop=["ALL"],
        security_opts=["no-new-privileges"],
        user=user or "unknown",
        memory_bytes=0,
        nano_cpus=0,
        pids_limit=0,
        tmpfs_mounts=[],
        docker_version=docker_version or "unknown",
        runtime_driver=driver,
        cgroup_version=cgroup,
    )