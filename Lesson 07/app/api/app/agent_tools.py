"""Инструменты ИИ-агента урока 06.

Каждый инструмент — обычная Python-функция с JSON-схемой для модели.
Модель сама решает, какой инструмент вызвать; сервер лишь проверяет
аргументы и возвращает наблюдение (observation) обратно в диалог.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import operator
import re
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

#: Максимальная длина выражения калькулятора
MAX_EXPRESSION = 200
#: Предел результата, чтобы модель не считала 9**9**9
MAX_RESULT = 10**12

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Точно вычисляет арифметическое выражение: +, -, *, /, //, %, **, "
                "скобки, round(), abs(), min(), max(). Используй для любых расчётов, "
                "не считай в уме."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Выражение, например: (4850 * 17) / 100",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": (
                "Возвращает текущие дату, время и день недели в указанном часовом поясе. "
                "По умолчанию — Europe/Moscow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA-пояс, например Europe/Moscow или Asia/Tokyo",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "text_stats",
            "description": (
                "Считает статистику текста: символы, символы без пробелов, слова, "
                "предложения, строки и примерное время чтения."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст для анализа"}
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "currency_rates",
            "description": (
                "Возвращает курсы валют по данным open.er-api.com: сколько единиц "
                "каждой целевой валюты стоит одна единица базовой. По умолчанию "
                "база USD и основные валюты. Используй для курсов и конвертации."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {
                        "type": "string",
                        "description": "Код базовой валюты из трёх букв, например USD",
                    },
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Коды целевых валют, до 8; пусто — основные",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_converter",
            "description": (
                "Переводит значение между единицами длины, массы, температуры, объёма, "
                "данных и времени. Возвращает точный числовой результат."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "Числовое значение"},
                    "from_unit": {"type": "string", "description": "Исходная единица: km, m, kg, C, F, GB, l…"},
                    "to_unit": {"type": "string", "description": "Целевая единица: m, mi, lb, F, MB, ml…"},
                },
                "required": ["value", "from_unit", "to_unit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "date_diff",
            "description": (
                "Считает разницу между двумя датами в днях или прибавляет дни к дате. "
                "Даты — в формате YYYY-MM-DD или DD.MM.YYYY."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Начальная дата"},
                    "end": {"type": "string", "description": "Конечная дата; не вместе с days"},
                    "days": {"type": "integer", "description": "Сколько дней прибавить к start"},
                },
                "required": ["start"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "number_base",
            "description": (
                "Переводит число между системами счисления: десятичная, двоичная, "
                "восьмеричная, шестнадцатеричная и другие (2–36)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": "Число в исходной системе"},
                    "from_base": {"type": "integer", "minimum": 2, "maximum": 36,
                                  "description": "Исходная система, по умолчанию 10"},
                    "to_base": {"type": "integer", "minimum": 2, "maximum": 36,
                                "description": "Целевая система, по умолчанию 16"},
                },
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "number_stats",
            "description": (
                "Считает статистику набора чисел: количество, сумму, среднее, медиану, "
                "минимум, максимум, размах и стандартное отклонение."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numbers": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 1,
                        "maxItems": 200,
                        "description": "Числа для анализа",
                    }
                },
                "required": ["numbers"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "text_hash",
            "description": (
                "Считает криптографический хеш текста: SHA-256, SHA-1 или MD5. "
                "Возвращает hex-строку и длину входа."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст для хеширования"},
                    "algorithm": {
                        "type": "string",
                        "enum": ["sha256", "sha1", "md5"],
                        "description": "Алгоритм, по умолчанию sha256",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_LABELS = {
    "calculator": "Калькулятор",
    "current_time": "Текущее время",
    "text_stats": "Статистика текста",
    "currency_rates": "Курс валют",
    "unit_converter": "Конвертер единиц",
    "date_diff": "Разница дат",
    "number_base": "Системы счисления",
    "number_stats": "Статистика чисел",
    "text_hash": "Хеш текста",
}

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_FUNCTIONS = {
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
}


class ToolError(ValueError):
    """Ошибка аргументов инструмента — возвращается модели как наблюдение."""


@dataclass(frozen=True)
class Tool:
    """Инструмент агента: описание для модели плюс локальный обработчик."""

    name: str
    label: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    """Набор доступных агенту инструментов.

    Агент не знает о глобальном списке: ему передают реестр, уже суженный
    до выбранных инструментов. Это делает состав инструментов зависимостью
    агента, а не скрытым глобальным состоянием.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def select(self, names: list[str] | None) -> "ToolRegistry":
        if names is None:
            return ToolRegistry(list(self._tools.values()))
        unknown = [name for name in names if name not in self._tools]
        if unknown:
            raise ValueError(f"Неизвестный инструмент: {unknown[0]}")
        return ToolRegistry([self._tools[name] for name in dict.fromkeys(names)])

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def missing_for(self, prompt: str) -> list[str]:
        return [name for name in required_tools(prompt) if name not in self._tools]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Неизвестный инструмент: {name}"}
        try:
            result = tool.handler(arguments or {})
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - ошибку инструмента показываем модели
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "result": result}

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "label": tool.label,
                "description": tool.description,
                "parameters": tool.schema["function"]["parameters"],
            }
            for tool in self._tools.values()
        ]


