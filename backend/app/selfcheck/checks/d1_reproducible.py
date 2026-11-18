"""D1 可复现性检查项（6 项）。"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

from app.realscan.evidence import EvidencePackWriter

from ..models import (
    CheckResult,
    CheckSpec,
    Dimension,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)
from ..probes import EnvMode

_MISSING = "MISSING"


def _d1_1(ctx: object) -> CheckResult:
    script = (
        "import sys; sys.path.insert(0, 'backend');"
        "from app.config import load_config;"
        "load_config(); print('config ok')"
    )
    output = ctx.probe.run(
        [sys.executable, "-c", script],
        timeout=60,
        cwd=ctx.root,
        env_mode=EnvMode.CLEAN,
    )
    command = "python -c \"<load_config 并打印 config ok>\"（CLEAN 环境，清空 PYTHON*）"
    if output.unavailable:
        return build_result(
            _SPECS[0], Status.UNVERIFIED, sub_reason="RUNTIME_UNAVAILABLE", command=command,
            output_summary="解释器不可用，未执行。", duration_seconds=output.duration_seconds,
        )
    if output.timed_out:
        return build_result(
            _SPECS[0], Status.BLOCKED, sub_reason="TIMEOUT", command=command,
            output_summary="配置加载超时。", duration_seconds=output.duration_seconds,
        )
    if output.exit_code == 0 and "config ok" in output.stdout_tail:
        return build_result(
            _SPECS[0], Status.PASS, command=command, exit_code=0,
            output_summary="干净环境下配置加载成功（无隐式 PYTHON* 依赖）。",
            duration_seconds=output.duration_seconds,
        )
    return build_result(
        _SPECS[0], Status.BLOCKED, sub_reason="CONFIG_LOAD_FAILED", command=command,
        exit_code=output.exit_code,
        output_summary=(
            "干净环境配置加载失败；若提示编码错误，通常源于隐式 PYTHONUTF8 依赖。"
            f"stderr：{output.stderr_tail[-400:]}"
        ),
        duration_seconds=output.duration_seconds,
    )


def _d1_2(ctx: object) -> CheckResult:
    output = ctx.probe.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py"],
        timeout=ctx.thresholds.regression_timeout,
        cwd=ctx.root,
        env_mode=EnvMode.INHERIT,
    )
    command = "python -m unittest discover -s backend/tests -p \"test_*.py\"（默认环境）"
    text = output.stdout_tail + "\n" + output.stderr_tail
    ran = re.search(r"Ran (\d+) tests?", text)
    errors = re.search(r"errors=(\d+)", text)
    failures = re.search(r"failures=(\d+)", text)
    error_count = int(errors.group(1)) if errors else 0
    failure_count = int(failures.group(1)) if failures else 0
    total = int(ran.group(1)) if ran else 0
    detail = f"Ran {total} tests；errors={error_count}；failures={failure_count}"
    if output.timed_out:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="TIMEOUT", command=command,
            output_summary=f"全量回归超时（>{ctx.thresholds.regression_timeout:.0f}s）。",
            duration_seconds=output.duration_seconds,
        )
    if output.unavailable:
        return build_result(
            _SPECS[1], Status.UNVERIFIED, sub_reason="RUNTIME_UNAVAILABLE", command=command,
            output_summary="解释器不可用，未执行全量回归。",
            duration_seconds=output.duration_seconds,
        )
    if ran is None:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="UNPARSEABLE", command=command,
            exit_code=output.exit_code,
            output_summary="无法解析回归输出。" + text[-400:],
            duration_seconds=output.duration_seconds,
        )
    if error_count == 0 and failure_count == 0:
        return build_result(
            _SPECS[1], Status.PASS, command=command, exit_code=output.exit_code,
            output_summary=detail,
            duration_seconds=output.duration_seconds,
        )
    failing = re.findall(r"(?:FAIL|ERROR): ([^\s]+)", text)
    return build_result(
        _SPECS[1], Status.BLOCKED, sub_reason="TEST_FAILED", command=command,
        exit_code=output.exit_code,
        output_summary=detail + "；" + ", ".join(failing[:5]),
        duration_seconds=output.duration_seconds,
    )


def _d1_3(ctx: object) -> CheckResult:
    output = ctx.probe.run(
        [sys.executable, "scripts/smoke_m0.py"],
        timeout=ctx.thresholds.item_timeout,
        cwd=ctx.root,
        env_mode=EnvMode.INHERIT,
    )
    command = "python scripts/smoke_m0.py"
    if output.unavailable:
        return build_result(
            _SPECS[2], Status.UNVERIFIED, sub_reason="RUNTIME_UNAVAILABLE", command=command,
            output_summary="脚本不可用，未执行。", duration_seconds=output.duration_seconds,
        )
    if output.timed_out:
        return build_result(
            _SPECS[2], Status.BLOCKED, sub_reason="TIMEOUT", command=command,
            output_summary="空转闭环超时。", duration_seconds=output.duration_seconds,
        )
    if output.exit_code == 0 and "chain_valid=True" in output.stdout_tail:
        return build_result(
            _SPECS[2], Status.PASS, command=command, exit_code=0,
            output_summary="空转闭环成立（chain_valid=True）。",
            duration_seconds=output.duration_seconds,
        )
    return build_result(
        _SPECS[2], Status.BLOCKED, sub_reason="CHAIN_BROKEN", command=command,
        exit_code=output.exit_code,
        output_summary="未观测到 chain_valid=True。" + output.stderr_tail[-300:],
        duration_seconds=output.duration_seconds,
    )


def _d1_4(ctx: object) -> CheckResult:
    readme = ctx.read_text("README.md")
    command = "README §3 五步链路前提检测（默认不执行链路、不写盘）"
    if readme is None:
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason=_MISSING, command=command,
            output_summary="README.md 缺失，无法定位 15 分钟路径。",
        )
    has_section = bool(re.search(r"^#+\s*3[.\s、]", readme, re.MULTILINE))
    has_flow = ("run_eval" in readme) or ("复现" in readme)
    if not (has_section or has_flow):
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="PRECONDITION_UNMET", command=command,
            output_summary="README 中未定位到 §3 复现路径。",
        )
    return build_result(
        _SPECS[3], Status.UNVERIFIED, sub_reason="PRECONDITION_UNMET", command=command,
        output_summary=(
            "默认不执行 15 分钟链路（会写 eval/runs 与指标报告），仅完成前提检测："
            f"README §3={'存在' if has_section else '以关键词近似定位'}；如需计时请显式 --allow-writes。"
        ),
    )


def _d1_5(ctx: object) -> CheckResult:
    frontend = ctx.root / "frontend"
    command = "node node_modules/vue-tsc/bin/vue-tsc.js --noEmit；node node_modules/vite/bin/vite.js build --outDir <tmp>/dist"
    if not frontend.is_dir():
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason=_MISSING, command=command,
            output_summary="frontend/ 目录缺失。",
        )
    node = shutil.which("node")
    if not node:
        return build_result(
            _SPECS[4], Status.UNVERIFIED, sub_reason="DEPENDENCY_UNAVAILABLE", command=command,
            output_summary="node 不可用，未执行前端构建。",
        )
    vue_tsc = frontend / "node_modules" / "vue-tsc" / "bin" / "vue-tsc.js"
    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not vue_tsc.is_file() or not vite.is_file():
        return build_result(
            _SPECS[4], Status.UNVERIFIED, sub_reason="DEPENDENCY_UNAVAILABLE", command=command,
            output_summary="node_modules 缺失（未自动安装，避免额外写盘与长耗时）。",
        )
    typecheck = ctx.probe.run(
        [node, str(vue_tsc), "--noEmit"],
        timeout=ctx.thresholds.build_timeout,
        cwd=frontend,
        env_mode=EnvMode.INHERIT,
    )
    if typecheck.timed_out or typecheck.exit_code != 0:
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="TYPECHECK_FAILED", command=command,
            exit_code=typecheck.exit_code,
            output_summary="类型检查未通过。" + typecheck.stderr_tail[-400:],
            duration_seconds=typecheck.duration_seconds,
        )
    out_dir = ctx.tmp_dir / "dist"
    build = ctx.probe.run(
        [node, str(vite), "build", "--outDir", str(out_dir)],
        timeout=ctx.thresholds.build_timeout,
        cwd=frontend,
        env_mode=EnvMode.INHERIT,
    )
    produced = out_dir.is_dir() and any(out_dir.rglob("*"))
    if build.timed_out or build.exit_code != 0 or not produced:
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="BUILD_FAILED", command=command,
            exit_code=build.exit_code,
            output_summary="构建未通过或产物为空。" + build.stderr_tail[-400:],
            duration_seconds=build.duration_seconds,
        )
    return build_result(
        _SPECS[4], Status.PASS, command=command, exit_code=build.exit_code,
        output_summary=f"类型检查与构建通过，产物落临时目录（{len(list(out_dir.rglob('*')))} 项）。",
        duration_seconds=build.duration_seconds,
    )


def _d1_6(ctx: object) -> CheckResult:
    command = "容器能力探测（docker / WSL docker）+ 最近 VER 包摘要校验（只读，不重跑）"
    candidates: list[list[str]] = []
    docker = shutil.which("docker")
    if docker:
        candidates.append([docker, "version", "--format", "{{.Server.Version}}"])
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if wsl:
        candidates.append([wsl, "docker", "version", "--format", "{{.Server.Version}}"])
    if not candidates:
        return build_result(
            _SPECS[5], Status.UNVERIFIED, sub_reason="RUNTIME_UNAVAILABLE", command=command,
            output_summary="docker CLI 与 WSL 均不可用，未执行沙箱复现校验。",
        )
    probe = None
    last_output = ""
    for attempt in range(2):
        for argv in candidates:
            probe = ctx.probe.run(argv, timeout=30, cwd=ctx.root)
            if probe.exit_code == 0 and not probe.timed_out:
                break
            last_output = (probe.stderr_tail or probe.stdout_tail).strip()[-200:]
        if probe is not None and probe.exit_code == 0 and not probe.timed_out:
            break
        if attempt == 0:
            time.sleep(5)
    if probe is None or probe.exit_code != 0 or probe.timed_out:
        return build_result(
            _SPECS[5], Status.UNVERIFIED, sub_reason="RUNTIME_UNAVAILABLE", command=command,
            output_summary=(
                "容器运行时不可用（两次探测均失败），未执行沙箱校验；最后返回："
                + (last_output or "无输出")
            ),
            duration_seconds=probe.duration_seconds if probe else 0.0,
        )
    if ctx.refresh_evidence:
        ctx.notes.append("D1-6 已开启 --refresh-evidence：沙箱重跑与 .evidence 写入不在只读保证内。")
        return build_result(
            _SPECS[5], Status.UNVERIFIED, sub_reason="REFRESH_REQUESTED", command=command,
            output_summary="已请求重跑沙箱证据；本次自检不代跑证据写入，请单独执行 run_sandbox_verify.py。",
        )
    evidence_root = ctx.root / ".evidence"
    packs: list[tuple[Path, str]] = []
    for index_path in sorted(evidence_root.rglob("INDEX.json")) if evidence_root.is_dir() else []:
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for pack in payload.get("packs") or []:
            if isinstance(pack, dict) and str(pack.get("evidence_id", "")).startswith("VER-"):
                packs.append((index_path.parent, str(pack["evidence_id"])))
    if not packs:
        return build_result(
            _SPECS[5], Status.BLOCKED, sub_reason=_MISSING, command=command,
            output_summary="证据索引中无 VER 包，无法校验沙箱复现。",
        )
    root, evidence_id = packs[-1]
    report = EvidencePackWriter(root).verify(evidence_id)
    if report.ok:
        return build_result(
            _SPECS[5], Status.PASS, command=command, exit_code=0,
            output_summary=f"容器可用；最近 VER 包 {evidence_id} 摘要校验通过。",
            evidence_refs=[evidence_id],
            duration_seconds=probe.duration_seconds,
        )
    return build_result(
        _SPECS[5], Status.BLOCKED, sub_reason="EVIDENCE_TAMPERED", command=command,
        output_summary=f"{evidence_id} 摘要校验失败：{', '.join(report.mismatches)[:300]}",
        evidence_refs=[evidence_id],
        duration_seconds=probe.duration_seconds,
    )


_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec("D1-1", "干净环境配置加载", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "退出码 0 且输出含 config ok", handler=_d1_1),
    CheckSpec("D1-2", "全量回归", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "errors=0 且 failures=0，记录用例数",
              depends_on=("D1-1",), handler=_d1_2),
    CheckSpec("D1-3", "空转闭环", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "退出码 0 且 stdout 含 chain_valid=True", handler=_d1_3),
    CheckSpec("D1-4", "15 分钟路径", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "全链 ≤900s 且产出指标报告（默认仅前提检测）",
              depends_on=("D1-1",), handler=_d1_4),
    CheckSpec("D1-5", "前端构建", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "类型检查与构建退出码 0 且产物非空", handler=_d1_5),
    CheckSpec("D1-6", "沙箱复现", Dimension.REPRODUCIBLE, JudgmentMode.AUTO,
              ThreeQuestion.REPRODUCE, "容器可用且最近 VER 包 verify().ok=True", handler=_d1_6),
)

SPECS = _SPECS