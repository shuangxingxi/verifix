"""D3 证据完整性检查项（7 项）。全组只读，禁止调用任何证据写接口。"""

from __future__ import annotations

import json
from pathlib import Path

from app.realscan.evidence import (
    DIGEST_NAME,
    HISTORY_BASELINE,
    MANIFEST_NAME,
    EvidencePackWriter,
    _sha256_bytes,
    _tree_digest,
    verify_history_digests,
)

from ..loaders import (
    build_reference_map,
    extract_evidence_ids,
    load_carriers,
    load_documents,
    load_claimable_items,
    load_evidence_index,
)
from ..models import (
    CheckResult,
    CheckSpec,
    ClaimRecord,
    Dimension,
    EvidenceEntry,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)


def _inspected(ctx: object) -> tuple[list[EvidenceEntry], list[str]]:
    loaded = load_evidence_index(ctx.root)
    entries: list[EvidenceEntry] = []
    references = build_reference_map(load_documents(ctx))
    for entry in loaded.entries:
        pack = ctx.path(entry.path)
        entry.referenced_by = references.get(entry.evidence_id, [])
        if not pack.is_dir():
            entry.integrity_ok = False
            entry.mismatches = ["missing:pack"]
            entries.append(entry)
            continue
        report = EvidencePackWriter(pack.parent).verify(entry.evidence_id)
        entry.integrity_ok = report.ok
        entry.mismatches = list(report.mismatches)
        manifest_path = pack / MANIFEST_NAME
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                entry.manifest_sha256 = str(manifest.get("sha256", ""))
            except (OSError, json.JSONDecodeError):
                entry.manifest_sha256 = ""
        entry.recomputed_sha256 = _tree_digest(pack)
        entries.append(entry)
    ctx.artifacts["evidence"] = entries
    return entries, loaded.errors


def _d3_1(ctx: object) -> CheckResult:
    items = load_claimable_items(ctx)
    loaded = load_evidence_index(ctx.root)
    if loaded.errors:
        return build_result(
            _SPECS[0], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(loaded.errors),
        )
    if not items:
        return build_result(
            _SPECS[0], Status.BLOCKED, sub_reason="MISSING",
            output_summary="未在收尾文档 §4 抽取到可声称条目。",
        )
    known = {entry.evidence_id for entry in loaded.entries}
    claims: list[ClaimRecord] = []
    missing: list[str] = []
    for index, text in enumerate(items, start=1):
        references = extract_evidence_ids(text)
        claims.append(
            ClaimRecord(
                claim_id=f"CLM-{index:03d}",
                text=text,
                carrier="docs/devlog/m12-closure-and-blockers.md",
                location="§4 可声称",
                claim_type="能力型",
                evidence_refs=references,
            )
        )
        if not references or any(reference not in known for reference in references):
            missing.append(text)
    ctx.artifacts["claims"] = claims
    if missing:
        return build_result(
            _SPECS[0], Status.BLOCKED, sub_reason="CLAIM_WITHOUT_EVIDENCE",
            output_summary=(
                f"{len(items)} 条可声称中 {len(missing)} 条未给出可解析证据标识："
                + "；".join(missing[:3])
            ),
            evidence_refs=sorted(known)[:5],
        )
    return build_result(
        _SPECS[0], Status.PASS,
        output_summary=f"{len(items)} 条可声称均定位到证据且摘要可校验。",
        evidence_refs=sorted(known)[:5],
    )


def _d3_2(ctx: object) -> CheckResult:
    loaded = load_evidence_index(ctx.root)
    if loaded.errors:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(loaded.errors),
        )
    references = build_reference_map(load_documents(ctx))
    known = {entry.evidence_id for entry in loaded.entries}
    if not known:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="MISSING", output_summary="证据索引为空。"
        )
    orphans = sorted(known - set(references))
    rate = len(orphans) / len(known)
    summary = f"证据包 {len(known)} 个，孤儿 {len(orphans)} 个，孤儿率 {rate:.1%}（阈值 10%）。"
    if rate <= ctx.thresholds.orphan_rate:
        return build_result(_SPECS[1], Status.PASS, output_summary=summary)
    return build_result(
        _SPECS[1], Status.WARNING, sub_reason="ORPHAN_RATE_EXCEEDED",
        output_summary=summary + " 孤儿：" + ", ".join(orphans[:5]),
        evidence_refs=orphans[:5],
    )


