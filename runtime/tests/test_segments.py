from loguru import logger

# 51 characters including the full stop.
S = "Our team can help you with that today and tomorrow."


def _reply(n: int) -> str:
    return " ".join([S] * n)


def test_a_short_reply_passes_through_as_one_part():
    from spatalk.text.segments import split_sms
    assert split_sms("We open at ten today.") == ["We open at ten today."]


def test_an_empty_reply_produces_no_parts():
    from spatalk.text.segments import split_sms
    assert split_sms("   ") == []


def test_a_reply_of_about_450_characters_splits_into_two_parts_at_a_sentence_end():
    from spatalk.text.segments import split_sms
    text = _reply(9)
    assert 440 <= len(text) <= 470
    parts = split_sms(text)
    assert len(parts) == 2
    assert all(len(p) <= 300 for p in parts)
    assert parts[0].endswith(".") and parts[1].endswith(".")
    assert " ".join(parts) == text


def test_a_700_character_reply_yields_two_parts_and_logs_the_rest_dropped():
    from spatalk.text.segments import split_sms
    text = _reply(14)
    assert 700 <= len(text) <= 740
    records: list[str] = []
    handle = logger.add(records.append, level="WARNING")
    try:
        parts = split_sms(text)
    finally:
        logger.remove(handle)
    assert len(parts) == 2
    assert all(len(p) <= 300 for p in parts)
    assert len(" ".join(parts)) < len(text)
    assert any("dropped" in r for r in records)


def test_no_part_ever_ends_mid_word():
    from spatalk.text.segments import split_sms
    words = ("appointment consultation rejuvenation microdermabrasion " * 12).split()
    text = " ".join(words) + "."
    parts = split_sms(text, limit=120)
    assert len(parts) == 2
    for p in parts:
        assert len(p) <= 120
        for w in p.rstrip(".").split():
            assert w in words


def test_a_single_long_sentence_is_split_at_a_word_boundary():
    from spatalk.text.segments import split_sms
    words = ("the team will call you back about this " * 12).split()
    text = " ".join(words) + "."
    parts = split_sms(text, limit=200)
    assert len(parts) == 2
    assert all(len(p) <= 200 for p in parts)
    assert parts[0].split()[-1] in words
    assert text.startswith(parts[0])
