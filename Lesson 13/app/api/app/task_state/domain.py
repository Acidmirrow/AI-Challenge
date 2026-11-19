"""Доменные модели конечного автомата задачи."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Stage(str, Enum):
    PLANNING = "planning"
    EXECUTION = "execution"
    VALIDATION = "validation"
    DONE = "done"


class Action(str, Enum):
    SUBMIT_PLAN = "submit_plan"
    APPROVE_PLAN = "approve_plan"
    START_EXECUTION = "start_execution"
    COMPLETE_EXECUTION = "complete_execution"
    START_VALIDATION = "start_validation"
    PASS_VALIDATION = "pass_validation"
    FAIL_VALIDATION = "fail_validation"
    FINISH = "finish"
    REWORK = "rework"
    PAUSE = "pause"
    RESUME = "resume"


STAGE_LABELS = {
    Stage.PLANNING: "Планирование",
    Stage.EXECUTION: "Реализация",
    Stage.VALIDATION: "Валидация",
    Stage.DONE: "Готово",
}

ACTION_LABELS = {
    Action.SUBMIT_PLAN: "Отправить план",
    Action.APPROVE_PLAN: "Утвердить план",
    Action.START_EXECUTION: "Начать реализацию",
    Action.COMPLETE_EXECUTION: "Завершить реализацию",
    Action.START_VALIDATION: "Начать валидацию",
    Action.PASS_VALIDATION: "Валидация пройдена",
    Action.FAIL_VALIDATION: "Валидация не пройдена",
    Action.FINISH: "Завершить задачу",
    Action.REWORK: "Вернуть в реализацию",
    Action.PAUSE: "Пауза",
    Action.RESUME: "Продолжить",
}
EXPECTED_LABELS = {
    f"{Action.PASS_VALIDATION.value} | {Action.FAIL_VALIDATION.value}": (
        "Валидация: пройдена или не пройдена"
    ),
    "none": "—",
}


def plan_steps(plan_text: str | None) -> list[str]:
    """Разобрать план на шаги для прозрачного выполнения."""
    lines = [line.strip() for line in (plan_text or "").splitlines() if line.strip()]
    numbered = [
        re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip()
        for line in lines
        if re.match(r"^\s*(?:\d+[.)]|[-*])\s+", line)
    ]
    steps = [step for step in numbered if step]
    if not steps:
        steps = [line for line in lines if len(line) > 20]
    if not steps:
        steps = ["Выполнить задачу по утверждённому плану"]
    return [step[:1_000] for step in steps[:12]]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class TaskState:
    task_id: str
    session_id: str
    goal: str
    plan_text: str | None
    context_summary: str | None
    stage: Stage
    current_step: str
    expected_action: str
    paused: bool
    plan_approved: bool
    execution_complete: bool
    validation_passed: bool
    validation_failed: bool
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def new(cls, session_id: str, goal: str) -> "TaskState":
        now = utcnow()
        return cls(
            task_id=str(uuid.uuid4()),
            session_id=session_id,
            goal=goal.strip(),
            plan_text=None,
            context_summary=None,
            stage=Stage.PLANNING,
            current_step="формулировка плана",
            expected_action=Action.SUBMIT_PLAN.value,
            paused=False,
            plan_approved=False,
            execution_complete=False,
            validation_passed=False,
            validation_failed=False,
            version=1,
            created_at=now,
            updated_at=now,
        )

    def copy(self) -> "TaskState":
        return replace(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "plan_text": self.plan_text,
            "context_summary": self.context_summary,
            "stage": self.stage.value,
            "stage_label": STAGE_LABELS[self.stage],
            "current_step": self.current_step,
            "expected_action": self.expected_action,
            "expected_action_label": EXPECTED_LABELS.get(
                self.expected_action,
                ACTION_LABELS.get(
                    Action(self.expected_action), self.expected_action
                )
                if self.expected_action in Action._value2member_map_
                else self.expected_action,
            ),
            "paused": self.paused,
            "plan_approved": self.plan_approved,
            "execution_complete": self.execution_complete,
            "validation_passed": self.validation_passed,
            "validation_failed": self.validation_failed,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "done": self.stage is Stage.DONE,
        }


@dataclass
class TaskEvent:
    task_id: str
    action: str
    from_stage: str
    to_stage: str
    reason: str | None
    success: bool
    error_code: str | None
    version_before: int
    version_after: int
    created_at: str

    @classmethod
    def from_transition(
        cls,
        task: TaskState,
        action: Action,
        new_task: TaskState,
        reason: str | None,
    ) -> "TaskEvent":
        return cls(
            task_id=task.task_id,
            action=action.value,
            from_stage=task.stage.value,
            to_stage=new_task.stage.value,
            reason=reason,
            success=True,
            error_code=None,
            version_before=task.version,
            version_after=new_task.version,
            created_at=timer_now(),
        )

    @classmethod
    def rejection(
        cls,
        task: TaskState,
        action: Action | str,
        reason: str | None,
        error_code: str,
    ) -> "TaskEvent":
        return cls(
            task_id=task.task_id,
            action=action.value if isinstance(action, Action) else str(action),
            from_stage=task.stage.value,
            to_stage=task.stage.value,
            reason=reason,
            success=False,
            error_code=error_code,
            version_before=task.version,
            version_after=task.version,
            created_at=timer_now(),
        )


def timer_now() -> str:
    return utcnow()


class TaskError(Exception):
    """Ошибка домена с готовым JSON-контрактом."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        task: TaskState | None = None,
        action: str | None = None,
        possible_actions: list[str] | None = None,
        available_actions: list[str] | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.task = task
        self.action = action
        self.possible_actions = possible_actions or []
        self.available_actions = available_actions or []
        self.hint = hint
        self.details = details or {}

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "state_unchanged": True,
        }
        if self.task is not None:
            result.update(
                {
                    "current_stage": self.task.stage.value,
                    "version": self.task.version,
                    "possible_actions": self.possible_actions,
                    "available_actions": self.available_actions,
                }
            )
        if self.action is not None:
            result["action"] = self.action
        if self.hint:
            result["hint"] = self.hint
        if self.details:
            result["details"] = self.details
        return result


