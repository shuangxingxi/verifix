from __future__ import annotations

from dataclasses import dataclass

from app.realscan.models import DefaultAdoption
from app.runtime.exec_domain import ExecDomain

CONTAINER_DOMAINS = frozenset({ExecDomain.RUNTIME_ROOT, ExecDomain.CONTAINER_EXEC})

@dataclass(frozen=True)
class ConflictDisposition:
    k_id: str
    disposition: str
    landing: str
    evidence_hint: str


CONFLICT_DISPOSITIONS = (
    ConflictDisposition("K-01", "容器身份结论作为对外口径，宿主域结论降为过程记录", "DES-ISO-06 / T-ISO-06", "ISO-*/records/isolation.json"),
    ConflictDisposition("K-02", "保持故障关闭，新增 EXEC_DOMAIN_MISMATCH 分类，不放行", "DES-ISO-04 / T-ISO-04", "审计中执行域不匹配记录"),
    ConflictDisposition("K-03", "改为挂载面裁剪，区分 PATH_NOT_EXIST 与 PERMISSION_DENIED", "DES-ISO-02/03", "ISO-*/raw/iso_stdout.jsonl"),
    ConflictDisposition("K-04", "补测 P4-05 超时用例，未执行维持 UNVERIFIED", "DES-SBX-14 / T-SBX-14", "VER-*/raw/p4-05.log"),
    ConflictDisposition("K-05", "重开受影响的未实测条目，旧结论保留为历史", "DES-EVD-07 / T-BASE-02", "sandbox-realscan-index 差异表"),
    ConflictDisposition("K-06", "M1 的 10/10 标记 RECORDED_STUB，不计入真扫分母", "DES-SCAN-14 / T-SCAN-14", "SCAN-*/records/scan.json"),
    ConflictDisposition("K-07", "真扫默认 15/15 全量，子集必须声明未覆盖类别", "DES-SCAN-12 / T-SCAN-12", "SCAN-*/records/scan.json scope"),
    ConflictDisposition("K-08", "同容器回环满足禁网与可达，不放行网络", "DES-SCAN-20 / T-SCAN-20", "SCAN-*/raw/scan_stdout.jsonl"),
    ConflictDisposition("K-09", "证据包继续携带容器层与云上不可外推的边界声明", "DES-EVD-05 / T-EVD-05", "*/boundary.json"),
    ConflictDisposition("K-10", "新增验证沿用 unittest，镜像内 pytest 不作为项目依赖", "DES-CFG-04 / T-CFG-04", "全量回归记录"),
)


_DEFAULT_VALUES: dict[str, str] = {
    "O-01": "10 judgement classes cover 11 policy keys",
    "O-02": "synthetic .git fixture with mount trimming",
    "O-03": "local alias allowed with registered image id",
    "O-04": "cli and evidence only, no api routes added",
    "O-05": "runtime flask independent, C01 static only",
    "O-06": "host fallback enabled but marked REAL_LOCAL",
    "Q-01": "runtime root identity",
    "Q-02": "local build image with image id",
    "Q-03": "build time egress only, runtime none",
    "Q-04": "dynamic port allocation",
    "Q-05": "full scope 15 items",
    "Q-06": "host fallback accepted but excluded from sandbox evidence",
    "Q-07": "p4-05 timeout retest mandatory",
    "Q-08": "dual track probes, container domain publishable",
    "Q-09": "write new evidence root only",
    "Q-10": "cloud credential missing placeholder",
}


def default_adoptions() -> list[DefaultAdoption]:
    return [
        DefaultAdoption(q_id=key, value=value, source="SPEC_DEFAULT", pending=True)
        for key, value in sorted(_DEFAULT_VALUES.items())
    ]


def is_container_conclusion(exec_domain: ExecDomain, source_kind: str, verification_source: str) -> bool:
    return (
        exec_domain in CONTAINER_DOMAINS
        and source_kind == "REAL_CONTAINER"
        and verification_source == "REAL_EXECUTION"
    )