# Lesson 02 — Форматы ответа модели

Один и тот же промпт прогоняется через пять способов задать формат, и каждый результат
разбирается, валидируется по JSON Schema и показывается в UI. Стек тот же, что в первом
уроке: FastAPI + Streamlit на Python, всё в Docker.

```
      промпт + схема
 браузер ──▶ front (Streamlit, 8502) ──▶ api (FastAPI, 8002) ──▶ DeepSeek / OpenAI
                                          │
                              формат: text | markdown | json_object |
                                     json_schema | tool_call
                                          │
                          разбор → JSON Schema валидация
```

## Один интерфейс для двух уроков

Фронт этого приложения обслуживает обе лаборатории: в сайдбаре переключатель
**«Чат (урок 01)» / «Форматы ответа (урок 02)»**.

- Чат ходит в API первого урока (`ai-chat`, порт 8000) — код урока 01 не менялся;
  адрес задаётся переменной `CHAT_API_BASE_URL` (по умолчанию
  `http://host.docker.internal:8000`, для этого в compose добавлен `extra_hosts`).
- Форматы ходят в собственный API (`format-lab`, порт 8002) через `FORMAT_API_BASE_URL`.
- Выбранный источник модели (Демо/DeepSeek) и сама модель хранятся в общем состоянии
  (`ui_source` / `ui_model`), поэтому переключение разделов их не сбрасывает.
- Чтобы вкладка чата работала, стек первого урока должен быть запущен:
  `cd "Lesson 01/app" && docker compose up -d`.

```
front (8502) ──▶ format-lab api (8002)   # форматы
              └▶ ai-chat api (8000)       # чат, host.docker.internal
```

Модули фронта: `app.py` (навигация), `chat_page.py` (урок 01), `format_page.py`
(урок 02), `common.py` (адреса API, SSE-клиент, стили).

## Быстрый старт

```bash
cd "Lesson 02/app"
cp config/secrets.properties.example config/secrets.properties   # вписать токен
docker compose up -d --build
```

- UI: http://localhost:8502
- API: http://localhost:8002/docs

Без токена тоже работает: переключи «Источник модели» на `Демо (mock)` — провайдер
сгенерирует структуру локально.

## Форматы

| Формат | Что отправляем | Что проверяем |
|---|---|---|
| `text` | ничего, обычный чат | — (базовая линия) |
| `markdown` | системный промпт про таблицы | — |
| `json_object` | `response_format={"type":"json_object"}` + схема в промпте | JSON-парсинг + `jsonschema` |
| `json_schema` | `response_format={"type":"json_schema","strict":true}` | тот же валидатор |
| `tool_call` | `tools=[…]` + `tool_choice` | аргументы инструмента как JSON |

**Проверено на DeepSeek V4.1 Flash** (`api.deepseek.com`):

- `json_object` — работает, JSON приходит чистым;
- `json_schema` — провайдер отвечает `400 This response_format type is unavailable now`,
  ошибка показывается в UI как есть с подсказкой «попробуй json_object или tool_call»;
- `tool_call` — работает: при `reasoning=off` уходит принудительный
  `tool_choice={"type":"function",…}`, а в thinking-режиме DeepSeek такой выбор
  запрещает (`Thinking mode does not support this tool_choice`), поэтому автоматически
  отправляется `tool_choice=auto` и в результате появляется пометка.

## Ограничения ответа и сравнение

В сайдбаре четыре ручки, которые и есть предмет урока:

| Ручка | Что делает | Как проверить |
|---|---|---|
| **Описание формата (system)** | поле предзаполнено встроенной подсказкой формата и уходит первым system-сообщением; шаблоны «Три пункта», «Markdown-таблица», «JSON без пояснений», «Одна строка» подставляются одной кнопкой, текст можно править | «Три пункта» → ответ нумерованный тремя пунктами, без шаблона — одна фраза. Во вкладке «Что отправлено» видно `system`-сообщение |
| **Max tokens** | ограничивает длину ответа; в UI ползунок 100–10000 с шагом 100 и табло со значением, API не принимает больше 10000 | `100` → `complete=100`, `finish_reason=length`; `10000` → ответ целиком, `stop`; `10001` → `422` |
| **Stop sequence** | обрывает генерацию на последовательности (через запятую, `\n` = перевод строки) | `5` на «посчитай 1–10» → `1, 2, 3, 4,`, `finish_reason=stop` |
| **Строгая схема** | `json_object` + JSON Schema + валидация | ответ парсится и проходит схему |

