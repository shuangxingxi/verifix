from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".evidence" / "git-baseline"
DEFAULT_OVERRIDE = EVIDENCE / "override-paths.txt"
DEFAULT_SNAPSHOT = ROOT / ".merkle-snapshot.json"

EXIT_OK = 0
EXIT_MANIFEST_UNREADABLE = 3
EXIT_PRECONDITION_FAILED = 4
EXIT_SNAPSHOT_UNREADABLE = 5
EXIT_SENSITIVE_HIT = 6
EXIT_SIZE_EXCEEDED = 7
EXIT_INIT_INCOMPLETE = 8
EXIT_GIT_UNAVAILABLE = 9

L2_DIRS = ("frontend/node_modules", "edgeprofile", "edgeprofile2", "edgeprofile3")
L2_DEPTH = 3

LIMIT_FILES = 1500
LIMIT_BYTES = 40 * 1024 * 1024
LIMIT_FILE_BYTES = 5 * 1024 * 1024

SEGMENT_REASONS = {
    1: "依赖缓存",
    2: "用户目录",
    3: "运行产物",
    4: "凭据证书",
    5: "答案",
    6: "临时调试",
}

STEPS = (
    ("[step-1/requirement]", "需求理解"),
    ("[step-2/codegen]", "代码生成"),
    ("[step-3/build]", "项目构建"),
    ("[step-4/bootstrap]", "问题修复"),
    ("[step-5/release]", "部署上线"),
)

W_HIT = re.compile(r"留痕已通过|五步留痕验收通过|已 Git 化，留痕通过")
W_FULL = re.compile(r"内容完全一致|内容级一致")
W_REAL_GIT = re.compile(r"已验证真实仓库\s*`?\.git`?")

ADDED_WHITELIST = (".gitignore", ".gitattributes", ".evidence/git-baseline/", "docs/devlog/vcs-baseline.md")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def posix(path: Path | str) -> str:
    return str(path).replace(os.sep, "/").replace("\\", "/")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def classify(rel: str) -> str:
    parts = rel.split("/")
    name = parts[-1]
    if rel == "eval/.gitignore":
        return "source"
    if rel.startswith("eval/"):
        return "answer"
    if rel == "verifix-target/ground_truth.json":
        return "answer"
    if rel == ".evidence/redteam-baseline/gt.txt":
        return "answer"
    if rel.startswith("deploy/certs/"):
        return "secret"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "secret"
    if name.endswith((".pem", ".key", ".pfx", ".p12")):
        return "secret"
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo", ".pyd")):
        return "derived"
    if rel.startswith("frontend/node_modules/"):
        return "derived"
    if parts[0] == "frontend" and parts[:2] == ["frontend", "dist"]:
        return "derived"
    if parts[0].startswith("edgeprofile"):
        return "derived"
    if ".work" in parts:
        return "derived"
    if rel in ("verifix-target/target.db", "verifix-target/backup.tgz"):
        return "derived"
    if rel.startswith(".codeartsdoer/.codebase/") or rel.startswith(".codeartsdoer/temp/"):
        return "derived"
    if rel in ("dom.txt", "err.txt") or re.fullmatch(r"\.patch_fix[^/]*\.py", rel):
        return "derived"
    if rel.startswith(".codeartsdoer/specs/"):
        return "spec"
    if rel.startswith("docs/devlog/"):
        return "history"
    if rel.startswith("docs/") or rel in ("README.md", "NOTES.md"):
        return "docs"
    if rel.startswith(".evidence/") or rel == ".merkle-snapshot.json":
        return "evidence"
    return "source"


class Rule:
    __slots__ = ("base", "depth", "regex", "dir_only", "negated", "has_slash", "pattern", "reason", "order")

    def __init__(self, base: str, depth: int, pattern: str, dir_only: bool, negated: bool, reason: str, order: int):
        self.base = base
        self.depth = depth
        self.pattern = pattern
        self.dir_only = dir_only
        self.negated = negated
        self.reason = reason
        self.order = order
        self.has_slash = "/" in pattern.strip("/")
        self.regex = re.compile(_translate(pattern))

    def applies(self, rel: str, is_dir: bool = False) -> str | None:
        if self.base:
            prefix = self.base + "/"
            if not rel.startswith(prefix):
                return None
            sub = rel[len(prefix):]
        else:
            sub = rel
        if not sub:
            return None
        segments = sub.split("/")
        if self.has_slash:
            targets = ["/".join(segments[: i + 1]) for i in range(len(segments))]
        else:
            targets = list(segments)
        if self.dir_only and not is_dir:
            targets = targets[:-1]
        for target in targets:
            if self.regex.fullmatch(target):
                return target
        return None


