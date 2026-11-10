"""Цены моделей для расчёта стоимости прогона.

Стоимость считается по прайсу провайдера за 1 млн токенов: отдельно вход
(prompt) и выход (completion). Бесплатные провайдеры (OpenRouter, Gemini, Nous Portal,
mock) считаются нулевыми.

Значения можно переопределить в `config/pricing.properties`:

    deepseek-flash.in = 0.28
    deepseek-flash.out = 0.42

Формат ключа — `<id модели>.<in|out>`, значения — доллары за 1 млн токенов.
"""

from __future__ import annotations

from pathlib import Path

#: Прайс по умолчанию, $ за 1 млн токенов: (вход, выход)
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-flash": (0.28, 0.42),
    "deepseek-v4-pro": (0.28, 1.10),
}

#: Провайдеры, у которых бесплатный тариф: стоимость всегда 0
FREE_PROVIDERS = {"openrouter", "gemini", "nous", "mock"}


def load_prices(path: str = "/srv/config/pricing.properties") -> dict[str, tuple[float, float]]:
    """Прайс из файла поверх значений по умолчанию."""
    prices = dict(DEFAULT_PRICES)
    file = Path(path)
    if not file.is_file():
        return prices

    collected: dict[str, dict[str, float]] = {}
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        try:
            number = float(value.strip())
        except ValueError:
            continue
        model, _, kind = key.rpartition(".")
        if kind in ("in", "out") and model:
            collected.setdefault(model, {})[kind] = number

    for model, sides in collected.items():
        price_in, price_out = prices.get(model, (0.0, 0.0))
        prices[model] = (sides.get("in", price_in), sides.get("out", price_out))
    return prices


def cost_of(
    prices: dict[str, tuple[float, float]],
    model_id: str,
    provider: str,
    usage: dict,
) -> tuple[float, float, float, str]:
    """Стоимость прогона: (цена входа, цена выхода, стоимость $, пояснение)."""
    if provider in FREE_PROVIDERS:
        return 0.0, 0.0, 0.0, "бесплатный провайдер"

    price_in, price_out = prices.get(model_id, (0.0, 0.0))
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    cost = prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out

    if not price_in and not price_out:
        return 0.0, 0.0, 0.0, "цена не задана"
    return price_in, price_out, round(cost, 6), "по прайсу провайдера"
