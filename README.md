# AI Challenge — 35 уроков

Учебный проект: каждый урок — отдельное приложение (FastAPI + Streamlit), но весь
курс открывается **с одного хоста и одного порта**.

```
UI:   http://localhost:8500     # общий интерфейс, разделы всех уроков
API:  http://localhost:8000     # шлюз: /lesson-01/api/..., /lesson-02/api/...
```

## Как это устроено

```
docker-compose.yml        # единственный стек: 4 API + шлюз + один фронт
gateway/                  # прокси: разводит /lesson-0X/api/* по сервисам
Lesson 01/app/            # код урока 01: api/ (FastAPI) + front/ (страницы) + config/
Lesson 02/app/            # код урока 02 — отдельно, ничего общего с уроком 01
Lesson 03/app/
Lesson 04/app/
```

Логика каждого урока живёт **в своей папке**: у него собственные `app/api/app/*`,
`app/config/*`, тесты и `docker-compose.yml` для изолированной работы. Общий стек
ничего не смешивает — он только собирает эти приложения и публикует их за одним
адресом.

| Что | Адрес снаружи | Внутри стека |
|---|---|---|
| API урока 01 | `http://localhost:8000/lesson-01/api/health` | `lesson-01-api:8000` |
| API урока 02 | `http://localhost:8000/lesson-02/api/health` | `lesson-02-api:8000` |
| API урока 03 | `http://localhost:8000/lesson-03/api/health` | `lesson-03-api:8000` |
| API урока 04 | `http://localhost:8000/lesson-04/api/health` | `lesson-04-api:8000` |
| Общий UI | `http://localhost:8500` | `front:8501` |

Шлюз проксирует запросы всех методов, включая потоковые ответы чата
(`text/event-stream`), поэтому стриминг работает так же, как при прямом обращении
к API урока. Список адресов доступен по `GET /api/lessons`.

## Быстрый старт

```bash
docker compose up -d --build
open http://localhost:8500        # macOS
```

Порты можно переопределить: `API_PORT=8080 FRONT_PORT=8600 docker compose up -d`.

## Ключи и конфигурация

У каждого урока свой `Lesson 0X/app/config/`:

- `app.properties` — в git, без секретов (провайдер, base_url, лимиты);
- `secrets.properties` — gitignored, монтируется в контейнер при деплое
  (`deepseek.api.key`, `groq.api.key`, `gemini.api.key`, `openrouter.api.key`).

Пример лежит рядом: `secrets.properties.example`.

## Отдельная работа над одним уроком

Стек курса занимает порты 8000 и 8500, поэтому для изолированного запуска урока
сначала остановите общий:

```bash
docker compose down
cd "Lesson 04/app" && docker compose up -d    # UI :8504, API :8004
```

У каждого урока собственные порты (01 → 8000/8501, 02 → 8002/8502, 03 → 8003/8503,
04 → 8004/8504) и собственные тесты:

```bash
cd "Lesson 04/app" && docker compose run --rm api python -m pytest -q
```