def _translate(pattern: str) -> str:
    body = pattern[1:] if pattern.startswith("/") else pattern
    if body.endswith("/"):
        body = body[:-1]
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "*":
            if body.startswith("**", index):
                index += 2
                if body.startswith("/", index):
                    out.append("(?:.*/)?")
                    index += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
            index += 1
            continue
        if char == "?":
            out.append("[^/]")
            index += 1
            continue
        if char == "[":
            end = body.find("]", index)
            if end != -1:
                out.append(body[index:end + 1])
                index = end + 1
                continue
        out.append(re.escape(char))
        index += 1
    return "".join(out)


def parse_ignore(path: Path, base: str) -> list[Rule]:
    rules: list[Rule] = []
    if not path.is_file():
        return rules
    depth = len([part for part in base.split("/") if part])
    segment = 0
    order = 0
    fallback = "运行产物" if base.startswith(".codeartsdoer") else ("答案" if base == "eval" else "运行产物")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        marker = re.match(r"#\s*──\s*(\d)\.", line)
        if marker:
            segment = int(marker.group(1))
            continue
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        body = line[1:].strip() if negated else line
        if not body:
            continue
        reason = SEGMENT_REASONS.get(segment, fallback) if base == "" else fallback
        rules.append(Rule(base, depth, body, body.endswith("/"), negated, reason, order))
        order += 1
    return rules


class IgnoreResolver:
    def __init__(self, root: Path):
        self.rules = (
            parse_ignore(root / ".gitignore", "")
            + parse_ignore(root / ".codeartsdoer" / ".gitignore", ".codeartsdoer")
            + parse_ignore(root / "eval" / ".gitignore", "eval")
        )

    def resolve(self, rel: str) -> tuple[bool, str | None, Rule | None]:
        ignored = False
        reason: str | None = None
        matched: Rule | None = None
        for rule in self.rules:
            if rule.applies(rel):
                ignored = not rule.negated
                reason = None if rule.negated else rule.reason
                matched = rule
        return ignored, reason, matched


def load_override(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _skip_dir(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == ".git"


def _collect_l2(root: Path) -> list[dict]:
    entries: list[dict] = []
    for rel in L2_DIRS:
        path = root / rel
        if not path.is_dir():
            continue
        digest = hashlib.sha256()
        total = 0
        rows: list[tuple[str, int]] = []
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if d != ".git")
            for name in sorted(filenames):
                full = Path(dirpath) / name
                try:
                    size = full.stat().st_size
                    rows.append((posix(full.relative_to(path)), size))
                except OSError:
                    continue
        rows.sort()
        for sub, size in rows:
            digest.update(f"{sub}\0{size}\n".encode("utf-8"))
            total += size
        entries.append(
            {
                "path": rel,
                "sha256": digest.hexdigest(),
                "size": total,
                "role": "derived",
                "tracked": False,
                "aggregated": True,
                "file_count": len(rows),
                "digest_mode": "path+size",
            }
        )
    return entries


def build_manifest(root: Path, phase: str, override: set[str], skip_paths: set[str] | None = None) -> dict:
    resolver = IgnoreResolver(root)
    skip_paths = skip_paths or set()
    files: list[dict] = []
    errors: list[str] = []

    for entry in _collect_l2(root):
        files.append(entry)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = posix(Path(dirpath).relative_to(root))
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not _skip_dir(f"{rel_dir}/{d}" if rel_dir else d)
            and (posix(Path(dirpath).relative_to(root) / d) not in L2_DIRS)
        )
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rel in skip_paths:
                continue
            role = classify(rel)
            if role in ("secret", "answer"):
                tracked = False
                reason = "凭据证书" if role == "secret" else "答案"
            elif rel in override:
                tracked = True
                reason = None
            else:
                ignored, reason, _rule = resolver.resolve(rel)
                tracked = not ignored
            try:
                size = full.stat().st_size
                digest = sha256_file(full)
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
                continue
            files.append(
                {
                    "path": rel,
                    "sha256": digest,
                    "size": size,
                    "role": role,
                    "tracked": tracked,
                }
            )

    if errors:
        raise ManifestError(errors)

    files.sort(key=lambda item: item["path"].encode("utf-8"))
    excluded = _excluded_report(files, resolver, override)
    digest = manifest_digest(files)
    return {
        "schema_version": "1",
        "phase": phase,
        "generated_at": now_iso(),
        "root": ".",
        "files": files,
        "excluded": excluded,
        "manifest_digest": digest,
        "cross_check": {
            "merkle_root_hash": "",
            "merkle_file_count": 0,
            "consistent": False,
            "differences": [],
            "content_comparable": False,
            "note": "占位：由 cross-check 子命令填充",
        },
    }


