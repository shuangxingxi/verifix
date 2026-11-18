from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class ErrorCode(str, Enum):
    NOT_NORMALIZED = "VF-1001"
    OUT_OF_SCOPE = "VF-1002"
    IDEMPOTENT_HIT = "VF-1003"
    NO_VERDICT = "VF-2001"
    VERDICT_TIMEOUT = "VF-2002"
    REPRO_FAILED = "VF-3001"
    PATCH_OVERSIZED = "VF-4001"
    PATCH_WEAK = "VF-4002"
    AUDIT_HIT = "VF-4003"
    BACKDOOR = "VF-4004"
    GATE_NOT_EXECUTED = "VF-5001"
    GATE_TIMEOUT = "VF-5002"
    GATE_RED_MISSING = "VF-5003"
    CIRCUIT_OPEN = "VF-6001"
    BLACKLISTED = "VF-6002"
    EVIDENCE_MISSING = "VF-7001"
    RECALC_CONFLICT = "VF-7002"
    RECALC_FAILED = "VF-7003"
    DEFINITION_MISSING = "VF-7004"
    REPORT_INCONSISTENT = "VF-7005"
    SNAPSHOT_INTEGRITY = "VF-7006"
    HISTORY_TAMPERED = "VF-7007"
    REPORT_VERSION_CONFLICT = "VF-7008"
    EVAL_INVALID = "VF-8001"
    EVAL_LEGACY_RETIRED = "VF-8002"
    EVAL_ISOLATION_UNMET = "VF-8003"
    EVAL_PATH_FORBIDDEN = "VF-8004"
    EVAL_DIGEST_MISMATCH = "VF-8005"
    EVAL_NOT_ADJUDICATED = "VF-8006"
    EVAL_LEAK_DETECTED = "VF-8007"
    EVAL_SECURITY_ABORT = "VF-8008"
    EVAL_INCOMPLETE = "VF-8009"
    SANDBOX_UNVERIFIABLE = "VF-8010"
    REALSCAN_NOT_ESTABLISHED = "VF-8011"
    EVIDENCE_INTEGRITY = "VF-8012"
    CREDENTIAL_RISK = "VF-9001"
    UNAUTHORIZED = "VF-1004"
    CONFIG_FROZEN = "VF-1005"
    CONFIG_INVALID = "VF-1006"
    SELFCHECK_LOCKED = "VF-7010"
    SELFCHECK_TIMEOUT = "VF-7011"
    SELFCHECK_READONLY_VIOLATION = "VF-7012"
    SELFCHECK_REPORT_WRITE_FAILED = "VF-7013"
    SELFCHECK_BASELINE_INVALID = "VF-7014"
    SELFCHECK_MANUAL_PENDING = "VF-7015"


@dataclass(frozen=True)
class ErrorSpec:
    code: ErrorCode
    http_status: int
    semantic: str
    trigger: str


