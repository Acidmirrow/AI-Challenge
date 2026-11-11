from app.tokenizer import count_tokens, count_words, repeat_to_tokens, token_pieces, token_stats, truncate_to_tokens


def test_tokenize_words_and_punctuation() -> None:
    assert [piece.text for piece in token_pieces("Привет, мир!")] == [
        "Привет", ",", "мир", "!",
    ]


def test_count_words_is_not_token_count() -> None:
    text = "Привет, мир!"
    assert count_tokens(text) == 4
    assert count_words(text) == 2


def test_truncate_stops_at_token_boundary() -> None:
    text, tokens = truncate_to_tokens("one two three four", 2)
    assert text == "one two"
    assert tokens == 2
    assert count_tokens(text) == 2


def test_stats_ratio_and_preview() -> None:
    stats = token_stats("one two, three", limit=2)
    assert stats["tokens"] == 4
    assert stats["words"] == 3
    assert stats["chars"] == 14
    assert len(stats["preview"]) == 2
    assert stats["preview_truncated"] is True


def test_repeat_reaches_target_even_when_base_is_long() -> None:
    base = "word " * 100
    grown = repeat_to_tokens(base, 120)
    assert count_tokens(grown) == 120
