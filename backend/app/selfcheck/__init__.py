"""M13 自检框架（selfcheck_harness）。

设计依据：`.codeartsdoer/specs/selfcheck_harness/design.md`。
本包只诊断、定级与排序，不修复被检问题、不补造证据、不代填人工判定。
"""

from __future__ import annotations

__all__ = ["models", "registry", "context", "probes", "runner", "baseline", "loaders", "report", "manual"]