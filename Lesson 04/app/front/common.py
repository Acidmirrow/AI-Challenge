"""Общие части фронта урока 03: адрес API, SSE-клиент, стили."""

from __future__ import annotations

import json
import os
from typing import Iterator

import httpx
import streamlit as st

# Четыре урока — один шлюз, у каждого свой префикс
CHAT_API = os.getenv("CHAT_API_BASE_URL", "http://localhost:8000").rstrip("/")
FORMAT_API = os.getenv("FORMAT_API_BASE_URL", "http://localhost:8002").rstrip("/")
REASONING_API = os.getenv("REASONING_API_BASE_URL", "http://localhost:8003").rstrip("/")
TEMP_API = os.getenv("TEMP_API_BASE_URL", "http://localhost:8004").rstrip("/")
TIMEOUT = httpx.Timeout(300.0, connect=10.0)
LAMP = "#ff9d3d"

SOURCE_LABELS = {
    "mock": "Демо (mock)",
    "deepseek": "DeepSeek API",
    "openai": "OpenAI API",
    "gemini": "Google Gemini",
    "openrouter": "OpenRouter",
    "nous": "Nous Portal",
}
#: подписи групп в попапе выбора модели
PROVIDER_LABELS = {
    "deepseek": "DeepSeek API",
    "openai": "OpenAI API",
    "gemini": "Google Gemini · бесплатно",
    "openrouter": "OpenRouter · бесплатно",
    "nous": "Nous Portal · бесплатно",
    "mock": "Демо (офлайн)",
}
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
      /* кнопка выбора модели — тихая, как вторичная кнопка «Очистить» */
      [data-testid="stPopover"] button[data-testid="stPopoverButton"] {{
          width: 100%; justify-content: center; font-weight: 400 !important;
          font-size: .92rem !important; min-height: 2.2rem !important; height: 2.2rem !important;
          padding: 0 .6rem !important;
          background: var(--secondary-background-color, rgba(27, 32, 44, 1)) !important;
          background-image: none !important;
          color: var(--text-color, #e6e8ef) !important;
          border: 1px solid rgba(230, 232, 239, .2) !important;
          box-shadow: none !important;
      }}
      [data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover {{
          border-color: rgba(230, 232, 239, .35) !important;
      }}
      [data-testid="stPopoverBody"], [role="dialog"] {{ min-width: 16rem; max-width: 16.5rem; }}
      [data-testid="stPopoverBody"] {{ padding: .4rem .3rem !important; }}
      [data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{ gap: .05rem !important; }}
      /* выбор модели: компактный строгий список, галочка у левого края */
      .picker-count {{ font-size: .64rem; opacity: .45; margin: 0 0 .1rem 1.1rem; line-height: 1.2; }}
      [data-testid="stHtml"] {{ margin: 0 !important; }}
      [data-testid="stPopoverBody"] button {{ justify-content: flex-start !important;
                                              text-align: left !important;
                                              min-height: 1.7rem !important;
                                              height: 1.7rem !important;
                                              padding: 0 .45rem !important;
                                              font-size: .82rem !important;
                                              line-height: 1 !important;
                                              border: none !important;
                                              background: transparent !important;
                                              box-shadow: none !important;
                                              border-radius: .3rem !important; }}
      [data-testid="stPopoverBody"] button p {{ font-size: .82rem !important; margin: 0 !important;
                                                white-space: nowrap; overflow: hidden;
                                                text-overflow: ellipsis; max-width: 100%; }}
      [data-testid="stPopoverBody"] button:hover {{ background: rgba(128, 128, 128, .14) !important; }}
      [data-testid="stPopoverBody"] button > div {{ justify-content: flex-start !important;
                                                    text-align: left !important;
                                                    width: 100%; }}

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

      .reasoning-text {{ font-size: .86rem; opacity: .85; line-height: 1.45; white-space: pre-wrap; }}
      .meta-line {{ font-size: .76rem; opacity: .58; }}
      .strategy-hint {{ font-size: .82rem; opacity: .7; margin: -.2rem 0 .6rem 0; }}
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
    """POST и разбор SSE; HTTP-ошибку отдаём событием error."""
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


def selectable_models(models: list[dict]) -> list[dict]:
    """Модели для выбора в UI: офлайн-mock скрыт, если настроен реальный провайдер.

    Mock остаётся только как аварийный вариант — когда других моделей нет.
    """
    real = [item for item in models if item.get("provider") != "mock"]
    return real or list(models)


def nixie_digits(text: str) -> str:
    cells = []
    for char in text:
        if char in ".,":
            cells.append(f'<span class="dot">{char}</span>')
        else:
            cells.append(f'<span class="tube"><span class="glow">{char}</span></span>')
    return f'<div class="nixie">{"".join(cells)}</div>'


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

def model_picker(
    models: list[dict],
    selected_id: str | None,
    *,
    key: str,
) -> str:
    """Единый выбор модели: счётчик и строгий список названий.

    Кнопка `⚙ <модель> ▾`, внутри — «Доступно моделей: N» и плоский список
    без id/URL и подписей; выбранная модель отмечена галочкой у левого края.
    Возвращает выбранный id модели.
    """
    if not models:
        return selected_id or ""

    current = next((item for item in models if item["id"] == selected_id), models[0])
    with st.popover(f"⚙  {current['label']}  ▾", use_container_width=True):
        st.html(f'<div class="picker-count">Моделей: {len(models)}</div>')
        for item in models:
            # место под галочку резервируем всегда — названия выровнены по левому краю
            mark = "✓ " if item["id"] == current["id"] else "\u00a0" * 4
            if st.button(
                f"{mark}{item['label']}",
                key=f"{key}::pick::{item['id']}",
                use_container_width=True,
            ):
                st.session_state[key] = item["id"]
                st.rerun()

    return st.session_state.get(key) or current["id"]
