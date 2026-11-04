"""Две группы экспертов: одни решают задачу, другие проверяют ответы.

Совет — это не «ещё одна стратегия», а распределение ролей: у каждого участника
свой system-промпт, способ рассуждения, reasoning и температура. Проверяющая
группа получает задачу и все ответы и возвращает разбор в JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .strategies import STRATEGIES_BY_ID


@dataclass(frozen=True)
class Solver:
    """Участник, который отвечает на задачу."""

    id: str
    label: str
    role: str
    strategy: str
    reasoning: str
    temperature: float

    def system_prompt(self) -> str:
        strategy = STRATEGIES_BY_ID[self.strategy]
        return f"{strategy.system_prompt}\n\nТвоя роль: {self.label}. {self.role}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "temperature": self.temperature,
        }


@dataclass(frozen=True)
class Reviewer:
    """Участник проверяющей группы."""

    id: str
    label: str
    role: str
    reasoning: str
    temperature: float
    shows_reasoning: bool = False

    def system_prompt(self, experts: list[dict]) -> str:
        names = ", ".join(f'{item["id"]} — {item["label"]}' for item in experts)
        return (
            f"Ты — {self.label}. {self.role}\n\n"
            "Тебе дают задачу и ответы группы экспертов. Проверь КАЖДЫЙ ответ по существу: "
            "верный итог, ошибка в рассуждении, потерянное условие.\n"
            f"Эксперты и их id: {names}.\n\n"
            "Верни строго JSON без пояснений вокруг:\n"
            '{"verdicts": [{"expert": "<id>", "verdict": "ok|wrong|unclear", '
            '"comment": "<до 140 символов>"}], "final_answer": "<итоговый ответ совета>"}'
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "reasoning": self.reasoning,
            "temperature": self.temperature,
        }


SOLVERS: list[Solver] = [
    Solver(
        id="analyst",
        label="Аналитик",
        role="Разбираешь задачу по шагам, проверяешь каждое вычисление и единицы.",
        strategy="cot",
        reasoning="medium",
        temperature=0.2,
    ),
    Solver(
        id="engineer",
        label="Инженер",
        role="Любишь явный план решения и аккуратный счёт, не пропускаешь условия.",
        strategy="plan_solve",
        reasoning="low",
        temperature=0.1,
    ),
    Solver(
        id="critic",
        label="Критик",
        role="Ищешь подвох в условии и проверяешь ответ на здравый смысл.",
        strategy="self_check",
        reasoning="low",
        temperature=0.4,
    ),
    Solver(
        id="manager",
        label="Менеджер",
        role="Отвечаешь коротко: только итог и ключевые числа, без рассуждений.",
        strategy="direct",
        reasoning="none",
        temperature=0.7,
    ),
]

REVIEWERS: list[Reviewer] = [
    Reviewer(
        id="auditor",
        label="Аудитор",
        role="Проверяешь арифметику, проценты, перевод единиц и время.",
        reasoning="medium",
        temperature=0.1,
    ),
    Reviewer(
        id="logician",
        label="Логик",
        role="Проверяешь, следует ли вывод из условий, и ищешь противоречия.",
        reasoning="medium",
        temperature=0.2,
    ),
    Reviewer(
        id="chair",
        label="Председатель",
        role="Сводишь вердикты, выбираешь итоговый ответ и отмечаешь расхождения.",
        reasoning="low",
        temperature=0.3,
    ),
]

SOLVERS_BY_ID: dict[str, Solver] = {item.id: item for item in SOLVERS}
REVIEWERS_BY_ID: dict[str, Reviewer] = {item.id: item for item in REVIEWERS}


def expert_id(item: dict) -> str:
    """id эксперта: фронт может прислать и `id`, и `expert` (как в ответе API)."""
    return str(item.get("id") or item.get("expert") or "")


def review_messages(task: str, answers: list[dict]) -> list[dict]:
    """Сообщение проверяющему: задача и ответы экспертов."""
    lines = [f"Задача: {task}", "", "Ответы группы:"]
    for item in answers:
        lines.append(
            f'- id={expert_id(item)} ({item.get("label") or expert_id(item)}): '
            f'{item.get("answer") or "—"}'
        )
    lines.append("")
    lines.append("Проверь каждый ответ из списка и верни JSON по схеме.")
    return [{"role": "user", "content": "\n".join(lines)}]


VERDICT_LABELS = {"ok": "✅ верно", "wrong": "❌ ошибка", "unclear": "❓ спорно"}


def _json_slice(text: str) -> str:
    """Вырезать первый JSON-объект: модель любит добавлять текст вокруг."""
    start = text.find("{")
    end = text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else ""


def parse_review(raw: str, expected: list[str]) -> dict:
    """Разобрать JSON проверяющего; при неудаче вернуть пустой разбор."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text

    payload = None
    for candidate in (text, _json_slice(text)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(payload, dict):
        return {"verdicts": [], "final_answer": "", "parsed": False}

    verdicts = []
    for item in payload.get("verdicts") or []:
        expert = str(item.get("expert", "")).strip()
        if expert and expert in expected:
            verdicts.append({
                "expert": expert,
                "verdict": item.get("verdict") if item.get("verdict") in VERDICT_LABELS else "unclear",
                "comment": str(item.get("comment", ""))[:200],
            })
    return {
        "verdicts": verdicts,
        "final_answer": str(payload.get("final_answer", ""))[:400],
        "parsed": bool(verdicts),
    }
