"""自检测试夹具：最小仓库、真实摘要证据包、人工输入样例。

所有夹具均不联网、不依赖 Docker / npm。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.realscan.evidence import EvidenceInput, EvidencePackWriter, VerificationSource  # noqa: E402

README = """# Fixture Repo

## 指标

- 覆盖率 54.5%（全模块口径），判定函数口径 62.0%，未达标，n=6
- 全量回归 690 用例，n=6
- 缺陷 3 类
- 合并到 `release/auto`，永不并 `main`
- M9 24h 连续运行：未验证
- 演示入口：https://demo.example.com/verifix

## 8. 复现

1. 运行 `python scripts/smoke_m0.py`
"""

M12 = """# M12 收尾

## 4. 可声称 / 不可声称

**可声称**

- 690 用例、功能性失败 0
- 缺陷 3 类静态与动态链路可跑通

**不可声称**

- 云上已验证 / 已发布
- 真实 24h 连续运行

## 7. 报告索引

| 报告 | 内容 |
|---|---|
| m11 | 覆盖率 54.5%，n=6 |
"""

DELIVERABLES = """# 方案

## 0 一页速览

- 覆盖率 54.5%（全模块口径），判定函数口径 62.0%，未达标，n=6
- 全量回归 690 用例，n=6
- 缺陷 3 类
- 合并到 `release/auto`，永不并 `main`

## 2 创新性解读

创新点说明。

## 3 系统设计

方案设计说明。

## 5 数据集与处理

数据集说明。

## 6 关键代码解读

关键代码说明。

## 7 可量化指标

指标说明。

## 4 CodeArts 使用设计

CodeArts 说明。

## 8 部署与演示

部署说明。

## 9 团队分工与排期

分工说明。

正文长度补足，确保材料可打开且非占位。这一行用于把正文长度提高到阈值以上，避免 D5-4 因过短而误判。
为了稳定超过最小长度阈值，这里继续补充交付材料正文：方案设计、数据集处理、关键代码解读、可量化指标、
CodeArts 使用说明、部署与演示、团队分工与排期均在本文件对应章节中给出说明，且不包含任何独立占位行。
补充说明：本段仅用于夹具长度校验，不代表任何真实指标、能力范围或对外声称；真实交付材料以仓库内
`deliverables/CodeArts方案.md` 为准。夹具中的百分比、用例数、缺陷类别数与支出口径均用于验证
口径抽取逻辑，测试结束后不进入任何归档或对外材料。再次补充若干说明文字，使正文长度稳定超过
最小阈值，避免因夹具过短导致 D5-4 误判为占位或空正文。此处重复列举章节名称以增加长度：
方案设计、数据集与处理、关键代码解读、可量化指标、CodeArts 使用说明、部署与演示、团队分工与排期。
"""

PRESENTATION = """# 演示材料

- 覆盖率 54.5%（全模块口径），判定函数口径 62.0%，未达标，n=6
- 全量回归 690 用例，n=6
- 缺陷 3 类
- 合并到 `release/auto`，永不并 `main`
- 演示入口：https://demo.example.com/verifix
"""

MANUAL = """# 自检人工输入

### CLM-001
- 声称：690 用例、功能性失败 0
- 载体：README.md §指标
- 真实来源：python -m unittest discover -s backend/tests
- 级别：L3
- 证据：无
- 样本量：6
- 确认：是

### CLM-002
- 声称：命中率 99%
- 载体：README.md §指标
- 真实来源：待定
- 级别：L4
- 证据：无
- 样本量：3
- 确认：待确认
"""


def write_repo(
    root: Path,
    *,
    with_evidence: bool = True,
    with_manual: bool = True,
    with_demo: bool = True,
) -> dict[str, object]:
    root = Path(root)
    files = {
        "README.md": README,
        "docs/devlog/m12-closure-and-blockers.md": M12,
        "docs/devlog/m11-coverage-report.md": "# M11\n\n- 覆盖率 54.5%（全模块口径），判定函数口径 62.0%，未达标，n=6\n",
        "deliverables/CodeArts方案.md": DELIVERABLES,
        "backend/tests/dummy_test.py": "import unittest\n\n\nclass Dummy(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
        "frontend/src/app.ts": "export const ok = true;\n",
    }
    if with_demo:
        files["deliverables/演示材料.pptx"] = "placeholder"
        files["deliverables/demo.mp4"] = "placeholder"
    if with_manual:
        files["docs/devlog/selfcheck-manual.md"] = MANUAL
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    evidence_id = None
    if with_evidence:
        evidence_id = _write_evidence(root)
    return {"root": root, "evidence_id": evidence_id}


def _write_evidence(root: Path) -> str:
    evidence_root = root / ".evidence" / "sandbox-realscan"
    evidence_root.mkdir(parents=True, exist_ok=True)
    writer = EvidencePackWriter(evidence_root)
    pack = writer.write(
        "VER",
        EvidenceInput(
            commands=["python -m unittest discover -s backend/tests"],
            runtime_facts={"image_id": "sha256:fixture", "exec_domain": "host"},
            raw_output="Ran 1 test\nOK\n",
            verification_source=VerificationSource.REAL_EXECUTION,
            files={
                "runtime_facts.json": json.dumps(
                    {"image_id": "sha256:fixture", "exec_domain": "host"}, sort_keys=True
                )
            },
        ),
    )
    return pack.evidence_id


def reference_line(evidence_id: str) -> str:
    return f"- 证据：`.evidence/sandbox-realscan/{evidence_id}`"


def append_document(root: Path, relative: str, text: str) -> None:
    target = Path(root) / relative
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    target.write_text(existing + "\n" + text + "\n", encoding="utf-8")