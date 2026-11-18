from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.agents.patcher.templates import PatchCandidate
from app.agents.reproducer.executor import TestExecution, TestExecutorPort
from app.agents.reproducer.templates import render_test
from app.api.envelope import ErrorCode
from app.config import AppConfig
from app.domain.enums import AuditRuleId, AuditVerdict, FixParadigm, ProofResult
from app.domain.models import Alert, AuditFinding, Event, Issue, Patch, Proof
from app.tools.diff import DiffAnalyzer, DiffAnalysis

BACKDOOR_RULES = frozenset({AuditRuleId.R2, AuditRuleId.R3, AuditRuleId.R4, AuditRuleId.R5})
SCAN_CONFIG_FILES = frozenset(
    {
        ".codearts-check.yml",
        ".codearts-check.yaml",
        "sonar-project.properties",
        ".semgrep.yml",
        "check_rules.json",
    }
)


class CriticStatus(str):
    PASSED = "PASSED"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True)
class CriticOutcome:
    status: str
    findings: tuple[AuditFinding, ...]
    red_green_paired: bool
    regression_zero_fail: bool
    anti_cheat_ok: bool
    coverage_delta_pp: float
    message: str
    error_code: ErrorCode | None
    executions: dict[str, TestExecution]
    test_fingerprint: str


def _finding(rule: AuditRuleId, threshold: str, location: str, passed: bool, reason: str = "") -> AuditFinding:
    return AuditFinding(
        patch_id="pending",
        rule_id=rule,
        threshold=threshold,
        hit_location=location,
        verdict=AuditVerdict.PASS if passed else AuditVerdict.REJECT,
        reason=reason,
    )


def _filtered_io_hit(analysis: DiffAnalysis, allow_env: bool, allow_command: bool = False) -> bool:
    patterns = (
        "open(",
        "requests.",
        "urllib",
        "socket",
        "http://",
        "https://",
        "subprocess",
        "system(",
        "pathlib.Path",
    )
    for line in analysis.added:
        content = line.content
        if allow_env and ("os.environ" in content or "getenv(" in content):
            continue
        if allow_command and "subprocess.run([" in content and "shell=True" not in content:
            continue
        if any(pattern in content for pattern in patterns):
            return True
        if "os.environ" in content or "getenv(" in content:
            return True
    return False


