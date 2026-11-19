"""Декларативная таблица действий и guard-условий."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from .domain import Action, Stage, TaskState


Guard = Callable[[TaskState, str | None], str | None]
Apply = Callable[[TaskState, str | None], TaskState]


@dataclass(frozen=True)
class ActionSpec:
    action: Action
    stages: frozenset[Stage]
    guard: Guard
    apply: Apply


def _yes(_task: TaskState, _plan: str | None) -> str | None:
    return None


def _submit_plan(task: TaskState, _plan: str | None) -> str | None:
    if task.plan_approved:
        return "План уже утверждён; повторная отправка плана недоступна."
    return None


def _approve_plan(task: TaskState, _plan: str | None) -> str | None:
    if not (task.plan_text or "").strip():
        return "Нельзя утвердить пустой план."
    if task.plan_approved:
        return "План уже утверждён."
    return None


def _start_execution(task: TaskState, _plan: str | None) -> str | None:
    if not task.plan_approved:
        return "Нельзя начать реализацию: план не утверждён."
    return None


def _complete_execution(task: TaskState, _plan: str | None) -> str | None:
    if task.execution_complete:
        return "Реализация уже отмечена как завершённая."
    return None


def _start_validation(task: TaskState, _plan: str | None) -> str | None:
    if not task.execution_complete:
        return "Нельзя начать валидацию: реализация не завершена."
    return None


def _pass_validation(task: TaskState, _plan: str | None) -> str | None:
    if task.validation_passed or task.validation_failed:
        return "Решение валидации уже зафиксировано."
    return None


def _fail_validation(task: TaskState, _plan: str | None) -> str | None:
    if task.validation_passed or task.validation_failed:
        return "Решение валидации уже зафиксировано."
    return None


def _finish(task: TaskState, _plan: str | None) -> str | None:
    if not task.validation_passed:
        return "Нельзя завершить задачу: валидация не пройдена."
    if task.validation_failed:
        return "Нельзя завершить задачу: есть проваленная валидация."
    return None


def _rework(task: TaskState, _plan: str | None) -> str | None:
    if not task.validation_failed:
        return "Доработка доступна только после проваленной валидации."
    return None


def _pause(task: TaskState, _plan: str | None) -> str | None:
    if task.paused:
        return None
    return None


def _resume(task: TaskState, _plan: str | None) -> str | None:
    if not task.paused:
        return None
    return None


def _do_submit_plan(task: TaskState, plan: str | None) -> TaskState:
    return replace(
        task,
        plan_text=(plan or task.plan_text or "").strip(),
        plan_approved=False,
        current_step="план отправлен",
        expected_action=Action.APPROVE_PLAN.value,
    )


def _do_approve_plan(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        plan_approved=True,
        current_step="план утверждён",
        expected_action=Action.START_EXECUTION.value,
    )


def _do_start_execution(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        stage=Stage.EXECUTION,
        current_step="реализация",
        expected_action=Action.COMPLETE_EXECUTION.value,
        execution_complete=False,
        validation_passed=False,
        validation_failed=False,
    )


def _do_complete_execution(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        execution_complete=True,
        current_step="реализация завершена",
        expected_action=Action.START_VALIDATION.value,
    )


def _do_start_validation(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        stage=Stage.VALIDATION,
        current_step="валидация",
        expected_action=f"{Action.PASS_VALIDATION.value} | {Action.FAIL_VALIDATION.value}",
        validation_passed=False,
        validation_failed=False,
    )


def _do_pass_validation(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        validation_passed=True,
        validation_failed=False,
        current_step="валидация пройдена",
        expected_action=Action.FINISH.value,
    )


def _do_fail_validation(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        validation_passed=False,
        validation_failed=True,
        current_step="валидация не пройдена",
        expected_action=Action.REWORK.value,
    )


def _do_finish(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        stage=Stage.DONE,
        current_step="задача завершена",
        expected_action="none",
        paused=False,
    )


def _do_rework(task: TaskState, _plan: str | None) -> TaskState:
    return replace(
        task,
        stage=Stage.EXECUTION,
        execution_complete=False,
        validation_passed=False,
        validation_failed=False,
        current_step="доработка",
        expected_action=Action.COMPLETE_EXECUTION.value,
    )


def _do_pause(task: TaskState, _plan: str | None) -> TaskState:
    return replace(task, paused=True)


def _do_resume(task: TaskState, _plan: str | None) -> TaskState:
    return replace(task, paused=False)


ALL_ACTIVE = frozenset({Stage.PLANNING, Stage.EXECUTION, Stage.VALIDATION})

WORKFLOW: tuple[ActionSpec, ...] = (
    ActionSpec(
        Action.SUBMIT_PLAN,
        frozenset({Stage.PLANNING}),
        _submit_plan,
        _do_submit_plan,
    ),
    ActionSpec(
        Action.APPROVE_PLAN,
        frozenset({Stage.PLANNING}),
        _approve_plan,
        _do_approve_plan,
    ),
    ActionSpec(
        Action.START_EXECUTION,
        frozenset({Stage.PLANNING}),
        _start_execution,
        _do_start_execution,
    ),
    ActionSpec(
        Action.COMPLETE_EXECUTION,
        frozenset({Stage.EXECUTION}),
        _complete_execution,
        _do_complete_execution,
    ),
    ActionSpec(
        Action.START_VALIDATION,
        frozenset({Stage.EXECUTION}),
        _start_validation,
        _do_start_validation,
    ),
    ActionSpec(
        Action.PASS_VALIDATION,
        frozenset({Stage.VALIDATION}),
        _pass_validation,
        _do_pass_validation,
    ),
    ActionSpec(
        Action.FAIL_VALIDATION,
        frozenset({Stage.VALIDATION}),
        _fail_validation,
        _do_fail_validation,
    ),
    ActionSpec(
        Action.FINISH,
        frozenset({Stage.VALIDATION}),
        _finish,
        _do_finish,
    ),
    ActionSpec(
        Action.REWORK,
        frozenset({Stage.VALIDATION}),
        _rework,
        _do_rework,
    ),
    ActionSpec(Action.PAUSE, ALL_ACTIVE, _pause, _do_pause),
    ActionSpec(Action.RESUME, frozenset(Stage), _resume, _do_resume),
)


def specs_for(stage: Stage) -> list[ActionSpec]:
    return [spec for spec in WORKFLOW if stage in spec.stages]


def spec_for(action: Action) -> ActionSpec | None:
    return next((spec for spec in WORKFLOW if spec.action is action), None)
