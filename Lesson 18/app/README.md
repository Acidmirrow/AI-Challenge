# Урок 18 — Планировщик и фоновые задачи

Приложение по расписанию собирает метрики через MCP, сохраняет каждый запуск в
SQLite и периодически строит агрегированный отчёт по всем накопленным запускам.

## Что внутри

- `api/app/scheduler.py` — фоновый `asyncio`-цикл: снимок каждые 10 секунд,
  отчёт каждые 30 секунд (настраивается в `config/app.properties`).
- `api/app/mcp_server.py` — MCP-сервер `lesson18-scheduler`:
  `fetch_metrics`, `save_snapshot`, `read_snapshots`.
- `api/app/storage.py` — SQLite-таблицы `snapshots` и `reports`; лимит 500 снимков с вытеснением самого раннего.
- `front/lesson18_page.py` — статус, ручной запуск, снимки и отчёт.

## Запуск

Общий стек: `http://localhost:8500`, раздел «Планировщик и фоновые задачи
(урок 18)»; API — `http://localhost:8000/lesson-18/api/*`.

Изолированно:

```bash
docker compose -f "Lesson 18/app/docker-compose.yml" up -d --build
```

API `8018`, UI `8518`.

## Проверка

```bash
curl http://localhost:8018/api/scheduler/status
curl http://localhost:8018/api/snapshots
curl http://localhost:8018/api/reports/latest
```

Планировщик запускается автоматически через `lifespan` FastAPI. После
нескольких циклов в `snapshots` появляются отдельные записи, а отчёт содержит
`runs` и `series` по всем снимкам периода. Ручные кнопки нужны только для
ускоренной проверки.

Тесты:

```bash
docker compose -f "Lesson 18/app/docker-compose.yml" run --rm api python -m pytest -q
```

Текущий результат: **9 passed**. Кнопка «Очистить результаты» удаляет все снимки и отчёты; лимит снимков — 500, при превышении самый ранний вытесняется.

## Данные

`Lesson 18/app/data/lesson18.db` — SQLite общего стека с WAL; изолированный
запуск использует `lesson18-isolated.db`. Файлы базы и `-wal`/`-shm` исключены
из git; данные сохраняются между запусками и перезапусками контейнера.