def _excluded_report(files: list[dict], resolver: IgnoreResolver, override: set[str]) -> list[dict]:
    untracked = [item for item in files if not item["tracked"]]
    rows: list[dict] = []
    for rule in resolver.rules:
        if rule.negated:
            continue
        matched = [
            item["path"]
            for item in untracked
            if rule.applies(item["path"], bool(item.get("aggregated")))
        ]
        rows.append(
            {
                "pattern_or_path": prefix_path(rule.base, rule.pattern),
                "reason": rule.reason,
                "matched_count": len(matched),
                "source": f"{(rule.base + '/') if rule.base else ''}.gitignore",
                "rule": rule.pattern,
            }
        )
    rows.append(
        {
            "pattern_or_path": "override: .evidence/git-baseline/override-paths.txt",
            "reason": None,
            "matched_count": sum(1 for item in files if item["tracked"] and item["path"] in override),
            "note": "嵌套 .gitignore 均为 *，上层否定规则无法覆盖下层，只能以 git add -f 强制纳入",
        }
    )
    secrets = [item["path"] for item in files if item["role"] == "secret"]
    answers = [item["path"] for item in files if item["role"] == "answer"]
    if secrets:
        rows.append({"pattern_or_path": "role=secret", "reason": "凭据证书", "matched_count": len(secrets), "samples": secrets[:5]})
    if answers:
        rows.append({"pattern_or_path": "role=answer", "reason": "答案", "matched_count": len(answers), "samples": answers[:5]})
    return rows


def prefix_path(base: str, pattern: str) -> str:
    return f"{base}/{pattern}" if base else pattern


def manifest_digest(files: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in files:
        flag = "1" if item["tracked"] else "0"
        digest.update(f"{item['path']}\0{item['sha256']}\0{item['size']}\0{item['role']}\0{flag}\n".encode("utf-8"))
    return digest.hexdigest()


class ManifestError(RuntimeError):
    def __init__(self, paths: list[str]):
        super().__init__("unreadable: " + ", ".join(paths[:10]))
        self.paths = paths


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path, exit_code: int) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ERROR] 无法读取 {path}: {exc}", file=sys.stderr)
        raise SystemExit(exit_code)


