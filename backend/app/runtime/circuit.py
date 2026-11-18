from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.enums import CircuitStatus, DefectClass
from app.domain.models import BlacklistEntry, CircuitState

DEFAULT_FAIL_STREAK = 3
DEFAULT_BLACKLIST_TTL_HOURS = 72


@dataclass(frozen=True)
class CircuitDecision:
    allowed: bool
    reason: str
    code: str


class CircuitBreaker:
    def __init__(
        self,
        store,
        fail_streak: int = DEFAULT_FAIL_STREAK,
        blacklist_ttl_hours: int = DEFAULT_BLACKLIST_TTL_HOURS,
        clock=time.monotonic,
    ):
        self.store = store
        self.fail_streak = max(1, fail_streak)
        self.blacklist_ttl_hours = max(1, blacklist_ttl_hours)
        self.clock = clock
        self._paused = False
        self._pause_reason = ""

    def state_for(self, defect_class: DefectClass) -> CircuitState:
        return self.store.circuit_for(defect_class)

    def check(self, defect_class: DefectClass, fingerprint: str) -> CircuitDecision:
        if self._paused:
            return CircuitDecision(False, f"自动处置已暂停：{self._pause_reason}", "VF-6001")
        state = self.state_for(defect_class)
        if state.state is CircuitStatus.OPEN:
            return CircuitDecision(False, f"{defect_class.value} 已熔断，拒绝自动修复", "VF-6001")
        if self.is_blacklisted(fingerprint):
            return CircuitDecision(False, "失败指纹在 7 天黑名单内，跳过自动处置", "VF-6002")
        return CircuitDecision(True, "", "")

    def record_success(self, defect_class: DefectClass) -> CircuitState:
        state = self.state_for(defect_class)
        if state.fail_streak or state.state is not CircuitStatus.CLOSED:
            state = state.model_copy(update={"fail_streak": 0, "state": CircuitStatus.CLOSED, "opened_at": None})
            self.store.save_circuit(state)
        return state

    def record_failure(self, defect_class: DefectClass, fingerprint: str) -> CircuitState:
        state = self.state_for(defect_class)
        streak = state.fail_streak + 1
        now = datetime.now(timezone.utc)
        entries = list(state.blacklist_entries)
        entries.append(
            BlacklistEntry(
                fingerprint=fingerprint,
                failed_at=now,
                expires_at=now + timedelta(hours=self.blacklist_ttl_hours),
            )
        )
        opened = streak >= self.fail_streak
        updated = state.model_copy(
            update={
                "fail_streak": streak,
                "state": CircuitStatus.OPEN if opened else state.state,
                "opened_at": now if opened else state.opened_at,
                "blacklist_entries": entries,
            }
        )
        self.store.save_circuit(updated)
        return updated

    def is_blacklisted(self, fingerprint: str) -> bool:
        now = datetime.now(timezone.utc)
        for state in self.store.circuits.values():
            for entry in state.blacklist_entries:
                if entry.fingerprint == fingerprint and entry.expires_at > now:
                    return True
        return False

    def reset(self, defect_class: DefectClass, actor: str, reason: str) -> CircuitState:
        del actor, reason
        state = self.state_for(defect_class)
        updated = state.model_copy(update={"fail_streak": 0, "state": CircuitStatus.CLOSED, "opened_at": None})
        self.store.save_circuit(updated)
        return updated

    def pause(self, actor: str, reason: str) -> None:
        del actor
        self._paused = True
        self._pause_reason = reason

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = ""

    def is_paused(self) -> bool:
        return self._paused

    def pause_reason(self) -> str:
        return self._pause_reason