Плюс:

- **«Парсится кодом»** — автоматический вердикт для любого формата: `json.loads`,
  затем разбор Markdown-таблицы, иначе «структуры нет». Раньше это приходилось смотреть руками.
- **«⚖ Сравнить варианты»** — прогоняет три режима (без ограничений / с ограничениями /
  со строгой схемой) по одному разу и показывает таблицу: токены, `finish`, парсится, валидна схема.

⚠️ `json_schema` (strict) DeepSeek не принимает — отвечает
`400 invalid_request_error: This response_format type is unavailable now`.
Поэтому модель помечена `supports_json_schema=false`, и API сам понижает формат:
уходит `response_format={"type":"json_object"}` + JSON Schema в system-описании,
а схема проверяется локально (`Draft202012Validator`). В UI это видно подсказкой
под селектором формата и заметкой в статусе прогона. Для моделей с поддержкой
(`gpt-5`, mock) по-прежнему отправляется честный strict-конверт.

⚠️ Нюанс DeepSeek: «не передавать параметр» означает thinking включён, бюджет `max_tokens`
уходит на размышления, контент приходит пустым. Поэтому в UI уровня `off` больше нет —
предлагаются только явные уровни, по умолчанию `none` (рассуждения выключены).

⚠️ Если лимит «не работает», проверьте три вещи: выбран реальный провайдер (mock-ответ
теперь тоже обрезается по `max_tokens`), reasoning стоит `none`, и значение на табло
совпадает с тем, что в «Что отправлено» → `max_tokens`.

### Пример: планеты Солнечной системы

В UI это готовый набор: **«Шаблон промпта → Планеты Солнечной системы»** — подставляет
промпт ниже и автоматически выбирает пресет схемы `planets` (`GET /api/presets`).
Шаблоны промптов: планеты, фильмы, тикеты поддержки, товары. Каждый промпт
перечисляет несколько объектов (3 фильма, 3 тикета, 3 товара, 8 планет), а схема
описывает массив этих объектов — поэтому ответ наглядно показывает разницу форматов.

Промпт:

```
Перечисли планеты Солнечной системы по порядку от Солнца: Меркурий, Венера, Земля,
Марс, Юпитер, Сатурн, Уран, Нептун. Для каждой укажи номер, название, тип
(terrestrial / gas_giant / ice_giant), число спутников и расстояние от Солнца в а.е.
```

Схема:

```json
{
  "type": "object",
  "properties": {
    "planets": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "position": {"type": "integer", "minimum": 1, "maximum": 8},
          "name": {"type": "string"},
          "type": {"type": "string", "enum": ["terrestrial", "gas_giant", "ice_giant"]},
          "moons": {"type": "integer", "minimum": 0},
          "distance_au": {"type": "number", "exclusiveMinimum": 0}
        },
        "required": ["position", "name", "type"],
        "additionalProperties": false
      }
    },
    "count": {"type": "integer", "minimum": 1}
  },
  "required": ["planets"],
  "additionalProperties": false
}
```

Стоп-сиквенс — пятая планета: `Юпитер` (в поле «Stop sequence»).

Что получается:

| Формат | stop | Результат |
|---|---|---|
| `text` | `Юпитер` | 4 планеты и оборванная строка `5.` — `finish_reason=stop` |
| `json_object` | нет | 8 планет, JSON парсится, схема соблюдена |
| `json_object` | `Юпитер` | обрыв внутри строки `"position":5,"name":"` → `Unterminated string`, парсинг падает |

