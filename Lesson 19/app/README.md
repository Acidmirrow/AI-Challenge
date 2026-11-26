# Урок 19 — Композиция MCP инструментов

Один MCP-сервер предоставляет `search`, `summarize` и `saveToFile`; агент
автоматически выполняет цепочку и останавливается при ошибке или пустом
результате.

## Что внутри

- `api/app/mcp_server.py` — MCP-сервер `lesson19-pipeline` с тремя инструментами.
- `api/app/pipeline.py` — последовательный агент-оркестратор с проверкой данных
  после каждого шага.
- `api/app/main.py` — `/api/pipeline/run`, `/api/mcp/inspect`, `/api/mcp/call`.
- `front/lesson19_page.py` — запуск, схема `search → summarize → saveToFile`,
  трасса и результат.

## Сценарии

- `empty_search` — `search` возвращает пустой массив, `summarize` не вызывается.
- `summarize_error` — `summarize` возвращает ошибку, `saveToFile` не вызывается.
- `save_error` — ошибка сохранения; итоговый результат не выдаётся.
- `none` — все три шага успешно завершаются.

При остановке ответ содержит `stopped_at`, `stopped_step`, `reason` и `steps`;
поля `output` и `file` равны `null`.

## Запуск

Общий UI: `http://localhost:8500`, раздел «Композиция MCP инструментов (урок 19)».
API через шлюз: `http://localhost:8000/lesson-19/api/*`.

Изолированно:

```bash
docker compose -f "Lesson 19/app/docker-compose.yml" up -d --build
```

API `8019`, UI `8519`.

## Проверка

```bash
curl -X POST http://localhost:8019/api/pipeline/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"MCP","scenario":"none"}'

curl -X POST http://localhost:8019/api/pipeline/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"MCP","scenario":"summarize_error"}'
```

Тесты: **8 passed**.

Результат `saveToFile` сохраняется в `Lesson 19/app/data/output/`; содержимое
этой папки исключено из git.
