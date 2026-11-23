# Урок 16 — Подключение MCP

## Цель

Показать чат, в котором встроенные инструменты и внешний YouGile подключены
через MCP. Урок открывается отдельной вкладкой в неделе 4 общего UI.

## Схема

```text
Streamlit: вкладка «Урок 16. Подключение MCP»
        │ POST /api/chat  (все MCP-инструменты)
        ▼
FastAPI урока 16 ── stdio ── app.mcp_server (9 встроенных инструментов)
        │
        └──────── Streamable HTTP ── YouGile MCP (47 инструментов)
```

YouGile URL: `https://ru.yougile.com/data/ai/mcp`; OAuth выполняется в Hermes,
токен в чат не передаётся. Новые задачи по умолчанию попадают на доску **AI**
проекта AI в колонку **«Задачи»**; API подставляет `columnId` для
`manage_tasks` и перенаправляет `add_task_without_board`.

`Lesson 16/app/api/app/mcp_server.py` публикует `TOOL_SCHEMAS` и
`DEFAULT_REGISTRY` из `agent_tools.py`. `mcp_agent.py` ведёт цикл
«модель → выбор MCP-инструмента → вызов → наблюдение → ответ», а `mcp_client.py` отвечает за stdio- и HTTP-сессии.

## Проверка

- `POST /api/mcp/inspect` возвращает 9 встроенных инструментов;
- `POST /api/mcp/external/inspect` возвращает 47 инструментов YouGile;
- `get_project_tree` возвращает первый проект, доску и колонку;
- `POST /api/chat` с `model=mock-fast` и вопросом про слова вызывает
  `text_stats` и возвращает наблюдение;
- `POST /api/chat` с примером `17 * 4` вызывает `calculator` и получает `68`;
- неизвестная модель возвращает `400`.

Тесты: **8 passed**.
