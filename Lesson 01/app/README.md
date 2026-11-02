# AI Chat — Front + API на Docker

Чат-клиент к LLM: потоковые ответы, выбор модели, температуры и глубины reasoning.
Оба сервиса написаны на Python и запускаются одной командой через Docker Compose.

```
        браузер
           │  HTTP 8501
   ┌───────▼────────┐        HTTP/SSE        ┌──────────────┐        ┌──────────────────┐
   │  front (8501)  │ ────────────────────▶  │  api (8000)  │ ─────▶ │ LLM-провайдер     │
   │  Streamlit     │ ◀────────────────────  │  FastAPI     │ ◀───── │ OpenAI-compatible │
   └────────────────┘   reasoning + delta    └──────────────┘  SSE   └──────────────────┘
```

## Быстрый старт

```bash
cd "Lesson 01/app"
cp .env.example .env          # по умолчанию PROVIDER=mock — работает без ключа
docker compose up --build
```

- UI: http://localhost:8501
- API: http://localhost:8000/docs (Swagger)

С реальной моделью — правка `.env`:

```ini
PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...                     # ключ DeepSeek
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

```bash
docker compose up -d --build
```

## Что умеет

- **Потоковый ответ** — SSE-события `reasoning` / `delta` / `done`, текст появляется по мере генерации.
- **Выбор модели** — список берётся из `GET /api/models`; у каждой модели флаги `supports_reasoning` и `supports_temperature`.
- **Температура** — слайдер 0…2; для моделей, которые её не принимают (gpt-5, o-series), параметр не отправляется, а слайдер блокируется.
- **Reasoning** — набор уровней задаётся каталогом модели и уходит в `reasoning_effort`:
  у DeepSeek V4 это `none / minimal / low / medium / high / xhigh / ultra / max`, у OpenAI — `low / medium / high`.
  Неверный для модели уровень API отклоняет с 400, UI предлагает только поддерживаемые.
  Текст размышлений провайдер отдаёт в `reasoning_content` — он стримится отдельным SSE-событием в раскрывающийся блок над ответом.
- **Веб-поиск** — переключатель «🔎 Искать в интернете»: API находит источники (DuckDuckGo keyless, либо Tavily / Brave при наличии ключа), читает текст топ-страниц и передаёт его модели вместе со ссылками; источники показываются под ответом раскрывающимся блоком.
- **Промпт-инженерия** — системный промпт, лимит токенов, экспорт диалога в JSON, очистка чата.

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | Статус и активный провайдер (`ok` / `degraded`) |
| GET | `/api/models` | Каталог моделей и их возможности |
| POST | `/api/chat` | `text/event-stream` со стримом ответа |

Тело `POST /api/chat`:

```json
{
  "model": "gpt-5-mini",
  "messages": [{"role": "user", "content": "Привет"}],
  "temperature": 0.7,
  "reasoning": "medium",
  "max_tokens": 1024,
  "web_search": false
}
```

События SSE:

```
event: reasoning
data: {"text": "сначала разберу вопрос…"}

event: delta
data: {"text": "Привет!"}

event: done
data: {"model": "gpt-5-mini", "elapsed_ms": 1840, "completion_tokens": 42}
```

С `"web_search": true` перед генерацией приходят ещё два события:

```
event: search_start
data: {"query": "курс доллара цб", "backend": "duckduckgo"}

event: search
data: {"query": "...", "backend": "duckduckgo", "results": [{"title": "...", "url": "...", "snippet": "..."}], "error": null}
```

Если поиск не удался, `error` содержит причину, `results` пустой, а ответ модели
всё равно генерируется — поиск никогда не ломает чат.

Ошибки приходят либо HTTP-кодом (до старта стрима), либо событием
`event: error` с `{"message": "...", "kind": "auth|rate_limit|bad_request|..."}`.

Проверка без UI:

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-reasoner","messages":[{"role":"user","content":"привет"}],"reasoning":"medium"}'
```

## Переменные окружения

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PROVIDER` | `mock` | `mock`, `openai` или `deepseek` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | ключ и адрес OpenAI-совместимого шлюза |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | — | ключ и адрес DeepSeek (профиль `deepseek`) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | любой OpenAI-совместимый endpoint |
| `REASONING_PARAM` | `reasoning_effort` | имя параметра reasoning; `""` — не отправлять |
| `MAX_TOKENS_PARAM` | авто | `max_tokens` / `max_completion_tokens` |
| `MODELS_JSON` | — | свой каталог моделей (JSON-файл) |
| `DYNAMIC_MODELS` | `false` | дополнить каталог из `<base_url>/models` |
| `WEB_SEARCH_BACKEND` | `auto` | `off`, `auto`, `duckduckgo`, `brave-html`, `brave-api`, `tavily` |
| `TAVILY_API_KEY` / `BRAVE_API_KEY` | — | ключи поисковых API (иначе keyless DuckDuckGo) |
| `WEB_SEARCH_RESULTS` / `WEB_SEARCH_PAGES` / `WEB_SEARCH_PAGE_CHARS` | `5` / `2` / `3000` | сколько выдачи отдавать и сколько читать со страниц |
| `API_PORT` / `FRONT_PORT` | `8000` / `8501` | порты на хосте |

Свой каталог моделей (`models.json`, путь указать в `MODELS_JSON`) — нужен, если шлюз
предлагает нестандартные имена:

```json
[
  {"id": "deepseek-flash", "label": "DeepSeek V4.1 Flash", "reasoning_levels": ["none", "low", "high", "max"]},
  {"id": "qwen3-32b", "label": "Qwen3 32B", "supports_reasoning": true}
]
```

## Структура

```
app/
├── docker-compose.yml
├── .env.example
├── api/                     # FastAPI
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py          # роуты, SSE
│   │   ├── config.py        # настройки из env
│   │   ├── schemas.py       # валидация запросов
│   │   ├── models_catalog.py
│   │   └── providers/       # openai (реальный), mock (офлайн)
│   └── tests/               # pytest, контракт API
└── front/                   # Streamlit
    ├── Dockerfile
    ├── app.py
    └── .streamlit/config.toml
```

## Тесты

```bash
docker compose exec api pytest -q        # 7 тестов: health, models, стрим, ошибки
```

## Заметки

- Ключи не попадают в образ: `.env` читается Compose-ом и передаётся как переменные окружения; `.env` в `.gitignore`.
- Ollama на хосте: `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODELS` под именами из `ollama list`.
- Контейнеры работают от непривилегированного пользователя (uid 10001).
- Поиск по умолчанию keyless (DuckDuckGo HTML). Публичные выдачи могут отдавать 429/капчу —
  тогда `auto` переключается на следующий бэкенд; для стабильной работы задай `TAVILY_API_KEY`.