class TransitionNotAllowed(TaskError):
    def __init__(
        self,
        task: TaskState,
        action: Action,
        *,
        possible_actions: list[str],
        available_actions: list[str],
    ) -> None:
        super().__init__(
            "transition_not_allowed",
            f"Действие {action.value!r} недоступно на этапе {task.stage.value!r}",
            task=task,
            action=action.value,
            possible_actions=possible_actions,
            available_actions=available_actions,
        )


class GuardFailed(TaskError):
    def __init__(
        self,
        task: TaskState,
        action: Action,
        reason: str,
        *,
        possible_actions: list[str],
        available_actions: list[str],
    ) -> None:
        super().__init__(
            "guard_failed",
            reason,
            task=task,
            action=action.value,
            possible_actions=possible_actions,
            available_actions=available_actions,
        )


class TaskPaused(TaskError):
    def __init__(
        self,
        task: TaskState,
        action: Action,
        *,
        possible_actions: list[str],
        available_actions: list[str],
    ) -> None:
        super().__init__(
            "task_paused",
            "Задача на паузе. Сначала продолжите выполнение.",
            task=task,
            action=action.value,
            possible_actions=possible_actions,
            available_actions=available_actions,
        )


class VersionConflict(TaskError):
    def __init__(self, task: TaskState) -> None:
        super().__init__(
            "version_conflict",
            "Состояние уже изменилось. Обновите задачу и повторите действие.",
            task=task,
            possible_actions=[],
            available_actions=[],
        )


class TaskNotFound(TaskError):
    def __init__(self) -> None:
        super().__init__(
            "task_not_found",
            "Активная задача не найдена.",
            status_code=404,
        )


class ActiveTaskExists(TaskError):
    def __init__(self, task: TaskState) -> None:
        super().__init__(
            "active_task_exists",
            "У сессии уже есть незавершённая задача.",
            task=task,
            possible_actions=[],
            available_actions=[],
        )