def cmd_manifest(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if args.phase == "pre" and (root / ".git").exists():
        print("[ERROR] --phase pre 要求工作区尚无 .git", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED
    override = load_override(Path(args.override).resolve() if args.override else root / ".evidence/git-baseline/override-paths.txt")
    out = Path(args.out).resolve() if args.out else None
    skip: set[str] = set()
    if out is not None:
        try:
            skip.add(posix(out.relative_to(root)))
        except ValueError:
            pass
    try:
        payload = build_manifest(root, args.phase, override, skip)
    except ManifestError as exc:
        print(f"[ERROR] 文件不可读：{exc}", file=sys.stderr)
        return EXIT_MANIFEST_UNREADABLE
    if out:
        write_json(out, payload)
    tracked = [item for item in payload["files"] if item["tracked"]]
    summary = {
        "phase": payload["phase"],
        "files": len(payload["files"]),
        "tracked": len(tracked),
        "tracked_bytes": sum(item["size"] for item in tracked),
        "max_file_bytes": max((item["size"] for item in tracked), default=0),
        "excluded_entries": len(payload["excluded"]),
        "manifest_digest": payload["manifest_digest"],
        "out": str(out) if out else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_cross_check(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    snapshot_path = Path(args.snapshot).resolve()
    manifest = load_json(manifest_path, EXIT_MANIFEST_UNREADABLE)
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        root_hash = snippet(snapshot.get("rootHash"))
        file_count = int(snapshot.get("fileCount"))
        timestamp = snippet(snapshot.get("timestamp"))
        snapshot_files = snapshot.get("files") or []
        if not root_hash or not isinstance(snapshot_files, list):
            raise ValueError("rootHash/files 缺失")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(f"[ERROR] 快照不可读：{exc}", file=sys.stderr)
        return EXIT_SNAPSHOT_UNREADABLE

    manifest_files = {item["path"]: item for item in manifest.get("files", [])}
    snap_map: dict[str, dict] = {}
    for item in snapshot_files:
        path = str(item.get("path", "")).replace("\\", "/")
        if path:
            snap_map[path] = item

    only_in_snapshot = sorted(set(snap_map) - set(manifest_files))
    only_in_manifest = sorted(set(manifest_files) - set(snap_map))
    size_mismatch = sorted(
        path
        for path in set(snap_map) & set(manifest_files)
        if int(snap_map[path].get("size", -1)) != int(manifest_files[path].get("size", -2))
    )

    groups = [
        {
            "kind": "口径差异：快照仅覆盖代码域与部分证据",
            "count": len(only_in_snapshot),
            "samples": only_in_snapshot[:20],
        },
        {
            "kind": "时间差异：快照生成后新增文件",
            "count": len(only_in_manifest),
            "samples": only_in_manifest[:20],
        },
        {
            "kind": "大小不一致",
            "count": len(size_mismatch),
            "samples": size_mismatch[:20],
        },
    ]
    consistent = int(file_count) == len(manifest_files) and not only_in_snapshot and not only_in_manifest and not size_mismatch
    payload = {
        "merkle_root_hash": root_hash,
        "merkle_file_count": file_count,
        "merkle_timestamp": timestamp,
        "manifest_file_count": len(manifest_files),
        "content_comparable": False,
        "hash_algorithm": "unavailable",
        "consistent": consistent,
        "differences": [group for group in groups if group["count"]],
        "attribution": [
            {
                "kind": "口径差异",
                "detail": f"快照仅覆盖代码域与部分证据（{file_count} 项），清单覆盖全量工作区（{len(manifest_files)} 项）",
                "count": len(only_in_manifest),
            },
            {
                "kind": "时间差异",
                "detail": "快照生成（timestamp={0}）之后工作区新增文件".format(timestamp),
                "count": len(only_in_manifest),
            },
        ],
        "note": "快照 hash 算法不可复算，本轮仅做计数 + 路径集合 + 大小级校验；不声称内容级一致",
    }
    write_json(Path(args.out).resolve(), payload)
    detail_path = Path(args.out).resolve().with_name("cross-check-differences.json")
    write_json(
        detail_path,
        {
            "only_in_snapshot": only_in_snapshot,
            "only_in_manifest": only_in_manifest,
            "size_mismatch": size_mismatch,
            "note": "完整差异明细；取样路径不代表全部",
        },
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_OK


def snippet(value) -> str:
    return "" if value is None else str(value)


def cmd_diff(args: argparse.Namespace) -> int:
    before = load_json(Path(args.before).resolve(), EXIT_MANIFEST_UNREADABLE)
    after = load_json(Path(args.after).resolve(), EXIT_MANIFEST_UNREADABLE)
    waive = {item.strip() for item in (args.waive_tier or "").split(",") if item.strip()}
    before_map = {item["path"]: item for item in before.get("files", []) if item.get("tracked")}
    after_map = {item["path"]: item for item in after.get("files", []) if item.get("tracked")}

    added = sorted(set(after_map) - set(before_map))
    deleted = sorted(set(before_map) - set(after_map))
    changed = sorted(
        path
        for path in set(before_map) & set(after_map)
        if before_map[path].get("sha256") != after_map[path].get("sha256") or before_map[path].get("size") != after_map[path].get("size")
    )

    waived_paths = [path for path in (added + deleted + changed) if path in waive]
    added_unexpected = [path for path in added if path not in waive and not any(path == prefix or path.startswith(prefix) for prefix in ADDED_WHITELIST)]
    non_waived = [path for path in changed + deleted if path not in waive] + added_unexpected
    payload = {
        "before": str(Path(args.before).resolve()),
        "after": str(Path(args.after).resolve()),
        "added": added,
        "changed": changed,
        "deleted": deleted,
        "waived": waived_paths,
        "added_whitelisted": [path for path in added if path not in waive and path not in added_unexpected],
        "added_unexpected": added_unexpected,
        "non_waived_diff_count": len(non_waived),
        "non_waived": non_waived,
    }
    write_json(Path(args.out).resolve(), payload)
    print(json.dumps({key: (len(value) if isinstance(value, list) else value) for key, value in payload.items()}, ensure_ascii=False, indent=2))
    return EXIT_OK


def run_json(script: str, *extra: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--json", *extra],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"error": completed.stdout[-500:], "stderr": completed.stderr[-500:], "returncode": completed.returncode}


def git(*args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return completed.returncode, completed.stdout.strip()


def cmd_verify(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest).resolve(), EXIT_MANIFEST_UNREADABLE)
    meta_path = Path(args.meta).resolve()
    meta = load_json(meta_path, EXIT_MANIFEST_UNREADABLE) if meta_path.is_file() else {}

    code, count_out = git("rev-list", "--count", "HEAD")
    ac01 = code == 0 and count_out == "1"
    parent_code, _ = git("rev-parse", "HEAD^")
    if parent_code == 0:
        ac01 = False
    subjects_code, subjects = git("log", "--format=%s")
    subjects = subjects if subjects_code == 0 else ""
    if any(subject.startswith(step[0]) for step in STEPS for subject in subjects.splitlines()):
        ac01 = False

    files = {item["path"]: item for item in manifest.get("files", [])}
    tracked = {path: item for path, item in files.items() if item.get("tracked")}
    ls_code, ls_out = git("ls-files")
    ls_files = set(ls_out.splitlines()) if ls_code == 0 else None
    ac02 = ls_files is not None and ls_files == set(tracked)
    for pattern in ("frontend/node_modules", "__pycache__", ".pyc", "edgeprofile", "eval/expected", ".git/"):
        _, hit_out = git("ls-files", f"*{pattern}*")
        if hit_out.strip():
            ac02 = False

    total_bytes = sum(item["size"] for item in tracked.values())
    max_bytes = max((item["size"] for item in tracked.values()), default=0)
    ac03 = len(tracked) <= LIMIT_FILES and total_bytes <= LIMIT_BYTES and max_bytes <= LIMIT_FILE_BYTES

    perms = run_json("check_permissions.py")
    ac04 = perms.get("blocking_total") == 0 and perms.get("passed") is True
    ac11 = ac04 and not (perms.get("branch_guard") or {}).get("problems")

    devlog = run_json("check_devlog.py")
    ac10 = devlog.get("blocking_total") == 7 and len(devlog.get("global_blocking") or []) == 5 and devlog.get("passed") is False

    cross = {}
    cross_path = EVIDENCE / "cross-check.json"
    if cross_path.is_file():
        cross = json.loads(cross_path.read_text(encoding="utf-8"))
    ac09 = bool(cross) and cross.get("content_comparable") is False and cross.get("consistent") is False and bool(cross.get("differences"))

    diff_path = EVIDENCE / "pre-post-diff.json"
    diff = json.loads(diff_path.read_text(encoding="utf-8")) if diff_path.is_file() else {}
    ac05 = diff.get("non_waived_diff_count") == 0
    ac14 = ac05 and not any(path.startswith(("backend/", "frontend/src/", "mcp/")) for path in diff.get("changed", []))

    conventions = (ROOT / "docs/devlog/00-conventions.md").read_text(encoding="utf-8", errors="replace")
    c8 = (ROOT / ".codeartsdoer/specs/sandbox_realscan/tasks.md").read_text(encoding="utf-8", errors="replace")
    ac06 = "3.2 前版本控制期留痕" in conventions and "6. 基线提交" in conventions and "允许只读 git 查询" in c8

    record_doc = ROOT / "docs/devlog/vcs-baseline.md"
    record_text = record_doc.read_text(encoding="utf-8", errors="replace") if record_doc.is_file() else ""
    ac07 = record_text.count("tier=A") == 3 and record_text.count("tier=B") == 12 and record_text.count("tier=C") == 12

    ac08 = manifest_digest(manifest.get("files", [])) == manifest.get("manifest_digest")
    ac12 = "vcs-baseline/" in record_text and "definition_version=v2" in record_text
    ac13 = not W_REAL_GIT.search(record_text + c8) and "fixture=true" in c8

    all_texts = [record_text]
    for path in ("docs/devlog/00-conventions.md", ".codeartsdoer/specs/selfcheck_harness/design.md"):
        candidate = ROOT / path
        if candidate.is_file():
            all_texts.append(candidate.read_text(encoding="utf-8", errors="replace"))
    ac_hit = sum(len(W_HIT.findall(text)) for text in all_texts)

    results = [
        {"id": "AC-01", "pass": ac01, "evidence": f"rev-list count={count_out}, HEAD^ rc={parent_code}"},
        {"id": "AC-02", "pass": ac02, "evidence": f"ls-files={len(ls_files or [])}, tracked={len(tracked)}"},
        {"id": "AC-03", "pass": ac03, "evidence": f"files={len(tracked)}, bytes={total_bytes}, max={max_bytes}"},
        {"id": "AC-04", "pass": ac04, "evidence": f"blocking_total={perms.get('blocking_total')}"},
        {"id": "AC-05", "pass": ac05, "evidence": f"non_waived={diff.get('non_waived_diff_count')}"},
        {"id": "AC-06", "pass": ac06, "evidence": "00-conventions 3.2/第 6 条 + C8 新语义"},
        {"id": "AC-07", "pass": ac07, "evidence": "Tier A/B/C 记录数 3/12/12"},
        {"id": "AC-08", "pass": ac08, "evidence": "manifest_digest 复算"},
        {"id": "AC-09", "pass": ac09, "evidence": "cross-check.json"},
        {"id": "AC-10", "pass": ac10, "evidence": f"blocking_total={devlog.get('blocking_total')}, global={len(devlog.get('global_blocking') or [])}"},
        {"id": "AC-11", "pass": ac11, "evidence": "check_permissions branch_guard"},
        {"id": "AC-12", "pass": ac12, "evidence": "vcs-baseline / definition_version=v2"},
        {"id": "AC-13", "pass": ac13, "evidence": "fixture=true 保留、无真实 .git 断言"},
        {"id": "AC-14", "pass": ac14, "evidence": "diff 无源码改动"},
    ]
    payload = {
        "checked_at": now_iso(),
        "manifest": str(Path(args.manifest).resolve()),
        "meta": str(meta_path),
        "baseline_label": meta.get("baseline_label", ""),
        "commit_id": meta.get("commit_id", ""),
        "results": results,
        "passed_count": sum(1 for item in results if item["pass"]),
        "failed": [item["id"] for item in results if not item["pass"]],
        "hit_forbidden_claims": ac_hit,
        "warnings": [
            item for item in (
                "AC-08 抽样的评审者签署属人工项，未在本报告中代填" if ac08 else "",
                "AC-13 需人工复核沙箱报告原文" if ac13 else "",
            ) if item
        ],
    }
    out = Path(args.out).resolve() if args.out else EVIDENCE / "ac-report.json"
    write_json(out, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_OK if not payload["failed"] else EXIT_INIT_INCOMPLETE


def cmd_init(args: argparse.Namespace) -> int:
    if not args.confirm:
        print("[ERROR] 需要 --confirm 才会创建基线提交", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED
    git_dir = ROOT / ".git"
    if git_dir.exists():
        code, subjects = git("log", "--format=%s")
        code2, count = git("rev-list", "--count", "HEAD")
        if code == 0 and code2 == 0 and count == "1":
            meta_path = EVIDENCE / "baseline-meta.json"
            label = ""
            if meta_path.is_file():
                label = json.loads(meta_path.read_text(encoding="utf-8")).get("baseline_label", "")
            print(json.dumps({"status": "already_initialized", "commit_id": git("rev-parse", "HEAD")[1], "baseline_label": label}, ensure_ascii=False, indent=2))
            return EXIT_OK
        print("[ERROR] .git 已存在但状态不是单基线提交，停止并转人工", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED

    for required in (".gitignore", ".gitattributes"):
        if not (ROOT / required).is_file():
            print(f"[ERROR] 缺少 {required}", file=sys.stderr)
            return EXIT_INIT_INCOMPLETE

    perms = run_json("check_permissions.py")
    if perms.get("blocking_total") != 0:
        print(json.dumps(perms, ensure_ascii=False, indent=2))
        return EXIT_SENSITIVE_HIT

    override = load_override(DEFAULT_OVERRIDE)
    pre_path = EVIDENCE / "pre-vcs-manifest.json"
    if pre_path.is_file() and (ROOT / ".git").exists():
        print("[ERROR] pre 清单与 .git 同时存在，状态矛盾", file=sys.stderr)
        return EXIT_PRECONDITION_FAILED
    manifest = build_manifest(ROOT, "pre", override, {posix(pre_path.relative_to(ROOT))})
    write_json(pre_path, manifest)
    tracked = [item for item in manifest["files"] if item["tracked"]]
    if len(tracked) > LIMIT_FILES or sum(item["size"] for item in tracked) > LIMIT_BYTES:
        print(f"[ERROR] 规模超限：{len(tracked)} 文件", file=sys.stderr)
        return EXIT_SIZE_EXCEEDED

    code, out = git("init", "-b", args.branch)
    if code != 0:
        print(out, file=sys.stderr)
        return EXIT_INIT_INCOMPLETE
    git("config", "core.autocrlf", "false")
    git("config", "core.quotepath", "false")
    code, out = git("add", "-A")
    if code != 0:
        print(out, file=sys.stderr)
        return EXIT_INIT_INCOMPLETE
    for rel in sorted(override):
        if (ROOT / rel).is_file():
            git("add", "-f", "--", rel)
    message = (
        f"[vcs-baseline] initialize repository baseline\n\n"
        f"tracked={len(tracked)}\n"
        f"excluded={sum(1 for item in manifest['files'] if not item['tracked'])}\n"
        f"manifest={manifest['manifest_digest']}\n"
    )
    code, out = git("commit", "-m", message)
    if code != 0:
        print(out, file=sys.stderr)
        return EXIT_INIT_INCOMPLETE
    commit_id = git("rev-parse", "HEAD")[1]
    write_json(
        EVIDENCE / "baseline-meta.json",
        {
            "commit_id": commit_id,
            "branch": args.branch,
            "committed_at": git("log", "-1", "--format=%cI")[1],
            "tracked_count": len(tracked),
            "excluded_count": sum(1 for item in manifest["files"] if not item["tracked"]),
            "manifest_digest": manifest["manifest_digest"],
            "baseline_label": f"vcs-baseline/{commit_id[:12]}",
        },
    )
    print(json.dumps({"commit_id": commit_id, "baseline_label": f"vcs-baseline/{commit_id[:12]}"}, ensure_ascii=False, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Git 化基线与留痕追溯工具（只读优先）")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="生成追溯清单")
    manifest.add_argument("--phase", choices=("pre", "post"), required=True)
    manifest.add_argument("--out")
    manifest.add_argument("--root", default=str(ROOT))
    manifest.add_argument("--override", default=None)
    manifest.set_defaults(func=cmd_manifest)

    cross = sub.add_parser("cross-check", help="与 merkle 快照交叉校验")
    cross.add_argument("--manifest", required=True)
    cross.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    cross.add_argument("--out", required=True)
    cross.set_defaults(func=cmd_cross_check)

    diff = sub.add_parser("diff", help="比对两份清单")
    diff.add_argument("--before", required=True)
    diff.add_argument("--after", required=True)
    diff.add_argument("--waive-tier", default="")
    diff.add_argument("--out", required=True)
    diff.set_defaults(func=cmd_diff)

    verify = sub.add_parser("verify", help="AC 机器可判部分")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--meta", default=str(EVIDENCE / "baseline-meta.json"))
    verify.add_argument("--out", default=None)
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    init = sub.add_parser("init", help="初始化本地仓库并产生单基线提交")
    init.add_argument("--branch", default="main")
    init.add_argument("--confirm", action="store_true")
    init.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())