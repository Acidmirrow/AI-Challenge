"""Чистый конечный автомат: без FastAPI, БД и UI."""

from __future__ import annotations

from dataclasses import replace

from .domain import (
    Action,
    GuardFailed,
    Stage,
    TaskError,
    TaskPaused,
    TaskState,
    TransitionNotAllowed,
    utcnow,
)
from .workflow import ActionSpec, WORKFLOW, specs_for


class TaskStateMachine:
    def __init__(self, workflow: tuple[ActionSpec, ...] = WORKFLOW) -> None:
        self.workflow = workflow

    def _spec(self, action: Action) -> ActionSpec | None:
        return next((spec for spec in self.workflow if spec.action is action), None)

    def possible_actions(self, task: TaskState) -> list[str]:
        if task.paused:
            return [Action.RESUME.value]
        return [
            spec.action.value
            for spec in specs_for(task.stage)
            if spec.action is not Action.RESUME
        ]

    def available_actions(self, task: TaskState) -> list[str]:
        if task.paused:
            return [Action.RESUME.value] if task.stage is not Stage.DONE else []
        result: list[str] = []
        for spec in specs_for(task.stage):
            if spec.action is Action.RESUME:
                continue
            if spec.guard(task, None) is None:
                result.append(spec.action.value)
        return result

    def apply(
        self,
        task: TaskState,
        action: Action | str,
        *,
        reason: str | None = None,
        plan_text: str | None = None,
    ) -> TaskState:
        try:
            action_enum = action if isinstance(action, Action) else Action(action)
        except ValueError as exc:
            raise TaskError(
                "unknown_action",
                f"Неизвестное действие: {action!r}",
                status_code=422,
                task=task,
            ) from exc

        spec = self._spec(action_enum)
        if spec is None:
            raise TaskError(
                "unknown_action",
                f"Неизвестное действие: {action_enum.value!r}",
                status_code=422,
                task=task,
            )

        # pause/resume идемпотентны; проверяем их до общего guard паузы.
        if action_enum is Action.PAUSE and task.paused:
            return task
        if action_enum is Action.RESUME and not task.paused:
            return task

        possible = self.possible_actions(task)
        available = self.available_actions(task)

        if task.paused and action_enum is not Action.RESUME:
            raise TaskPaused(
                task,
                action_enum,
                possible_actions=possible,
                available_actions=available,
            )

        if task.stage is Stage.DONE:
            raise TransitionNotAllowed(
                task,
                action_enum,
                possible_actions=possible,
                available_actions=available,
            )

        if task.stage not in spec.stages:
            raise TransitionNotAllowed(
                task,
                action_enum,
                possible_actions=possible,
                available_actions=available,
            )

        guard_error = spec.guard(task, plan_text)
        if guard_error:
            raise GuardFailed(
                task,
                action_enum,
                guard_error,
                possible_actions=possible,
                available_actions=available,
            )

        if action_enum is Action.SUBMIT_PLAN and not (
            (plan_text or task.plan_text or "").strip()
        ):
            raise GuardFailed(
                task,
                action_enum,
                "План не может быть пустым.",
                possible_actions=possible,
                available_actions=available,
            )

        new_task = spec.apply(task, plan_text)
        return replace(
            new_task,
            version=task.version + 1,
            updated_at=utcnow(),
        )