def _d3_3(ctx: object) -> CheckResult:
    entries, errors = _inspected(ctx)
    if errors:
        return build_result(
            _SPECS[2], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(errors),
        )
    if not entries:
        return build_result(_SPECS[2], Status.BLOCKED, sub_reason="MISSING", output_summary="无可校验证据包。")
    missing: list[str] = []
    tampered: list[str] = []
    for entry in entries:
        for mismatch in entry.mismatches:
            if mismatch.startswith("missing:") or mismatch in {DIGEST_NAME, MANIFEST_NAME, "manifest_invalid"}:
                missing.append(f"{entry.evidence_id}:{mismatch}")
            elif mismatch in {"manifest_digest"} or mismatch.startswith("digest:"):
                tampered.append(f"{entry.evidence_id}:{mismatch}")
    if missing or tampered:
        reason = "TAMPERED" if tampered else "MISSING"
        return build_result(
            _SPECS[2], Status.BLOCKED, sub_reason=reason,
            output_summary=(
                f"逐文件摘要校验未通过：篡改 {len(tampered)} 处，缺失 {len(missing)} 处；"
                + "；".join((tampered + missing)[:5])
            ),
        )
    return build_result(
        _SPECS[2], Status.PASS,
        output_summary=f"{len(entries)} 个证据包逐文件摘要 100% 一致。",
        evidence_refs=[entry.evidence_id for entry in entries][:5],
    )


def _d3_4(ctx: object) -> CheckResult:
    entries, errors = _inspected(ctx)
    if errors:
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(errors),
        )
    mismatched: list[str] = []
    for entry in entries:
        triple = {entry.index_sha256, entry.manifest_sha256, entry.recomputed_sha256}
        if len(triple) != 1 or not all(triple):
            mismatched.append(
                f"{entry.evidence_id}（索引 {entry.index_sha256[:8] or '空'} / "
                f"清单 {entry.manifest_sha256[:8] or '空'} / 重算 {entry.recomputed_sha256[:8] or '空'}）"
            )
    if mismatched:
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="DIGEST_MISMATCH",
            output_summary=f"索引/清单/重算三方摘要不一致 {len(mismatched)} 处：" + "；".join(mismatched[:5]),
        )
    return build_result(
        _SPECS[3], Status.PASS,
        output_summary=f"{len(entries)} 个证据包索引、清单、重算摘要三方一致。",
    )


def _d3_5(ctx: object) -> CheckResult:
    loaded = load_evidence_index(ctx.root)
    if loaded.errors:
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(loaded.errors),
        )
    references = build_reference_map(load_documents(ctx))
    known = {entry.evidence_id for entry in loaded.entries}
    if not references:
        return build_result(
            _SPECS[4], Status.UNVERIFIED, sub_reason="NO_REFERENCE",
            output_summary="全部文档中未抽取到任何证据标识，本项无可比对输入（不得判通过）。",
        )
    unknown = sorted(reference for reference in references if reference not in known)
    if unknown:
        locations = [references[item][0] for item in unknown[:3]]
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="UNRESOLVED_REFERENCE",
            output_summary=(
                f"{len(unknown)} 个引用无法在索引中唯一定位："
                + "；".join(f"{item}（{location}）" for item, location in zip(unknown[:3], locations))
            ),
        )
    return build_result(
        _SPECS[4], Status.PASS,
        output_summary=f"{len(references)} 个证据引用全部可在索引中唯一定位。",
    )


