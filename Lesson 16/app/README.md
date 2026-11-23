# Урок 16 — Подключение MCP

Раздел **«Подключение MCP (урок 16)»** в неделе 4 общего UI.
Это отдельная вкладка урока 16 в неделе 4.

## Что подключено

В чате одновременно доступны:

- **9 встроенных MCP-инструментов** — через локальный stdio-сервер;
- **47 инструментов YouGile** — через Streamable HTTP/OAuth.

Модель выбирает инструмент автоматически по задаче; ручного переключателя нет.

YouGile подключается к `https://ru.yougile.com/data/ai/mcp`. OAuth-токен получает
Hermes; в чат его вводить не нужно. Токен хранится только в локальном gitignored
файле и не попадает в репозиторий.

### Встроенные инструменты

- `calculator`;
- `current_time`;
- `text_stats`;
- `currency_rates`;
- `unit_converter`;
- `date_diff`;
- `number_base`;
- `number_stats`;
- `text_hash`.

Схемы инструментов и их обработчики находятся в `app.agent_tools`; API урока 16
является MCP-клиентом: он запускает сервер по stdio, получает `tools/list` и
вызывает `tools/call`.

## Чат

Новые задачи YouGile по умолчанию создаются на доске **«AI»** проекта **AI**
в колонке **«Задачи»**. Если модель не передала `columnId` или вызвала
`add_task_without_board`, API подставляет эту колонку. Значение можно
переопределить через `YOUGILE_DEFAULT_COLUMN_ID`.

1. Модель получает историю диалога и список MCP-инструментов.
2. Модель выбирает инструмент.
3. API вызывает его через MCP.
4. Наблюдение возвращается модели; цикл повторяется до финального ответа.
5. В интерфейсе видны ответ, аргументы и результат каждого вызова.

Для теста без внешней модели выберите `Mock · fast`; для реального ответа —
модель OpenCode Go из списка. Для задач YouGile доступны инструменты
`get_project_tree`, `search_tasks`, `manage_tasks`, `create_board`, CRM,
чат, база знаний и другие; часть инструментов требует открытой вкладки YouGile.

## API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | состояние API и число MCP-инструментов |
| `GET` | `/api/models` | модели провайдера |
| `GET` | `/api/tools` | каталог встроенных инструментов |
| `POST` | `/api/mcp/inspect` | `initialize` + `tools/list` |
| `POST` | `/api/mcp/call` | вызов MCP-инструмента |
| `POST` | `/api/chat` | чат с историей и автоматическим выбором среди всех MCP-инструментов |
| `POST` | `/api/mcp/external/inspect` | `initialize` + `tools/list` внешнего MCP |
| `POST` | `/api/mcp/external/call` | вызов инструмента внешнего MCP |

## Запуск

```bash
cd "Lesson 16/app"
docker compose up -d --build
open http://localhost:8516
curl http://localhost:8016/api/health
```

В общем стеке — `/lesson-16/api/*`; раздел доступен на вкладке недели 4
в общем UI `http://localhost:8500`.

## Тесты

```bash
docker compose -f "Lesson 16/app/docker-compose.yml" run --rm api python -m pytest -q
```

Проверяются MCP handshake, наличие всех 9 инструментов, вызов `text_stats`
и `calculator` через чат, а также неизвестная модель.
Текущий результат: **8 passed**.
