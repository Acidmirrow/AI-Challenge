# Урок 20 — Оркестрация MCP

Три MCP-сервера (`orders`, `analytics`, внешний `time`) объединяются в один
каталог инструментов. Агент выбирает инструмент, хаб маршрутизирует вызов в
нужное соединение и корректно переживает отключение одного сервера.

## Что внутри

- `api/app/hub.py` — мультисерверный хаб: соединения, `tools/list`, коллизии
  имён `server__tool`, маршрутизация и закрытие через `AsyncExitStack`.
- `api/app/mcp_orders.py` — собственный сервер заказов.
- `api/app/mcp_analytics.py` — собственный сервер аналитики.
- Внешний `mcp-server-time==2025.8.4` — reference-сервер времени.
- `api/app/mcp_agent.py` — агент с общим каталогом инструментов.
- `api/app/flow.py` — длинный флоу по трём серверам.
- `front/lesson20_page.py` — статус серверов, флоу, чат и трасса вызовов.

## Отказ

В UI выберите сервер в «Смоделировать недоступность серверов». Хаб не
подключает его, но оставляет остальные соединения. Агент получает список
недоступных серверов и не выдумывает их данные. Длинный флоу останавливается на
шаге недоступного сервера с `stopped_server`, `stopped_at` и `reason`.

## Запуск

Изолированно:

```bash
docker compose -f "Lesson 20/app/docker-compose.yml" up -d --build
```

API `8020`, UI `8520`. В общем UI — раздел «Оркестрация MCP (урок 20)».

## Проверка

```bash
curl -X POST http://localhost:8020/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"C-104","amount_rub":100000,"disabled_servers":[]}'
```

Тесты:

```bash
docker compose -f "Lesson 20/app/docker-compose.yml" run --rm api python -m pytest -q
```

Текущий результат: **5 passed**.
