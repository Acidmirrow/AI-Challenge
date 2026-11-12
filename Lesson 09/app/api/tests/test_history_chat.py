from app.dialogue import demo_messages
from app.history_chat import answer_question


def test_answer_uses_fact_from_context() -> None:
    answer, sources = answer_question("Какой бюджет проекта?", demo_messages())
    assert "4 850 000" in answer
    assert sources


def test_answer_reports_when_fact_was_dropped() -> None:
    tail = demo_messages()[-2:]
    answer, sources = answer_question("Какие материалы заложены в спецификацию?", tail)
    assert sources == []
    assert "нет сообщения" in answer