class CriticService:
    def __init__(self, store, config: AppConfig, executor: TestExecutorPort):
        self.store = store
        self.config = config
        self.executor = executor
        self.analyzer = DiffAnalyzer()

    def evaluate(
        self,
        issue: Issue,
        patch: Patch,
        candidate: PatchCandidate,
        target_root: Path,
        test_paths: tuple[str, ...] = ("tests/test_smoke.py",),
    ) -> CriticOutcome:
        alerts = self.store.alerts_for(issue.issue_id)
        if not alerts:
            return CriticOutcome(CriticStatus.L2, (), False, False, False, 0.0,
                                 "缺少告警定位，无法执行审计", ErrorCode.NOT_NORMALIZED, {}, "")
        alert: Alert = alerts[0]
        proof = self.store.proof_for(issue.issue_id)
        if proof is None or proof.pre_patch_result is not ProofResult.FAIL:
            return CriticOutcome(CriticStatus.L2, (), False, False, False, 0.0,
                                 "缺少有效红态证据，三查失败", ErrorCode.GATE_RED_MISSING, {}, "")

        generated = render_test(issue, alert, target_root)
        rendered_fingerprint = hashlib.sha256(generated.source.encode("utf-8")).hexdigest()
        if rendered_fingerprint != proof.fingerprint:
            finding = _finding(AuditRuleId.R1, "test fingerprint", generated.relative_path, False,
                               "复现测试指纹与登记不一致（疑似篡改）")
            self._write_event(issue, "CHEAT", "test fingerprint mismatch")
            return CriticOutcome(CriticStatus.L2, (finding,), False, False, False, 0.0,
                                 "反作弊失败：复现测试指纹不符，转 L2", ErrorCode.AUDIT_HIT, {}, rendered_fingerprint)

        executed = self._apply_and_run(issue, candidate, target_root, generated.relative_path, test_paths)
        green = executed.get(generated.relative_path)
        regression = [result for path, result in executed.items() if path != generated.relative_path]
        red_green = green is not None and green.exit_code == 0 and not green.timed_out
        zero_fail = all(result.exit_code == 0 and not result.timed_out for result in regression)
        analysis = self.analyzer.parse(candidate.diff)
        findings = [
            item.model_copy(update={"patch_id": patch.patch_id})
            for item in self._audit(candidate, analysis, alert, patch)
        ]

        backdoor = any(item.verdict is AuditVerdict.REJECT and item.rule_id in BACKDOOR_RULES for item in findings)
        audit_reject = any(item.verdict is AuditVerdict.REJECT for item in findings)

        if backdoor:
            status = CriticStatus.L3
            message = "命中后门特征（R2–R5），拒绝并告警"
            code = ErrorCode.BACKDOOR
        elif not red_green:
            status = CriticStatus.L2
            message = "三查失败：补丁前红态存在但补丁后未转绿"
            code = ErrorCode.GATE_RED_MISSING
        elif not zero_fail:
            status = CriticStatus.L2
            message = "三查失败：回归测试出现失败"
            code = ErrorCode.AUDIT_HIT
        elif audit_reject:
            status = CriticStatus.L2
            message = "六条 diff 审计未通过"
            code = ErrorCode.AUDIT_HIT
        else:
            status = CriticStatus.PASSED
            message = "三查 + 六条审计全部通过"
            code = None

        for item in findings:
            self.store.add_audit_finding(item)
        return CriticOutcome(
            status=status,
            findings=tuple(findings),
            red_green_paired=red_green,
            regression_zero_fail=zero_fail,
            anti_cheat_ok=True,
            coverage_delta_pp=0.0,
            message=message,
            error_code=code,
            executions=executed,
            test_fingerprint=rendered_fingerprint,
        )

    def _apply_and_run(
        self,
        issue: Issue,
        candidate: PatchCandidate,
        target_root: Path,
        test_path: str,
        test_paths: tuple[str, ...],
    ) -> dict[str, TestExecution]:
        executions: dict[str, TestExecution] = {}
        with tempfile.TemporaryDirectory(prefix="verifix-critic-", ignore_cleanup_errors=True) as tmp:
            workspace = Path(tmp) / "workspace"
            shutil.copytree(Path(target_root), workspace)
            for relative, content in candidate.files.items():
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            generated_path = workspace / test_path
            generated_path.parent.mkdir(parents=True, exist_ok=True)
            alerts = self.store.alerts_for(issue.issue_id)
            generated = render_test(issue, alerts[0], target_root)
            generated_path.write_text(generated.source, encoding="utf-8")
            executions[test_path] = self.executor.run_tests(workspace, test_path)
            for path in test_paths:
                if not (workspace / path).is_file():
                    continue
                executions[path] = self.executor.run_tests(workspace, path)
        return executions

    def _audit(
        self,
        candidate: PatchCandidate,
        analysis: DiffAnalysis,
        alert: Alert,
        patch: Patch,
    ) -> list[AuditFinding]:
        location = f"{alert.location.file}:{alert.location.line or 0}"
        allow_env = patch.fix_paradigm is FixParadigm.CREDENTIAL_EXTERNALIZATION
        allow_command = patch.fix_paradigm is FixParadigm.PARAMETERIZED_COMMAND
        dependency_only = patch.fix_paradigm is FixParadigm.VERSION_UPGRADE
        findings: list[AuditFinding] = []

        proximity_ok = set(candidate.files) == {alert.location.file} or dependency_only
        findings.append(_finding(AuditRuleId.R1, "只在目标文件改动", location, proximity_ok,
                                 "" if proximity_ok else "补丁改动了目标文件之外的文件"))

        if dependency_only:
            for rule in (AuditRuleId.R2, AuditRuleId.R3, AuditRuleId.R4, AuditRuleId.R5):
                findings.append(_finding(rule, "依赖升级不涉及代码探针", location, True, ""))
        else:
            findings.append(_finding(AuditRuleId.R2, "无新增条件分支", location,
                                     not self.analyzer.adds_conditional(analysis),
                                     "新增条件分支（后门特征）"))
            findings.append(_finding(AuditRuleId.R3, "无新增 IO/网络/环境访问", location,
                                     not _filtered_io_hit(analysis, allow_env, allow_command),
                                     "新增网络/文件/环境变量访问（后门特征）"))
            findings.append(_finding(AuditRuleId.R4, "无字符串常量比较", location,
                                     not self.analyzer.adds_string_const_cmp(analysis),
                                     "新增字符串常量比较（后门特征）"))
            findings.append(_finding(AuditRuleId.R5, "未改动鉴权/加密常量", location,
                                     allow_env or not self.analyzer.touches_auth_constants(analysis),
                                     "改动鉴权/加密常量（后门特征）"))

        scale_ok = (
            candidate.lines_changed <= self.config.patch.max_lines
            and candidate.files_changed <= self.config.patch.max_files
        )
        findings.append(_finding(AuditRuleId.R6, "≤30 行 / ≤3 文件", location, scale_ok,
                                 f"{candidate.lines_changed} 行 / {candidate.files_changed} 文件"))

        config_touched = any(path in SCAN_CONFIG_FILES for path in candidate.files)
        if config_touched:
            findings.append(_finding(AuditRuleId.R1, "扫描配置不可改", location, False,
                                     "补丁修改了扫描配置"))
        return findings

    def _write_event(self, issue: Issue, marker: str, detail: str) -> None:
        from app.domain.enums import EventType

        run = self.store.run_for_issue(issue.issue_id)
        self.store.append(
            Event(
                event_id=f"{marker}-{issue.issue_id}",
                run_id=run.run_id if run else f"run-{issue.issue_id}",
                seq=1,
                event_type=EventType.AUDIT,
                actor="critic",
                payload_ref=detail,
            )
        )