ERROR_SPECS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.NOT_NORMALIZED: ErrorSpec(ErrorCode.NOT_NORMALIZED, 422, "未归一化", "告警缺规则/定位/类别"),
    ErrorCode.OUT_OF_SCOPE: ErrorSpec(ErrorCode.OUT_OF_SCOPE, 202, "范围外", "类别不在四类内"),
    ErrorCode.IDEMPOTENT_HIT: ErrorSpec(ErrorCode.IDEMPOTENT_HIT, 202, "幂等命中", "指纹已存在"),
    ErrorCode.NO_VERDICT: ErrorSpec(ErrorCode.NO_VERDICT, 409, "无可达性结论", "跳过判定直接请求复现"),
    ErrorCode.VERDICT_TIMEOUT: ErrorSpec(ErrorCode.VERDICT_TIMEOUT, 202, "判定超时", "判定超过 30s"),
    ErrorCode.REPRO_FAILED: ErrorSpec(ErrorCode.REPRO_FAILED, 202, "复现失败", "补丁前已通过"),
    ErrorCode.PATCH_OVERSIZED: ErrorSpec(ErrorCode.PATCH_OVERSIZED, 422, "补丁超限", ">30 行或 >3 文件"),
    ErrorCode.PATCH_WEAK: ErrorSpec(ErrorCode.PATCH_WEAK, 422, "补丁强度不足", "<0.60"),
    ErrorCode.AUDIT_HIT: ErrorSpec(ErrorCode.AUDIT_HIT, 422, "审计命中", "R1–R6 任一"),
    ErrorCode.BACKDOOR: ErrorSpec(ErrorCode.BACKDOOR, 403, "后门特征", "R2–R5"),
    ErrorCode.GATE_NOT_EXECUTED: ErrorSpec(ErrorCode.GATE_NOT_EXECUTED, 503, "门禁未执行", "Pipeline 触发失败"),
    ErrorCode.GATE_TIMEOUT: ErrorSpec(ErrorCode.GATE_TIMEOUT, 504, "门禁超时", "回读 >10min"),
    ErrorCode.GATE_RED_MISSING: ErrorSpec(ErrorCode.GATE_RED_MISSING, 409, "红态缺失", "有绿无红"),
    ErrorCode.CIRCUIT_OPEN: ErrorSpec(ErrorCode.CIRCUIT_OPEN, 423, "熔断中", "类别已熔断"),
    ErrorCode.BLACKLISTED: ErrorSpec(ErrorCode.BLACKLISTED, 202, "黑名单命中", "指纹 7 天内失败"),
    ErrorCode.EVIDENCE_MISSING: ErrorSpec(ErrorCode.EVIDENCE_MISSING, 500, "证据缺失", "引用不可解析"),
    ErrorCode.RECALC_CONFLICT: ErrorSpec(ErrorCode.RECALC_CONFLICT, 409, "复算冲突", "同窗口同档复算进行中"),
    ErrorCode.RECALC_FAILED: ErrorSpec(ErrorCode.RECALC_FAILED, 500, "复算失败", "快照校验或写入失败"),
    ErrorCode.DEFINITION_MISSING: ErrorSpec(ErrorCode.DEFINITION_MISSING, 422, "指标定义缺失", "定义未登记"),
    ErrorCode.REPORT_INCONSISTENT: ErrorSpec(ErrorCode.REPORT_INCONSISTENT, 409, "报告不一致", "报告值与落库记录不符"),
    ErrorCode.SNAPSHOT_INTEGRITY: ErrorSpec(ErrorCode.SNAPSHOT_INTEGRITY, 409, "快照不可信", "摘要或事件链校验失败"),
    ErrorCode.HISTORY_TAMPERED: ErrorSpec(ErrorCode.HISTORY_TAMPERED, 409, "历史留痕被篡改", "历史报告摘要与基线不一致"),
    ErrorCode.REPORT_VERSION_CONFLICT: ErrorSpec(ErrorCode.REPORT_VERSION_CONFLICT, 409, "报告版本冲突", "同窗口同档并发发布"),
    ErrorCode.EVAL_INVALID: ErrorSpec(ErrorCode.EVAL_INVALID, 422, "评测集校验失败", "配比/摘要不符"),
    ErrorCode.EVAL_LEGACY_RETIRED: ErrorSpec(ErrorCode.EVAL_LEGACY_RETIRED, 410, "评测集已退役", "请求加载历史单文件评测集"),
    ErrorCode.EVAL_ISOLATION_UNMET: ErrorSpec(ErrorCode.EVAL_ISOLATION_UNMET, 403, "答案隔离不满足", "启动前权限自检失败"),
    ErrorCode.EVAL_PATH_FORBIDDEN: ErrorSpec(ErrorCode.EVAL_PATH_FORBIDDEN, 403, "装载路径越权", "路径越出用例输入白名单"),
    ErrorCode.EVAL_DIGEST_MISMATCH: ErrorSpec(ErrorCode.EVAL_DIGEST_MISMATCH, 409, "评测摘要不符", "用例/答案/绑定/版本摘要不一致"),
    ErrorCode.EVAL_NOT_ADJUDICATED: ErrorSpec(ErrorCode.EVAL_NOT_ADJUDICATED, 409, "评测运行未裁决", "请求未裁决运行的结论"),
    ErrorCode.EVAL_LEAK_DETECTED: ErrorSpec(ErrorCode.EVAL_LEAK_DETECTED, 409, "评测产物存在答案泄漏", "泄漏扫描命中答案字段或取值"),
    ErrorCode.EVAL_SECURITY_ABORT: ErrorSpec(ErrorCode.EVAL_SECURITY_ABORT, 403, "评测安全中止", "累计越权尝试达到阈值"),
    ErrorCode.EVAL_INCOMPLETE: ErrorSpec(ErrorCode.EVAL_INCOMPLETE, 422, "评测数据不完整", "用例与答案条数或标识不匹配"),
    ErrorCode.SANDBOX_UNVERIFIABLE: ErrorSpec(ErrorCode.SANDBOX_UNVERIFIABLE, 503, "沙箱不可验证", "容器 CLI/daemon/权限/镜像任一不可用"),
    ErrorCode.REALSCAN_NOT_ESTABLISHED: ErrorSpec(ErrorCode.REALSCAN_NOT_ESTABLISHED, 409, "真扫不成立", "目标未响应或存在性/隔离/证据条件未满足"),
    ErrorCode.EVIDENCE_INTEGRITY: ErrorSpec(ErrorCode.EVIDENCE_INTEGRITY, 409, "证据不可信", "写入失败、摘要不一致、清洗命中或时间回拨"),
    ErrorCode.CREDENTIAL_RISK: ErrorSpec(ErrorCode.CREDENTIAL_RISK, 500, "凭据泄露风险", "输出含疑似凭据"),
    ErrorCode.CONFIG_FROZEN: ErrorSpec(ErrorCode.CONFIG_FROZEN, 409, "配置冻结", "冻结项变更需显式豁免记录"),
    ErrorCode.CONFIG_INVALID: ErrorSpec(ErrorCode.CONFIG_INVALID, 422, "配置变更非法", "路径未知、取值非法或缺少变更主体"),
    ErrorCode.SELFCHECK_LOCKED: ErrorSpec(ErrorCode.SELFCHECK_LOCKED, 409, "自检进行中", "锁被非陈旧持有"),
    ErrorCode.SELFCHECK_TIMEOUT: ErrorSpec(ErrorCode.SELFCHECK_TIMEOUT, 504, "检查项超时", "单项超过阈值"),
    ErrorCode.SELFCHECK_READONLY_VIOLATION: ErrorSpec(ErrorCode.SELFCHECK_READONLY_VIOLATION, 500, "只读违规", "执行前后摘要不一致或探针越界"),
    ErrorCode.SELFCHECK_REPORT_WRITE_FAILED: ErrorSpec(ErrorCode.SELFCHECK_REPORT_WRITE_FAILED, 500, "报告写入失败", "归档目录不可写"),
    ErrorCode.SELFCHECK_BASELINE_INVALID: ErrorSpec(ErrorCode.SELFCHECK_BASELINE_INVALID, 422, "基线不可用", "基线 JSON 不合法"),
    ErrorCode.SELFCHECK_MANUAL_PENDING: ErrorSpec(ErrorCode.SELFCHECK_MANUAL_PENDING, 422, "人工项未填", "人工输入缺失或未确认"),
    ErrorCode.UNAUTHORIZED: ErrorSpec(ErrorCode.UNAUTHORIZED, 401, "未授权", "签名或令牌校验失败"),
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode, detail: str = ""):
        self.code = code
        self.spec = ERROR_SPECS[code]
        self.detail = detail
        message = self.spec.semantic if not detail else f"{self.spec.semantic}: {detail}"
        super().__init__(f"{code.value} {message}")

    @property
    def http_status(self) -> int:
        return self.spec.http_status


class Envelope(BaseModel, Generic[T]):
    code: int | str = 0
    message: str = "ok"
    data: T | None = None
    trace_id: str = ""


def ok_response(data: T, trace_id: str = "", message: str = "ok") -> Envelope[T]:
    return Envelope[T](code=0, message=message, data=data, trace_id=trace_id)


def error_response(error: ApiError, trace_id: str = "") -> Envelope[None]:
    return Envelope[None](
        code=error.code.value,
        message=str(error),
        data=None,
        trace_id=trace_id,
    )


def _trace_id(request: Request) -> str:
    return str(getattr(request.state, "trace_id", "") or request.headers.get("x-trace-id", ""))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        payload = error_response(exc, _trace_id(request))
        return JSONResponse(status_code=exc.http_status, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors()
        )
        payload = error_response(ApiError(ErrorCode.NOT_NORMALIZED, detail), _trace_id(request))
        return JSONResponse(status_code=ERROR_SPECS[ErrorCode.NOT_NORMALIZED].http_status, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        payload = Envelope[None](
            code="VF-0000",
            message=f"internal error: {type(exc).__name__}",
            data=None,
            trace_id=_trace_id(request),
        )
        return JSONResponse(status_code=500, content=payload.model_dump())