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
cp config/secrets.properties.example config/secrets.properties   # вписать токены (файл в .gitignore)
docker compose up -d --build
```

- UI: http://localhost:8501
- API: http://localhost:8000/docs (Swagger)

Без ключа тоже работает: в `config/app.properties` можно поставить `provider = mock`.

## Конфигурация: properties-файлы

Все настройки читаются из двух файлов, смонтированных в контейнер (`./config:/srv/config:ro`):

| Файл | В git | Назначение |
|---|---|---|
| `config/app.properties` | да | обычная конфигурация: провайдер, base_url, поиск, лимиты |
| `config/secrets.properties` | **нет** (`.gitignore`) | токены: `deepseek.api.key`, `openai.api.key`, `tavily.api.key`, `brave.api.key` |
| `config/secrets.properties.example` | да | шаблон без значений |

Формат — Java-properties: `ключ = значение`, комментарии `#` и `!`, значения можно брать в кавычки.
Ключи нормализуются, поэтому эквивалентны все варианты:

```properties
deepseek.api.key = sk-...
deepseek-api-key = sk-...
DEEPSEEK_API_KEY = sk-...
```

Приоритет (первый побеждает): аргументы процесса → переменные окружения → `.env` → docker secrets →
`secrets.properties` → `app.properties` → значения по умолчанию.

Деплой на сервере: в репозитории только `app.properties` и `*.example`; реальный
`secrets.properties` создаётся на машине один раз и монтируется при `docker compose up`.
В образ секреты не попадают, в `docker inspect` их тоже нет — только файл на хосте.

Файлы, из которых реально прочитана конфигурация, видны в `/api/health`:

```json
{"status": "ok", "provider": "deepseek @ https://api.deepseek.com/v1",
 "config_files": ["/srv/config/app.properties", "/srv/config/secrets.properties"]}
```

## Что умеет

- **Потоковый ответ** — SSE-события `reasoning` / `delta` / `done`, текст появляется по мере генерации.
- **Выбор модели** — список берётся из `GET /api/models`; у каждой модели флаги `supports_reasoning` и `supports_temperature`.
- **Температура** — слайдер 0…2; для моделей, которые её не принимают (gpt-5, o-series), параметр не отправляется, а слайдер блокируется.
- **Reasoning** — набор уровней задаётся каталогом модели и уходит в `reasoning_effort`:
  у DeepSeek V4 это `none / minimal / low / medium / high / xhigh / ultra / max`, у OpenAI — `low / medium / high`.
  Неверный для модели уровень API отклоняет с 400, UI предлагает только поддерживаемые.
  Текст размышлений провайдер отдаёт в `reasoning_content` — он стримится отдельным SSE-событием в раскрывающийся блок над ответом.
- **Переключение mock / API** — радио «Источник модели» в сайдбаре: офлайн-демо или реальный провайдер. Каждая модель в `/api/models` несёт поле `provider`, поэтому выбор модели переключает и бэкенд.
- **Выбор модели** — выпадающий список прямо под кнопкой (Streamlit `st.popover`): модели выбранного источника, галочка на текущей, id и уровни reasoning у каждой.
- **Слайдеры в стиле ламповых часов** — температура и max tokens: тёмные «трубки» с янтарным свечением и глоу-ползунком.
- **Веб-поиск** — переключатель «🔎 Искать в интернете» + выбор провайдера: `Авто`, DuckDuckGo, Bing, Brave (HTML) работают без ключа, Brave API и Tavily включаются при наличии ключа. API читает текст топ-страниц и передаёт его модели вместе со ссылками; источники показываются под ответом раскрывающимся блоком.
- **Промпт-инженерия** — системный промпт, лимит токенов, экспорт диалога в JSON, очистка чата.

## Бесплатные провайдеры

Кроме основного провайдера (`provider` в `app.properties`) можно подключить модели
с бесплатным тарифом — ключ выдаётся без карты:

| Провайдер | Ключ в `config/secrets.properties` | Где взять | Фильтр моделей |
|---|---|---|---|
| Google AI Studio | `gemini.api.key =` | https://aistudio.google.com/apikey | `gemini-*` без embedding/tts/image |
| Groq | `groq.api.key =` | https://console.groq.com/keys | `llama*`, `gpt-oss*`, `qwen*` |
| OpenRouter | `openrouter.api.key =` | https://openrouter.ai/keys | только `:free` |

Список моделей не хардкодится: при старте API читает `/models` каждого провайдера,
у которого есть ключ, и подключает до трёх подходящих моделей. Перечитать каталог
без перезапуска контейнера:

```bash
curl -X POST http://localhost:8000/api/models/refresh
```

В UI такие модели видны в «Источник модели» — там появляется отдельный пункт
провайдера (`groq`), а в выпадающем списке модель с пометкой «(free)».

### Обрыв ответа по лимиту токенов

Событие `done` в SSE содержит `finish_reason`. Если модель не успела закончить и
вернула `length`, UI пишет в мете «⚠️ обрезано по max_tokens» и показывает
предупреждение: «Ответ не уместился в лимит max_tokens = N — текст оборван.
Увеличьте «Max tokens» и повторите запрос». Mock-провайдер ведёт себя так же:
режет ответ по бюджету и возвращает `finish_reason=length`.

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | Статус и активный провайдер (`ok` / `degraded`) |
| GET | `/api/models` | Каталог моделей и их возможности |
| GET | `/api/search/backends` | Доступные поисковые бэкенды и наличие ключей |
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

Провайдер можно переопределить на конкретный запрос: `"search_backend": "bing"`.
Неизвестный бэкенд или отсутствующий ключ — HTTP 400 с текстом причины.

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
| `WEB_SEARCH_BACKEND` | `auto` | `off`, `auto`, `duckduckgo`, `bing`, `brave-html`, `brave-api`, `tavily` — стартовый бэкенд, переключается в UI |
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

- Ключи не попадают ни в образ, ни в git: только `config/secrets.properties` на хосте, смонтированный read-only. `.env` теперь держит лишь порты Compose.
- Ollama на хосте: `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODELS` под именами из `ollama list`.
- Контейнеры работают от непривилегированного пользователя (uid 10001).
- Поиск по умолчанию keyless (DuckDuckGo HTML). Публичные выдачи могут отдавать 429/капчу —
  тогда `auto` переключается на следующий бэкенд; для стабильной работы задай `TAVILY_API_KEY`.
