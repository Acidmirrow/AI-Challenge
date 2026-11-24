# Урок 17 — Первый инструмент MCP

## Цель

Показать полный путь собственного MCP-инструмента:

```text
mock CRM API → MCP-сервер (get_customer, list_customers, create_customer,
delete_customer) → MCP-клиент → агент → ответ
```

## Реализация

- `Lesson 17/app/api/app/main.py` — mock CRM API `/mock/customers/{id}`, HTTP API и агентский чат; начальные данные — 5 клиентов;
- `Lesson 17/app/api/app/mcp_server.py` — MCP-сервер `lesson17-crm`, инструмент `get_customer`;
- `mcp_client.py` — stdio-сессия `initialize` → `tools/list` → `tools/call`;
- `mcp_agent.py` — цикл «модель → инструмент → наблюдение → ответ»;
- `front/lesson17_page.py` — прямой вызов, чат и трасса MCP.

## Инструменты

| Имя | Вход | Возврат |
|---|---|---|
| `get_customer` | `customer_id` (`^C-\d+$`) | `{ok, customer}` |
| `list_customers` | — | `{ok, count, customers}` |
| `create_customer` | `name`, `email`, `plan`; опционально `balance_rub`, `open_tickets`, `manager` | `{ok, customer}` |
| `delete_customer` | `customer_id` (`^C-\d+$`) | `{ok, deleted}` |
| Ошибка | — | `{ok: false, error}` |

## Сценарий

Пользователь спрашивает: «Что с клиентом C-104?». Агент вызывает
`get_customer({"customer_id": "C-104"})`, MCP-сервер обращается к mock CRM API
и возвращает карточку; агент использует имя, тариф, баланс и обращения в ответе.

## Проверка

```bash
curl -X POST http://localhost:8017/api/mcp/inspect
curl -X POST http://localhost:8017/api/mcp/call \
  -H 'Content-Type: application/json' \
  -d '{"tool":"get_customer","arguments":{"customer_id":"C-104"}}'
```

Тесты: **10 passed**.

Изолированный запуск: API `8017`, UI `8517`; в общем UI — раздел
«Первый инструмент MCP (урок 17)» в неделе 4.