def tool_catalog() -> list[dict[str, Any]]:
    """Схемы инструментов плюс человекочитаемые подписи для UI."""
    return DEFAULT_REGISTRY.catalog()


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Выполнить инструмент из реестра по умолчанию (совместимость/тесты)."""
    return DEFAULT_REGISTRY.execute(name, arguments)


# --- калькулятор -------------------------------------------------------------


def _calculator(args: dict[str, Any]) -> dict[str, Any]:
    expression = str(args.get("expression") or "").strip()
    if not expression:
        raise ToolError("Пустое выражение: передайте expression.")
    if len(expression) > MAX_EXPRESSION:
        raise ToolError(f"Выражение длиннее {MAX_EXPRESSION} символов.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"Некорректное выражение: {exc.msg}") from exc

    value = _eval_node(tree.body)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return {"expression": expression, "value": value}


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError("Разрешены только числа.")
        return node.value
    if isinstance(node, ast.BinOp):
        operation = _ALLOWED_BINOPS.get(type(node.op))
        if operation is None:
            raise ToolError("Эта операция не разрешена.")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ToolError("Слишком большая степень: максимум 10.")
        try:
            result = operation(left, right)
        except ZeroDivisionError as exc:
            raise ToolError("Деление на ноль.") from exc
        if abs(result) > MAX_RESULT:
            raise ToolError("Результат слишком большой.")
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _ALLOWED_FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ToolError("Эта функция не разрешена.")
        return function(*(_eval_node(arg) for arg in node.args))
    raise ToolError("В выражении есть недопустимая конструкция.")


# --- время -------------------------------------------------------------------

_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _current_time(args: dict[str, Any]) -> dict[str, Any]:
    timezone = str(args.get("timezone") or "Europe/Moscow").strip()
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(f"Неизвестный часовой пояс: {timezone}") from exc
    now = datetime.now(zone)
    offset = now.utcoffset()
    offset_hours = offset.total_seconds() / 3600 if offset else 0
    return {
        "timezone": timezone,
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%d.%m.%Y"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS[now.weekday()],
        "utc_offset_hours": round(offset_hours, 2),
    }


# --- статистика текста -------------------------------------------------------


def _text_stats(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "")
    if not text.strip():
        raise ToolError("Пустой текст: передайте text.")
    words = re.findall(r"[\w'-]+", text, flags=re.UNICODE)
    sentences = [part for part in re.split(r"[.!?…]+", text) if part.strip()]
    lines = [line for line in text.splitlines() if line.strip()]
    reading_minutes = max(1, round(len(words) / 200)) if words else 0
    return {
        "chars": len(text),
        "chars_no_spaces": len(re.sub(r"\s", "", text)),
        "words": len(words),
        "sentences": len(sentences),
        "lines": len(lines),
        "reading_minutes": reading_minutes,
    }


# --- конвертер единиц --------------------------------------------------------

_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "length": {
        "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
        "mi": 1609.344, "ft": 0.3048, "in": 0.0254, "yd": 0.9144,
    },
    "mass": {
        "kg": 1.0, "g": 0.001, "mg": 0.000001, "t": 1000.0,
        "lb": 0.45359237, "oz": 0.028349523125,
    },
    "volume": {"l": 1.0, "ml": 0.001, "gal": 3.785411784, "pt": 0.473176473},
    "data": {
        "b": 1.0, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
        "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3,
    },
    "time": {"s": 1.0, "min": 60.0, "h": 3600.0, "day": 86400.0},
}

_UNIT_ALIASES = {
    "км": "km", "м": "m", "см": "cm", "мм": "mm",
    "миля": "mi", "мили": "mi", "миль": "mi",
    "фут": "ft", "фута": "ft", "футы": "ft",
    "дюйм": "in", "дюйма": "in", "ярд": "yd",
    "кг": "kg", "г": "g", "мг": "mg", "т": "t", "тонна": "t", "тонны": "t",
    "фунт": "lb", "фунта": "lb", "унция": "oz", "унции": "oz",
    "л": "l", "мл": "ml", "литр": "l", "литра": "l", "галлон": "gal",
    "байт": "b", "байта": "b", "кб": "kb", "мб": "mb", "гб": "gb", "тб": "tb",
    "кибибайт": "kib", "мебибайт": "mib", "гибибайт": "gib",
    "с": "s", "сек": "s", "секунд": "s", "мин": "min", "минута": "min",
    "минуты": "min", "ч": "h", "час": "h", "часа": "h",
    "день": "day", "дня": "day", "дней": "day",
    "цельсий": "c", "цельсия": "c", "фаренгейт": "f", "фаренгейта": "f",
    "кельвин": "k", "кельвина": "k",
}

_TEMPERATURE_UNITS = {"c", "f", "k"}


def _unit_converter(args: dict[str, Any]) -> dict[str, Any]:
    try:
        value = float(args.get("value"))
    except (TypeError, ValueError) as exc:
        raise ToolError("value должно быть числом.") from exc
    if not math.isfinite(value):
        raise ToolError("value должно быть конечным числом.")
    from_unit = _normalize_unit(args.get("from_unit"))
    to_unit = _normalize_unit(args.get("to_unit"))
    if not from_unit or not to_unit:
        raise ToolError("Укажите from_unit и to_unit.")

    if from_unit in _TEMPERATURE_UNITS or to_unit in _TEMPERATURE_UNITS:
        if from_unit not in _TEMPERATURE_UNITS or to_unit not in _TEMPERATURE_UNITS:
            raise ToolError("Температуру можно переводить только между C, F и K.")
        result = _convert_temperature(value, from_unit, to_unit)
        return {
            "value": value,
            "from": from_unit,
            "to": to_unit,
            "result": round(result, 6),
            "category": "temperature",
        }

    for category, factors in _UNIT_FACTORS.items():
        if from_unit in factors and to_unit in factors:
            result = value * factors[from_unit] / factors[to_unit]
            return {
                "value": value,
                "from": from_unit,
                "to": to_unit,
                "result": round(result, 6),
                "category": category,
            }
    raise ToolError(f"Не знаю единицы {from_unit!r} и/или {to_unit!r}.")


def _normalize_unit(raw: Any) -> str:
    unit = str(raw or "").strip().lower().replace("°", "").replace(" ", "")
    return _UNIT_ALIASES.get(unit, unit)


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    if from_unit == "c":
        celsius = value
    elif from_unit == "f":
        celsius = (value - 32) * 5 / 9
    else:
        celsius = value - 273.15
    if to_unit == "c":
        return celsius
    if to_unit == "f":
        return celsius * 9 / 5 + 32
    return celsius + 273.15


# --- разница дат -------------------------------------------------------------


def _date_diff(args: dict[str, Any]) -> dict[str, Any]:
    start = _parse_date(args.get("start"), "start")
    raw_end = str(args.get("end") or "").strip()
    raw_days = args.get("days")
    if raw_end and raw_days not in (None, ""):
        raise ToolError("Передайте либо end, либо days, но не оба сразу.")
    if raw_end:
        end = _parse_date(raw_end, "end")
        delta = (end - start).days
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": delta,
            "abs_days": abs(delta),
            "weeks": round(delta / 7, 2),
            "hours": delta * 24,
            "weekday_start": _WEEKDAYS[start.weekday()],
            "weekday_end": _WEEKDAYS[end.weekday()],
        }
    if raw_days in (None, ""):
        raise ToolError("Укажите end или days.")
    try:
        days = int(raw_days)
    except (TypeError, ValueError) as exc:
        raise ToolError("days должно быть целым числом.") from exc
    target = start + timedelta(days=days)
    return {
        "start": start.isoformat(),
        "days_added": days,
        "target": target.isoformat(),
        "weekday": _WEEKDAYS[target.weekday()],
    }


def _parse_date(raw: Any, field: str) -> date:
    text = str(raw or "").strip()
    if not text:
        raise ToolError(f"Укажите {field} в формате YYYY-MM-DD или DD.MM.YYYY.")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ToolError(f"Не удалось разобрать дату {text!r}; нужен YYYY-MM-DD или DD.MM.YYYY.")


# --- системы счисления -------------------------------------------------------

_BASE_ALIASES = {
    "bin": 2, "binary": 2, "двоичная": 2, "двоичной": 2,
    "oct": 8, "octal": 8, "восьмеричная": 8, "восьмеричной": 8,
    "dec": 10, "decimal": 10, "десятичная": 10, "десятичной": 10,
    "hex": 16, "hexadecimal": 16, "шестнадцатеричная": 16, "шестнадцатеричной": 16,
}
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _number_base(args: dict[str, Any]) -> dict[str, Any]:
    raw_value = str(args.get("value") if args.get("value") is not None else "").strip().lower()
    raw_value = raw_value.replace("_", "").replace(" ", "")
    if not raw_value:
        raise ToolError("Укажите value.")
    from_raw = args.get("from_base")
    if from_raw in (None, ""):
        if raw_value.startswith("0x"):
            from_base = 16
        elif raw_value.startswith("0b"):
            from_base = 2
        elif raw_value.startswith("0o"):
            from_base = 8
        else:
            from_base = 10
    else:
        from_base = _parse_base(from_raw, "from_base")
    to_base = _parse_base(args.get("to_base"), "to_base", default=16)
    try:
        number = int(raw_value, from_base)
    except ValueError as exc:
        raise ToolError(f"{raw_value!r} — не число в системе с основанием {from_base}.") from exc
    return {
        "decimal": number,
        "result": _to_base(number, to_base),
        "from_base": from_base,
        "to_base": to_base,
    }


def _parse_base(raw: Any, field: str, default: int = 10) -> int:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        raise ToolError(f"{field} должно быть целым числом 2–36.")
    if isinstance(raw, int):
        base = raw
    else:
        text = str(raw).strip().lower()
        if text in _BASE_ALIASES:
            base = _BASE_ALIASES[text]
        else:
            try:
                base = int(text)
            except ValueError as exc:
                raise ToolError(f"{field} должно быть целым числом 2–36.") from exc
    if not 2 <= base <= 36:
        raise ToolError(f"{field} должно быть в диапазоне 2–36.")
    return base


def _to_base(number: int, base: int) -> str:
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, base)
        digits.append(_DIGITS[remainder])
    return sign + "".join(reversed(digits))


# --- статистика чисел --------------------------------------------------------


def _number_stats(args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("numbers")
    if isinstance(raw, str):
        raw = [part for part in re.split(r"[,\s;]+", raw) if part]
    if not isinstance(raw, list) or not raw:
        raise ToolError("Передайте непустой список numbers.")
    if len(raw) > 200:
        raise ToolError("Слишком много чисел: максимум 200.")
    values: list[float] = []
    for item in raw:
        try:
            value = float(item)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"{item!r} — не число.") from exc
        if not math.isfinite(value):
            raise ToolError("Все числа должны быть конечными.")
        values.append(value)
    return {
        "count": len(values),
        "sum": round(sum(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "median": round(statistics.median(values), 6),
        "min": min(values),
        "max": max(values),
        "range": round(max(values) - min(values), 6),
        "stdev": round(statistics.pstdev(values), 6),
        "variance": round(statistics.pvariance(values), 6),
    }


# --- хеш текста --------------------------------------------------------------


def _text_hash(args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("text") or "")
    if not text:
        raise ToolError("Передайте непустой text.")
    algorithm = str(args.get("algorithm") or "sha256").strip().lower().replace("-", "")
    if algorithm not in {"sha256", "sha1", "md5"}:
        raise ToolError("algorithm должен быть sha256, sha1 или md5.")
    digest = hashlib.new(algorithm, text.encode("utf-8")).hexdigest()
    return {
        "algorithm": algorithm,
        "hash": digest,
        "hex_length": len(digest),
        "chars": len(text),
        "bytes": len(text.encode("utf-8")),
    }


# --- курсы валют -------------------------------------------------------------

CURRENCY_URL = "https://open.er-api.com/v6/latest/{base}"
CURRENCY_TTL_S = 600
DEFAULT_TARGETS = ("USD", "EUR", "RUB", "CNY", "GBP")
MAX_TARGETS = 8
_rates_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _fetch_rates(base: str) -> dict[str, Any]:
    """Запросить свежие курсы у open.er-api.com (без ключа)."""
    with httpx.Client(timeout=12.0, follow_redirects=True) as client:
        response = client.get(CURRENCY_URL.format(base=base))
    response.raise_for_status()
    data = response.json()
    if data.get("result") != "success":
        raise ToolError(data.get("error-type") or "Источник курсов вернул ошибку.")
    return data


def _currency_rates(args: dict[str, Any]) -> dict[str, Any]:
    base = str(args.get("base") or "USD").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", base):
        raise ToolError("Базовая валюта должна быть кодом из трёх букв, например USD.")

    cached = _rates_cache.get(base)
    if cached is None or time.monotonic() - cached[0] > CURRENCY_TTL_S:
        try:
            data = _fetch_rates(base)
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - сеть недоступна
            raise ToolError(f"Не удалось получить курсы валют: {exc}") from exc
        rates = data.get("rates") or {}
        if base not in rates:
            raise ToolError(f"Источник не знает валюту {base}.")
        cached = (time.monotonic(), data)
        _rates_cache[base] = cached

    data = cached[1]
    rates: dict[str, float] = data.get("rates") or {}
    raw_targets = args.get("targets") or []
    if isinstance(raw_targets, str):
        raw_targets = re.split(r"[,\s]+", raw_targets)
    targets = [str(item).strip().upper() for item in raw_targets if str(item).strip()]
    if not targets:
        targets = [code for code in DEFAULT_TARGETS if code != base]
    if len(targets) > MAX_TARGETS:
        raise ToolError(f"Слишком много целевых валют: максимум {MAX_TARGETS}.")
    for code in targets:
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ToolError(f"Некорректный код валюты: {code}.")
    unknown = [code for code in targets if code not in rates]
    if unknown:
        raise ToolError(f"Источник не знает валюты: {', '.join(unknown)}.")

    base_rate = float(rates[base] or 1.0)
    return {
        "base": base,
        "date": data.get("time_last_update_utc") or "",
        "source": "open.er-api.com",
        "rates": {
            code: round(float(rates[code]) / base_rate, 6)
            for code in targets
        },
    }


def required_tools(prompt: str) -> list[str]:
    """Какие инструменты нужны для типовой задачи — до вызова модели.

    Это страховка для случая, когда нужный инструмент не выбран: агент должен
    честно сказать, что не может ответить, а не выдумывать результат. Для задач
    «курс + посчитать сумму» нужны оба инструмента.
    """
    low = prompt.lower()
    needed: list[str] = []

    hash_task = any(token in low for token in (
        "sha256", "sha-256", "sha1", "sha-1", "md5", "хеш", "хэш", "контрольн",
    ))
    base_task = any(token in low for token in (
        "шестнадцатерич", "двоичн", "восьмерич", "hex", "binary", "octal",
        "система счисления", "системы счисления", "16-ричн", "2-ичн",
    ))
    date_task = bool(re.search(
        r"(сколько\s+дней|разниц\w*\s+(?:между\s+)?дат|между\s+дат|"
        r"через\s+\d+\s+дн|прибав\w*\s+\d+\s+дн|добав\w*\s+\d+\s+дн|"
        r"вычт\w*\s+\d+\s+дн)",
        low,
    ))
    unit_task = any(token in low for token in (
        "километр", "метр", "сантиметр", "миллиметр", "миля", "миль",
        "фут", "дюйм", "ярд", "килограмм", "грамм", "тонн", "литр",
        "миллилитр", "галлон", "байт", "килобайт", "мегабайт", "гигабайт",
        "терабайт", "цельс", "фаренгейт", "кельвин", "градус",
    ))
    if ("фунт" in low or "унци" in low) and any(
        token in low for token in ("кг", "килограмм", "грамм", "вес", "масс")
    ):
        unit_task = True
    stats_task = any(token in low for token in (
        "среднее", "средняя", "медиан", "стандартн", "отклонен", "дисперс",
        "сумма чисел", "статистика чисел", "минимум", "максимум",
    ))
    text_task = any(token in low for token in ("слов", "символ", "предложен")) or (
        "статистик" in low and "текст" in low
    )
    currency_task = any(token in low for token in (
        "курс", "валют", "доллар", "евро", "рубл", "юан", "иен",
        "usd", "eur", "rub", "cny", "gbp", "конвертац", "конвертир",
    )) or ("фунт" in low and any(token in low for token in ("курс", "стерлинг", "валют")))

    if hash_task:
        needed.append("text_hash")
    if base_task:
        needed.append("number_base")
    if date_task:
        needed.append("date_diff")
    if unit_task:
        needed.append("unit_converter")
    if stats_task:
        needed.append("number_stats")
    if currency_task:
        needed.append("currency_rates")
    if text_task:
        needed.append("text_stats")
    time_task = any(token in low for token in (
        "который час", "сколько времени", "текущ", "какое сегодня число",
        "дата", "день недели", "врем",
    ))
    explicit_clock = any(token in low for token in (
        "который час", "сколько времени", "текущ", "врем",
    ))
    if time_task and (not date_task or explicit_clock):
        needed.append("current_time")

    strong_math = "%" in low or any(token in low for token in (
        "процент", "умнож", "сложи", "вычти", "раздели", "плюс", "минус",
        "делить", "сколько получится",
    ))
    # Дефисы в датах («2026-01-01») не должны выглядеть как вычитание.
    operator_math = bool(re.search(r"\d\s*[+\-*/×÷]\s*\d", low)) and not date_task
    wants_math = strong_math or operator_math

    amount_in_currency = bool(
        re.search(
            r"\d[\d\s.,]*\s*(доллар|евро|рубл|юан|фунт|иен|usd|eur|rub|cny|gbp)",
            low,
        )
    )
    if wants_math or (currency_task and amount_in_currency):
        needed.append("calculator")

    return list(dict.fromkeys(needed))


def required_tool(prompt: str) -> str | None:
    """Первый необходимый инструмент (совместимость с простыми задачами)."""
    tools = required_tools(prompt)
    return tools[0] if tools else None


_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "calculator": _calculator,
    "current_time": _current_time,
    "text_stats": _text_stats,
    "currency_rates": _currency_rates,
    "unit_converter": _unit_converter,
    "date_diff": _date_diff,
    "number_base": _number_base,
    "number_stats": _number_stats,
    "text_hash": _text_hash,
}

ALL_TOOLS: list[Tool] = [
    Tool(
        name=schema["function"]["name"],
        label=TOOL_LABELS.get(schema["function"]["name"], schema["function"]["name"]),
        description=schema["function"]["description"],
        schema=schema,
        handler=_TOOL_HANDLERS[schema["function"]["name"]],
    )
    for schema in TOOL_SCHEMAS
]

DEFAULT_REGISTRY = ToolRegistry(ALL_TOOLS)


def tool_result_json(result: dict[str, Any]) -> str:
    """Сериализация наблюдения для сообщения role=tool."""
    return json.dumps(result, ensure_ascii=False)
