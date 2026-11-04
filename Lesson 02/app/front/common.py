"""Общие части объединённого фронта: адреса API, SSE-клиент, стили."""

from __future__ import annotations

import json
import os
from typing import Iterator

import httpx

# Урок 01 (чат) и урок 02 (форматы) — разные сервисы, разные адреса
CHAT_API = os.getenv("CHAT_API_BASE_URL", "http://localhost:8000").rstrip("/")
FORMAT_API = os.getenv("FORMAT_API_BASE_URL", "http://localhost:8002").rstrip("/")
TIMEOUT = httpx.Timeout(300.0, connect=10.0)
LAMP = "#ff9d3d"

SOURCE_LABELS = {"mock": "Демо (mock)", "deepseek": "DeepSeek API", "openai": "OpenAI API"}
REASONING_LABELS = {
    "off": "Выключен",
    "none": "Без рассуждений",
    "minimal": "Минимальный",
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "xhigh": "Очень высокий",
    "ultra": "Ультра",
    "max": "Максимальный",
}

BASE_CSS = f"""
      [data-testid="stSidebarHeader"] {{ height: 0 !important; min-height: 0 !important; padding: 0 !important; }}
      [data-testid="stSidebarHeader"] > div {{ display: none !important; }}
      [data-testid="stSidebarUserContent"] {{ padding-top: 0 !important; }}
      .brand {{ font-size: 1.35rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;
                margin: -.1rem 0 .05rem 0; }}
      .brand span {{ color: {LAMP}; text-shadow: 0 0 12px rgba(255,157,61,.55); }}
      .brand-sub {{ font-size: .62rem; letter-spacing: .18em; text-transform: uppercase; opacity: .42;
                    margin: 0 0 .55rem 0; }}
      .provider-badge {{ font-size: .8rem; opacity: .85; margin: -.1rem 0 .35rem 0; cursor: default; }}
      .prov-chip {{ margin-right: .7rem; white-space: nowrap; }}
      [data-testid="stPopover"] button[data-testid="stPopoverButton"] {{
          width: 100%; justify-content: center; font-weight: 600;
          background: linear-gradient(180deg, #8b6bff, #6f4ae6) !important; color: #fff !important;
          border: 1px solid #7a55f0 !important;
      }}
      [data-testid="stPopoverBody"], [role="dialog"] {{ min-width: 15rem; max-width: 18rem; }}

      /* ламповое табло слайдеров */
      .nixie {{ display: flex; gap: 6px; margin: .05rem 0 .5rem 0;
                filter: drop-shadow(0 0 10px rgba(255,140,40,.18)); }}
      .nixie .tube {{ position: relative; display: inline-flex; align-items: center; justify-content: center;
          width: 1.5rem; height: 2.1rem; border-radius: .5rem;
          background: radial-gradient(130% 120% at 50% 12%, #26190f 0%, #100b07 55%, #040302 100%);
          border: 1px solid #33261a;
          box-shadow: inset 0 0 14px rgba(255,140,40,.20), inset 0 -8px 12px rgba(0,0,0,.75),
                      0 1px 0 rgba(255,255,255,.05); }}
      .nixie .glow {{ font-family: "SF Mono", "Menlo", monospace; font-size: 1.05rem; font-weight: 600;
          color: #ffc078; text-shadow: 0 0 4px {LAMP}, 0 0 10px rgba(255,157,61,.6), 0 0 20px rgba(255,110,0,.32); }}
      .nixie .dot {{ display: inline-flex; align-items: flex-end; padding-bottom: .4rem;
          font-family: "SF Mono", monospace; color: #ffc078; font-size: .95rem;
          text-shadow: 0 0 8px rgba(255,157,61,.7); }}
      [data-testid="stSliderThumbValue"] {{ display: none !important; }}
      [data-testid="stSliderTickBar"] {{ opacity: .45; font-family: "SF Mono", monospace; }}
      [data-testid="stSlider"] [role="group"] > div > div:first-child {{
          height: 8px !important; border-radius: 6px !important;
          background: linear-gradient(90deg, #3a2410, #14100b) !important;
          box-shadow: inset 0 1px 4px rgba(0,0,0,.9), 0 0 6px rgba(255,140,40,.12); }}
      [data-testid="stSlider"] [role="group"] > div > div[style*="position: absolute"] {{
          width: 1.2rem !important; height: 1.2rem !important; border-radius: 50% !important;
          background: radial-gradient(circle at 50% 35%, #ffe3bd, {LAMP} 48%, #c9611a 76%, #5c2a06 100%) !important;
          border: 1px solid #63330f !important;
          box-shadow: 0 0 12px rgba(255,157,61,.95), 0 0 26px rgba(255,120,0,.5) !important; }}

      .reasoning-text {{ font-size: .86rem; opacity: .85; line-height: 1.45; }}
      .meta-line {{ font-size: .76rem; opacity: .58; }}
      .verdict-ok {{ color: #6ee7a8; font-weight: 600; }}
      .verdict-bad {{ color: #ff8a8a; font-weight: 600; }}
      div[data-testid="stChatMessage"] {{ padding-bottom: .25rem; }}
"""


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    event, data = None, []
    for line in lines:
        if line == "":
            if event:
                try:
                    yield event, json.loads("".join(data) or "{}")
                except json.JSONDecodeError:
                    yield event, {}
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if event:
        try:
            yield event, json.loads("".join(data) or "{}")
        except json.JSONDecodeError:
            yield event, {}


def post_stream(path: str, payload: dict, base: str) -> Iterator[tuple[str, dict]]:
    """POST и разбор SSE; ошибки HTTP отдаём событием error."""
    with httpx.stream("POST", f"{base}{path}", json=payload, timeout=TIMEOUT) as response:
        if response.status_code != 200:
            response.read()
            try:
                detail = response.json().get("detail", response.text)
            except Exception:  # noqa: BLE001
                detail = response.text
            yield "error", {"message": f"API {response.status_code}: {detail}", "kind": "http"}
            return
        yield from parse_sse(response.iter_lines())


def nixie_digits(text: str) -> str:
    cells = []
    for char in text:
        if char in ".,":
            cells.append(f'<span class="dot">{char}</span>')
        else:
            cells.append(f'<span class="tube"><span class="glow">{char}</span></span>')
    return f'<div class="nixie">{"".join(cells)}</div>'

PROVIDER_LABELS = {
    "mock": "Демо",
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
}


def provider_badges(rows: list[dict]) -> str:
    """Индикаторы доступности: 🟢 отвечает, 🟠 не отвечает, ⚪ ключа нет."""
    chips = []
    for row in rows or []:
        name = row.get("provider") or ""
        label = PROVIDER_LABELS.get(name, name.title() or "—").split(" · ")[0].removesuffix(" API")
        if not row.get("configured"):
            dot, hint = "⚪", "ключ не настроен"
        elif row.get("available"):
            dot = "🟢"
            hint = f"{row.get('models', 0)} моделей · {row.get('latency_ms', 0)} мс"
        else:
            dot, hint = "🟠", row.get("error") or "нет ответа"
        chips.append(f'<span class="prov-chip" title="{hint}">{dot} {label}</span>')
    return f'<div class="provider-badge">{"".join(chips)}</div>' if chips else ""

