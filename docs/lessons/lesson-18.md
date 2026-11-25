# Урок 18 — Планировщик и фоновые задачи

## Цель

Собрать приложение, которое **само по расписанию** вызывает MCP-инструменты,
сохраняет каждый запуск и периодически строит сводку по накопленным данным.

```text
asyncio-планировщик
  → fetch_metrics   (MCP, новый снимок)
  → save_snapshot   (MCP, SQLite)
  → read_snapshots  (MCP, все снимки периода)
  → агрегированный отчёт → SQLite → UI
```

## Реализация

- `Lesson 18/app/api/app/scheduler.py` — фоновый `asyncio`-цикл: снимок каждые
  `scheduler.snapshot.interval.s` секунд, отчёт каждые
  `scheduler.report.interval.s` секунд.
- `mcp_server.py` — собственный MCP-сервер `lesson18-scheduler` с тремя
  инструментами; работает через stdio.
- `storage.py` — SQLite: таблицы `snapshots` и `reports`, WAL, сохранение
  каждого запуска и чтение периода; лимит 500 снимков с вытеснением самого раннего.
- `POST /api/scheduler/clear` — кнопка очистки накопленных снимков и отчётов.
- `main.py` — API, запуск планировщика через `lifespan`, ручные кнопки,
  статус, снимки, отчёты и прямой вызов MCP.
- `front/lesson18_page.py` — статус фонового цикла, таблица снимков,
  последний отчёт и ручные действия.

## MCP-инструменты

| Имя | Вход | Возврат |
|---|---|---|
| `fetch_metrics` | `source` (опционально) | `{ok, snapshot}` |
| `save_snapshot` | `snapshot` с `run_id`, `collected_at` и метриками | `{ok, snapshot, total, limit, trimmed}` |
| `read_snapshots` | `since`, `until`, `limit` | `{ok, count, total, snapshots}` |
| Ошибка | — | `{ok: false, error}` |

Метрики демо-сервиса: `cpu_pct`, `requests`, `errors`, `latency_ms`,
`queue_depth`, `run_id`, `collected_at`, `source`.

## API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | состояние приложения и планировщика |
| `GET` | `/api/scheduler/status` | запущен ли цикл, интервалы, последние запуски |
| `POST` | `/api/scheduler/run` | один цикл вручную |
| `POST` | `/api/scheduler/report` | собрать отчёт вручную |
| `POST` | `/api/scheduler/clear` | очистить все снимки и отчёты |
| `GET` | `/api/snapshots` | накопленные снимки |
| `GET` | `/api/reports/latest` | последний агрегированный отчёт |
| `GET` | `/api/reports` | история отчётов |
| `POST` | `/api/mcp/inspect` | регистрация MCP-инструментов |
| `POST` | `/api/mcp/call` | прямой вызов MCP-инструмента |

Отчёт включает `runs`, `snapshot_ids`, `first_run_at`, `last_run_at`,
`requests_total`, `errors_total`, `error_rate_pct`, `cpu_avg`, `cpu_max`,
`latency_avg`, `queue_avg` и `series` по всем снимкам периода.

## Запуск

Общий стек:

```bash
docker compose up -d --build lesson-18-api gateway front
```

- UI: `http://localhost:8500` → «Планировщик и фоновые задачи (урок 18)».
- API через шлюз: `http://localhost:8000/lesson-18/api/*`.

Изолированный запуск:

```bash
docker compose -f "Lesson 18/app/docker-compose.yml" up -d --build
```

API `8018`, UI `8518`.

## Проверка

```bash
curl http://localhost:8018/api/health
curl http://localhost:8018/api/scheduler/status
curl -X POST http://localhost:8018/api/scheduler/run
curl http://localhost:8018/api/snapshots
curl http://localhost:8018/api/reports/latest
```

Тесты: **9 passed**. Они проверяют регистрацию трёх MCP-инструментов,
прямое сохранение и чтение, автоматические запуски без ручного вмешательства,
накопление снимков, лимит 500 с вытеснением самого раннего, очистку и то, что
отчёт агрегирует **все** запуски периода, а не только последний.

Данные общего стека хранятся в `Lesson 18/app/data/lesson18.db`; изолированный
запуск использует `lesson18-isolated.db` в той же папке. Оба файла переживают
перезапуск контейнера и не коммитятся.
