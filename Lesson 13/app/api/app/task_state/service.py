"""Сервис применения переходов и сборки снимка задачи."""

from __future__ import annotations

import sqlite3
from typing import Any

from .domain import (
    Action,
    ActiveTaskExists,
    Stage,
    TaskError,
    TaskEvent,
    TaskNotFound,
    TaskState,
    VersionConflict,
    plan_steps,
)
from .machine import TaskStateMachine
from .repository import TaskRepository
from .sqlite_repository import SQLiteTaskRepository


class TaskService:
    def __init__(
        self,
        repository: TaskRepository,
        machine: TaskStateMachine | None = None,
    ) -> None:
        self.repository = repository
        self.machine = machine or TaskStateMachine()

    def snapshot(self, task: TaskState) -> dict[str, Any]:
        data = task.to_dict()
        data["possible_actions"] = self.machine.possible_actions(task)
        data["available_actions"] = self.machine.available_actions(task)
        steps = self.repository.steps(task.task_id)
        if not steps and task.stage is Stage.EXECUTION and task.plan_text:
            self.repository.replace_steps(
                task.task_id, plan_steps(task.plan_text)
            )
            steps = self.repository.steps(task.task_id)
        data["steps"] = steps
        done = sum(1 for step in steps if step["status"] == "done")
        data["execution_progress"] = {
            "done": done,
            "total": len(steps),
            "current": next(
                (
                    step["title"]
                    for step in steps
                    if step["status"] in {"pending", "running", "failed"}
                ),
                None,
            ),
        }
        return data

    def create(self, session_id: str, goal: str) -> dict[str, Any]:
        goal = goal.strip()
        if not goal:
            raise TaskError(
                "validation_error",
                "Цель задачи не может быть пустой.",
                status_code=422,
            )

        existing = self.repository.get_by_session(session_id)
        if existing is not None and existing.stage is not Stage.DONE:
            self.log_agent(
                session_id,
                "task",
                "warning",
                "Попытка создать задачу при уже активной задаче",
                task_id=existing.task_id,
            )
            raise ActiveTaskExists(existing)

        task = TaskState.new(session_id, goal)
        try:
            self.repository.create(task)
        except sqlite3.IntegrityError:
            current = self.repository.get_by_session(session_id)
            if current is not None:
                self.log_agent(
                    session_id,
                    "task",
                    "warning",
                    "Конфликт при создании задачи",
                    task_id=current.task_id,
                )
                raise ActiveTaskExists(current) from None
            raise
        self.log_agent(
            session_id,
            "task",
            "info",
            f"Задача создана: {goal}",
            task_id=task.task_id,
        )
        return self.snapshot(task)

    def get(self, session_id: str) -> dict[str, Any]:
        task = self.repository.get_by_session(session_id)
        if task is None:
            raise TaskNotFound()
        return self.snapshot(task)

    def transition(
        self,
        session_id: str,
        action: Action | str,
        *,
        version: int,
        reason: str | None = None,
        plan_text: str | None = None,
    ) -> dict[str, Any]:
        try:
            action_enum = action if isinstance(action, Action) else Action(action)
        except ValueError:
            raise TaskError(
                "unknown_action",
                f"Неизвестное действие: {action!r}",
                status_code=422,
            ) from None

        task = self.repository.get_by_session(session_id)
        if task is None:
            self.log_agent(session_id, "task", "error", "Задача не найдена")
            raise TaskNotFound()

        if version != task.version:
            error = VersionConflict(task)
            self._log_rejection(task, action_enum, reason, error)
            self.log_agent(
                session_id,
                "transition",
                "error",
                f"Конфликт версии для {action_enum.value}",
                task_id=task.task_id,
                details={"expected": version, "actual": task.version},
            )
            raise error

        if action_enum is Action.COMPLETE_EXECUTION:
            steps = self.repository.steps(task.task_id)
            unfinished = [
                step for step in steps if step["status"] != "done"
            ]
            if unfinished:
                raise TaskError(
                    "steps_unfinished",
                    "Сначала выполните все шаги плана командой `/step`.",
                    status_code=409,
                    task=task,
                    action=action_enum.value,
                    possible_actions=self.machine.possible_actions(task),
                    available_actions=self.machine.available_actions(task),
                )

        try:
            new_task = self.machine.apply(
                task,
                action_enum,
                reason=reason,
                plan_text=plan_text,
            )
        except TaskError as error:
            self._log_rejection(task, action_enum, reason, error)
            self.log_agent(
                session_id,
                "transition",
                "error",
                f"{action_enum.value}: {error.message}",
                task_id=task.task_id,
                details={"code": error.code},
            )
            raise
        except sqlite3.IntegrityError as error:
            current = self.repository.get_by_session(session_id) or task
            failure = VersionConflict(current)
            self._log_rejection(current, action_enum, reason, failure)
            raise failure from error

        if new_task is task:
            self.log_agent(
                session_id,
                "transition",
                "info",
                f"Идемпотентное действие: {action_enum.value}",
                task_id=task.task_id,
            )
            return self.snapshot(task)

        event = TaskEvent.from_transition(task, action_enum, new_task, reason)
        try:
            self.repository.apply(task.task_id, task.version, new_task, event)
        except TaskError as error:
            self.log_agent(
                session_id,
                "transition",
                "error",
                f"{action_enum.value}: {error.message}",
                task_id=task.task_id,
                details={"code": error.code},
            )
            raise
        except sqlite3.IntegrityError as error:
            current = self.repository.get_by_session(session_id) or task
            failure = VersionConflict(current)
            self._log_rejection(current, action_enum, reason, failure)
            raise failure from error

        if action_enum in {Action.START_EXECUTION, Action.REWORK}:
            self.repository.replace_steps(
                new_task.task_id,
                plan_steps(new_task.plan_text),
            )
        self.log_agent(
            session_id,
            "transition",
            "info",
            f"{action_enum.value}: {task.stage.value} → {new_task.stage.value}",
            task_id=task.task_id,
            details={"version": new_task.version},
        )
        return self.snapshot(new_task)

    def pause(self, session_id: str, *, version: int) -> dict[str, Any]:
        return self.transition(
            session_id,
            Action.PAUSE,
            version=version,
            reason="Пауза",
        )

    def resume(self, session_id: str, *, version: int) -> dict[str, Any]:
        return self.transition(
            session_id,
            Action.RESUME,
            version=version,
            reason="Продолжение",
        )

    def history(self, session_id: str) -> list[dict[str, Any]]:
        task = self.repository.get_by_session(session_id)
        if task is None:
            raise TaskNotFound()
        return [self._event_dict(event) for event in self.repository.history(task.task_id)]

    def log_agent(
        self,
        session_id: str,
        kind: str,
        level: str,
        message: str,
        *,
        task_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.repository.log_agent_event(
            session_id=session_id,
            task_id=task_id,
            kind=kind,
            level=level,
            message=message,
            details=details,
        )

    def agent_log(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.repository.agent_log(session_id, limit=limit)

    def save_chat_message(
        self,
        session_id: str,
        *,
        task_id: str | None,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> None:
        self.repository.save_chat_message(
            session_id=session_id,
            task_id=task_id,
            role=role,
            content=content,
            meta=meta,
        )

    def chat_history(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return self.repository.chat_history(
            session_id,
            task_id=task_id,
            limit=limit,
        )

    def claim_next_step(self, session_id: str) -> dict[str, Any]:
        task = self.repository.get_by_session(session_id)
        if task is None:
            raise TaskNotFound()
        if task.paused:
            raise TaskError("task_paused", "Задача на паузе.", status_code=409)
        if task.stage is not Stage.EXECUTION or task.execution_complete:
            raise TaskError(
                "step_not_allowed",
                "Шаги выполняются только на активном этапе реализации.",
                status_code=409,
                task=task,
            )
        steps = self.repository.steps(task.task_id)
        if not steps and task.plan_text:
            self.repository.replace_steps(task.task_id, plan_steps(task.plan_text))
            steps = self.repository.steps(task.task_id)
        next_step = next(
            (step for step in steps if step["status"] in {"pending", "failed"}),
            None,
        )
        if next_step is None:
            raise TaskError(
                "steps_done",
                "Все шаги плана уже выполнены; завершите реализацию командой `/complete`.",
                status_code=409,
                task=task,
            )
        claimed = self.repository.start_step(task.task_id, next_step["step_id"])
        if claimed is None:
            raise TaskError(
                "step_conflict",
                "Шаг уже выполняется другим запросом.",
                status_code=409,
                task=task,
            )
        return claimed

    def finish_step(
        self,
        task_id: str,
        step_id: int,
        *,
        status: str,
        result: str,
    ) -> None:
        self.repository.finish_step(
            task_id,
            step_id,
            status=status,
            result=result,
        )

    def steps(self, session_id: str) -> list[dict[str, Any]]:
        task = self.repository.get_by_session(session_id)
        if task is None:
            raise TaskNotFound()
        return self.repository.steps(task.task_id)

    def clear_tasks(self) -> dict[str, int]:
        return self.repository.clear_tasks()

    def clear_chat(self) -> dict[str, int]:
        return self.repository.clear_chat()

    def _log_rejection(
        self,
        task: TaskState,
        action: Action,
        reason: str | None,
        error: TaskError,
    ) -> None:
        event = TaskEvent.rejection(task, action, reason, error.code)
        self.repository.log_event(event)

    @staticmethod
    def _event_dict(event: TaskEvent) -> dict[str, Any]:
        return {
            "task_id": event.task_id,
            "action": event.action,
            "from_stage": event.from_stage,
            "to_stage": event.to_stage,
            "reason": event.reason,
            "success": event.success,
            "error_code": event.error_code,
            "version_before": event.version_before,
            "version_after": event.version_after,
            "created_at": event.created_at,
        }


def build_default_service() -> TaskService:
    import os
    from pathlib import Path

    path = os.getenv("TASK_DB_PATH", "/srv/data/lesson13.db")
    return TaskService(SQLiteTaskRepository(Path(path)))