Последняя строка — главный вывод: stop sequence рубит поток байтов и несовместим
со строгим JSON; для структурированного ответа ограничивают `max_tokens` и схему,
а stop оставляют текстовым форматам.

## Валидация ответа

Ответ парсится, лишние ```-обёртки снимаются, затем проверяется по Draft 2020-12.
Ошибки `required` и `additionalProperties` разворачиваются по полям, чтобы в таблице
было видно конкретный ключ:

```
path  validator            message
year  required             обязательное поле отсутствует
extra additionalProperties лишнее поле — схема запрещает дополнительные ключи
```

Повторного прохода нет: ответ модели возвращается как есть, а нарушения показываются
во вкладке «Валидация» — так видно её реальное поведение, без «дожима» промптом.

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | статус, провайдер, число форматов, прочитанные конфиг-файлы |
| GET | `/api/formats` | пять форматов и их признаки (`needs_schema`, `uses_tools`) |
| GET | `/api/presets` | готовые схемы-списки: фильмы, тикеты, планеты, товары |
| GET | `/api/models` | модели и их возможности |
| POST | `/api/format/run` | `text/event-stream`: прогон формата |

Тело запроса:

```json
{
  "format": "json_object",
  "model": "deepseek-flash",
  "prompt": "Матрица, 1999 год, рейтинг 8.7",
  "schema": {"type": "object", "properties": {"title": {"type": "string"}}},
  "schema_name": "movie",
  "tool_name": "save_movie",
  "temperature": 0.2,
  "reasoning": "none",
  "max_tokens": 800,
  "system_prompt": "Ответь ровно тремя пунктами",
  "stop": ["\n3."]
}
```

События:

```
event: start    {"format":"json_object","model":"deepseek-flash","notes":[]}
event: delta    {"kind":"text","text":"{\"title\": "}       # или kind="tool_args"
event: run_result {"parse_check":{"ok":true,"kind":"json"},"validation":{"valid":true}}
event: result   {"runs":1,"results":[{…}],"summary":{"avg_completion_tokens":39.0,
                 "finish_reasons":{"stop":1},"parseable":1,"valid":1},
                 "parsed":{…},"validation":{"valid":true,"applicable":true},
                 "parse_check":{"ok":true,"kind":"json"},"sent":{…}}
event: error    {"message":"…","kind":"bad_request"}
```

## Конфигурация

Как в первом уроке: `config/app.properties` (в git) + `config/secrets.properties`
(в `.gitignore`, монтируется при деплое), приоритет env > `.env` > docker secrets > properties.

```properties
provider = deepseek
deepseek.base.url = https://api.deepseek.com/v1
```

## Структура

```
Lesson 02/app/
├── docker-compose.yml
├── config/{app.properties, secrets.properties.example}
├── api/
│   ├── app/{main,config,properties,formats,validation,schemas,models_catalog}.py
│   ├── app/providers/{base,openai_provider,mock_provider}.py
│   └── tests/{test_formats,test_api}.py
└── front/{app.py, .streamlit/config.toml}
```

## Тесты

```bash
docker compose exec api pytest -q     # 37 тестов
```

Покрыто: сборка запроса для каждого формата, парсинг (включая ```-обёртки и битый JSON),
разворачивание ошибок схемы, SSE-контракт, tool-аргументы, отсутствие повторного прохода
при нарушении схемы, потолок `max_tokens` (10000 — 200, 10001 — 422),
неизвестные модель/формат, некорректная схема.

## Что важно понять из урока

1. Формат — это часть контракта, а не пожелание в промпте: текстовый ответ нельзя
   надёжно парсить, `json_object` уже даёт валидный JSON, а `json_schema`/tool call дают
   гарантии на стороне провайдера (если он их поддерживает).
2. Проверять ответ нужно всегда: даже `json_object` может вернуть лишние ключи или
   не то число, а `additionalProperties: false` и `enum` ловят это автоматически.
3. Ошибку провайдера нельзя прятать: `json_schema` у DeepSeek недоступен — UI говорит об
   этом прямо и предлагает рабочий формат.
