# Урок 19 — Композиция MCP инструментов

## Цель

Показать, как один MCP-сервер предоставляет несколько инструментов и как агент
автоматически проводит данные по цепочке:

```text
search → summarize → saveToFile
```

После каждого шага проверяются `ok` и наличие данных. Если шаг вернул ошибку или
пустой результат, следующие инструменты не вызываются.

## Реализация

- `api/app/mcp_server.py` — MCP-сервер `lesson19-pipeline` с тремя
  инструментами; все инструменты живут на одном сервере.
- `api/app/pipeline.py` — детерминированный агент-оркестратор: вызывает
  инструменты последовательно, передаёт результаты и фиксирует остановку.
- `api/app/main.py` — API, прямой вызов MCP и эндпоинт `/api/pipeline/run`.
- `front/lesson19_page.py` — выбор сценария, автоматический запуск, схема
  цепочки, трасса шагов и итоговый файл.

## MCP-инструменты

| Имя | Вход | Выход |
|---|---|---|
| `search` | `query`; опционально `empty` | `{ok, query, count, empty, results}` |
| `summarize` | `results`; опционально `fail` | `{ok, source_count, summary}` или ошибка |
| `saveToFile` | `filename`, `content`; опционально `fail` | `{ok, filename, path, bytes}` или ошибка |

Инструменты работают с локальным демо-корпусом и файловой папкой
`PIPELINE_OUTPUT_DIR` (в контейнере `/srv/data/output`), внешняя сеть не нужна.

## Сценарии сбоя

| Сценарий API | Что происходит | Где остановка |
|---|---|---|
| `empty_search` | `search` возвращает `results: []` | `search`, `summarize` не вызывается |
| `summarize_error` | `summarize` возвращает `{ok: false}` | `summarize`, `saveToFile` не вызывается |
| `save_error` | `saveToFile` возвращает ошибку | `saveToFile`; результат не объявляется успешным |

В остановленном ответе есть `stopped_at`, `stopped_step`, `reason`, `steps`;
`output` и `file` равны `null`. Агент не придумывает итог, если цепочка не
дошла до сохранения.

## API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | состояние и состав пайплайна |
| `POST` | `/api/pipeline/run` | автоматический запуск всей цепочки |
| `GET` | `/api/pipeline/scenarios` | доступные сценарии |
| `POST` | `/api/mcp/inspect` | регистрация трёх инструментов |
| `POST` | `/api/mcp/call` | прямой вызов инструмента |

Пример:

```bash
curl -X POST http://localhost:8019/api/pipeline/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"MCP","scenario":"none"}'
```

## Запуск

Общий стек: `http://localhost:8500`, раздел «Композиция MCP инструментов
(урок 19)»; API — `http://localhost:8000/lesson-19/api/*`.

Изолированно:

```bash
docker compose -f "Lesson 19/app/docker-compose.yml" up -d --build
```

API `8019`, UI `8519`.

## Проверка

```bash
curl http://localhost:8019/api/health
curl -X POST http://localhost:8019/api/mcp/inspect
curl -X POST http://localhost:8019/api/pipeline/run \
  -H 'Content-Type: application/json' \
  -d '{"query":"MCP","scenario":"empty_search"}'
```

Тесты: **8 passed**. Они проверяют нормальную цепочку, передачу `results` из
`search` в `summarize`, передачу `summary` в `saveToFile`, а также остановку на
пустом `search`, ошибке `summarize` и ошибке `saveToFile` без фиктивного
результата.
