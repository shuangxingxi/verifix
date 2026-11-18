from __future__ import annotations

import re
from dataclasses import dataclass

REDACTION = "[REDACTED-INSTRUCTION]"

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?i)(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules)"
            r"|忽略(之前|以上|先前|前面)(的)?(指令|提示|规则)"
        ),
    ),
    (
        "role_hijack",
        re.compile(r"(?i)you\s+are\s+now\s+(an?\s+)?(dan|developer|admin|root)|从现在起你是"),
    ),
    (
        "system_prompt_leak",
        re.compile(r"(?i)(reveal|print|show|repeat)\s+(your\s+)?system\s+prompt|输出系统提示词"),
    ),
    (
        "tool_injection",
        re.compile(r"(?i)(curl|wget)\s+https?://\S+\s*\|\s*(sh|bash)|;\s*(rm\s+-rf\s+/|chmod\s+777\s+/)"),
    ),
    (
        "secret_exfil",
        re.compile(
            r"(?i)(print|post|send|upload|exfiltrat\w*)\s+[^\n]{0,40}(secret|token|password|env|环境变量)"
            r"|VERIFIX_(WEBHOOK_SECRET|MODEL_PROVIDER)"
        ),
    ),
)


@dataclass(frozen=True)
class PromptSanitization:
    text: str
    hits: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not self.hits


def scan_untrusted_text(text: str) -> tuple[str, ...]:
    value = text or ""
    return tuple(name for name, pattern in RULES if pattern.search(value))


def sanitize_untrusted_text(text: str) -> PromptSanitization:
    value = text or ""
    hits = scan_untrusted_text(value)
    if not hits:
        return PromptSanitization(value, ())
    cleaned = value
    for _name, pattern in RULES:
        cleaned = pattern.sub(REDACTION, cleaned)
    return PromptSanitization(cleaned, hits)