from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueueTask:
    key: str
    task_type: str
    payload_ref: str
    attempts: int = 0
    status: str = "PENDING"


@dataclass
class TaskQueue:
    max_attempts: int = 3
    tasks: dict[str, QueueTask] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    dead_letters: list[QueueTask] = field(default_factory=list)

    def enqueue(self, key: str, task_type: str, payload_ref: str) -> QueueTask:
        task = self.tasks.get(key)
        if task is not None and task.status != "DONE":
            return task
        task = QueueTask(key=key, task_type=task_type, payload_ref=payload_ref)
        self.tasks[key] = task
        self.order.append(key)
        return task

    def consume(self, count: int = 1) -> list[QueueTask]:
        claimed: list[QueueTask] = []
        for key in list(self.order):
            if len(claimed) >= count:
                break
            task = self.tasks.get(key)
            if task is None or task.status != "PENDING":
                continue
            task.status = "RUNNING"
            claimed.append(task)
        return claimed

    def ack(self, key: str) -> None:
        task = self.tasks.get(key)
        if task is not None:
            task.status = "DONE"
            if key in self.order:
                self.order.remove(key)

    def retry(self, key: str, reason: str = "") -> QueueTask | None:
        task = self.tasks.get(key)
        if task is None:
            return None
        task.attempts += 1
        del reason
        if task.attempts >= self.max_attempts:
            task.status = "FAILED"
            self.dead_letters.append(task)
            if key in self.order:
                self.order.remove(key)
            return task
        task.status = "PENDING"
        return task

    def queued(self) -> int:
        return sum(1 for task in self.tasks.values() if task.status in {"PENDING", "RUNNING"})

    def pending(self) -> int:
        return sum(1 for task in self.tasks.values() if task.status == "PENDING")