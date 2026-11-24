"""Локальный mock HTTP API для MCP-сервера в тестах."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

CUSTOMERS = {
    "C-104": {
        "id": "C-104",
        "name": "ООО «Ромашка»",
        "email": "ops@romashka.example",
        "plan": "Pro",
        "balance_rub": 128000,
        "open_tickets": 2,
        "manager": "Анна Смирнова",
        "since": "2024-03-12",
    },
    "C-207": {
        "id": "C-207",
        "name": "ИП Волков",
        "email": "volkov@example.ru",
        "plan": "Start",
        "balance_rub": 0,
        "open_tickets": 5,
        "manager": "Илья Петров",
        "since": "2025-11-02",
    },
    "C-318": {
        "id": "C-318",
        "name": "ООО «Северный ветер»",
        "email": "office@northwind.example",
        "plan": "Enterprise",
        "balance_rub": 540000,
        "open_tickets": 1,
        "manager": "Ольга Ким",
        "since": "2023-07-19",
    },
    "C-422": {
        "id": "C-422",
        "name": "Мария Лебедева",
        "email": "m.lebedeva@example.ru",
        "plan": "Pro",
        "balance_rub": 12400,
        "open_tickets": 3,
        "manager": "Дмитрий Соколов",
        "since": "2025-01-27",
    },
    "C-509": {
        "id": "C-509",
        "name": "ООО «Кибер-Логистика»",
        "email": "ops@cyberlog.example",
        "plan": "Enterprise",
        "balance_rub": 0,
        "open_tickets": 8,
        "manager": "Наталья Орлова",
        "since": "2022-11-08",
    },
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/mock/customers":
            self._send(list(CUSTOMERS.values()))
            return
        customer_id = self.path.rsplit("/", 1)[-1].upper()
        payload = CUSTOMERS.get(customer_id)
        if payload is None:
            self._send({"detail": "Клиент не найден"}, 404)
            return
        self._send(payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/mock/customers":
            self._send({"detail": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        numbers = [
            int(customer_id.split("-", 1)[1])
            for customer_id in CUSTOMERS
            if customer_id.startswith("C-") and customer_id.split("-", 1)[1].isdigit()
        ]
        customer_id = f"C-{max(numbers, default=100) + 1}"
        customer = {
            "id": customer_id,
            "name": payload.get("name", ""),
            "email": payload.get("email", ""),
            "plan": payload.get("plan", ""),
            "balance_rub": int(payload.get("balance_rub") or 0),
            "open_tickets": int(payload.get("open_tickets") or 0),
            "manager": payload.get("manager", ""),
            "since": "2026-11-24",
        }
        CUSTOMERS[customer_id] = customer
        self._send(customer, 201)

    def do_DELETE(self) -> None:  # noqa: N802
        customer_id = self.path.rsplit("/", 1)[-1].upper()
        customer = CUSTOMERS.pop(customer_id, None)
        if customer is None:
            self._send({"detail": "Клиент не найден"}, 404)
            return
        self._send(customer)

    def log_message(self, *_args) -> None:  # noqa: D401
        return


@pytest.fixture(scope="session", autouse=True)
def mock_crm_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    os.environ["MOCK_API_URL"] = f"http://{host}:{port}/mock"
    yield
    server.shutdown()
    thread.join(timeout=2)