def _d3_6(ctx: object) -> CheckResult:
    entries, errors = _inspected(ctx)
    if errors:
        return build_result(
            _SPECS[5], Status.BLOCKED, sub_reason="EVIDENCE_UNREADABLE",
            output_summary="；".join(errors),
        )
    incomplete: list[str] = []
    for entry in entries:
        pack = ctx.path(entry.path)
        if not pack.is_dir():
            incomplete.append(f"{entry.evidence_id}:缺包")
            continue
        missing = []
        if not (pack / "commands.txt").is_file():
            missing.append("commands.txt")
        if not (pack / "runtime_facts.json").is_file():
            missing.append("runtime_facts.json")
        if not (pack / DIGEST_NAME).is_file():
            missing.append(DIGEST_NAME)
        raw = pack / "raw"
        if not raw.is_dir() or not any(item.is_file() for item in raw.rglob("*")):
            missing.append("raw/")
        if missing:
            incomplete.append(f"{entry.evidence_id}:缺 {','.join(missing)}")
    if incomplete:
        return build_result(
            _SPECS[5], Status.BLOCKED, sub_reason="EVIDENCE_INCOMPLETE",
            output_summary=f"{len(incomplete)} 个证据包四类内容不完备：" + "；".join(incomplete[:5]),
        )
    return build_result(
        _SPECS[5], Status.PASS,
        output_summary=f"{len(entries)} 个证据包四类内容齐备（commands/raw/runtime_facts/摘要）。",
    )


def _d3_7(ctx: object) -> CheckResult:
    violations = verify_history_digests(ctx.root)
    detail: list[str] = list(violations)
    archive_checked = 0
    index_path = ctx.output_dir / "index.json"
    if index_path.is_file():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            detail.append("index.json 不可解析")
            payload = {}
        for item in payload.get("entries") or []:
            if not isinstance(item, dict):
                continue
            run_id = str(item.get("run_id", ""))
            archive = ctx.output_dir / run_id
            report = archive / "report.md"
            payload_path = archive / "selfcheck.json"
            if not report.is_file() or not payload_path.is_file():
                detail.append(f"{run_id}:归档缺失")
                continue
            archive_checked += 1
            if _sha256_bytes(report.read_bytes()) != item.get("report_sha256"):
                detail.append(f"{run_id}:report.md 被改写")
            if _sha256_bytes(payload_path.read_bytes()) != item.get("json_sha256"):
                detail.append(f"{run_id}:selfcheck.json 被改写")
    if detail:
        return build_result(
            _SPECS[6], Status.BLOCKED, sub_reason="HISTORY_TAMPERED",
            output_summary=f"历史报告/归档摘要变化 {len(detail)} 处：" + "；".join(detail[:5]),
        )
    return build_result(
        _SPECS[6], Status.PASS,
        output_summary=(
            f"历史基线 {len(HISTORY_BASELINE)} 项摘要不变；"
            f"已登记归档 {archive_checked} 个摘要不变。"
        ),
    )


_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec("D3-1", "声称→证据映射", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "每条声称 ≥1 个证据且摘要通过", handler=_d3_1),
    CheckSpec("D3-2", "孤儿证据率", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "孤儿率 ≤10% 通过；>10% 警告（不删除）", handler=_d3_2),
    CheckSpec("D3-3", "逐文件摘要一致性", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "EVIDENCE.sha256 逐行 100% 一致", handler=_d3_3),
    CheckSpec("D3-4", "索引包摘要一致性", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "索引/清单/重算三方摘要一致", handler=_d3_4),
    CheckSpec("D3-5", "引用可解析", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "载体中证据标识 100% 可唯一定位", handler=_d3_5),
    CheckSpec("D3-6", "证据包四类内容完备", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "commands/raw/runtime_facts/摘要四类齐备", handler=_d3_6),
    CheckSpec("D3-7", "历史报告只读性", Dimension.EVIDENCE, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "历史基线与已登记归档摘要全部不变", handler=_d3_7),
)

SPECS = _SPECS