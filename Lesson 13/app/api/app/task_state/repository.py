"""Порт хранилища состояний задачи."""

from __future__ import annotations

from typing import Protocol

from .domain import TaskEvent, TaskState


class TaskRepository(Protocol):
    def create(self, task: TaskState) -> TaskState: ...
    def get_by_session(self, session_id: str) -> TaskState | None: ...
    def apply(
        self,
        task_id: str,
        expected_version: int,
        new_state: TaskState,
        event: TaskEvent,
    ) -> TaskState: ...
    def log_event(self, event: TaskEvent) -> None: ...
    def history(self, task_id: str) -> list[TaskEvent]: ...
    def log_agent_event(
        self,
        *,
        session_id: str,
        task_id: str | None,
        kind: str,
        level: str,
        message: str,
        details: dict | None = None,
    ) -> None: ...
    def agent_log(self, session_id: str, limit: int = 200) -> list[dict]: ...
    def save_chat_message(
        self,
        *,
        session_id: str,
        task_id: str | None,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> None: ...
    def replace_steps(self, task_id: str, titles: list[str]) -> None: ...
    def steps(self, task_id: str) -> list[dict]: ...
    def start_step(self, task_id: str, step_id: int) -> dict | None: ...
    def finish_step(
        self, task_id: str, step_id: int, *, status: str, result: str
    ) -> None: ...
    def chat_history(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]: ...
