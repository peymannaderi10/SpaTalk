"""Rung 0 of the evaluation ladder (memo §6; LIT §6.6).

Every signal here is free to record and needs no model. Together they are the only thing
that turns "it isn't as human sounding" into a number, and they are the inputs the phase-C
trouble score reads. The hard rule the first test pins: a signal is a count and a closed
label, never a word anybody said.
"""


def test_a_signal_can_never_carry_a_word_anybody_said():
    import pytest

    from spatalk.ops.signals import SignalLog

    log = SignalLog()
    log.record("repeat", script="ask_service")
    log.record("turn_prediction", is_complete=True, probability=0.91, ms=42)
    with pytest.raises(ValueError):
        log.record("repeat", script="what did you have in mind?")   # a sentence, not a key
    with pytest.raises(ValueError):
        log.record("repeat", text="I have a rash after my peel")    # not a detail key at all
    with pytest.raises(ValueError):
        log.record("nonsense", script="ask_service")                # not a kind


def test_counts_roll_up_and_barge_in_and_repeat_is_derived():
    from spatalk.ops.signals import SignalLog

    log = SignalLog()
    log.next_turn()
    log.record("bargein")
    log.next_turn()
    log.record("caller_repeat", similarity=0.94)
    log.next_turn()
    log.record("caller_repeat", similarity=0.91)
    c = log.counts()
    assert c["bargein"] == 1 and c["caller_repeat"] == 2
    # The signal that predicted dissatisfaction in deployed systems: the caller was cut off
    # and said it again. Derived, so it cannot drift from its two parts.
    assert c["bargein_repeat"] == 1


def test_the_log_is_bounded_and_serialises_to_counts_plus_the_tail():
    from spatalk.ops.signals import MAX_SIGNALS, SignalLog

    log = SignalLog()
    for _ in range(MAX_SIGNALS + 50):
        log.record("repeat", script="ask_name")
    doc = log.as_json()
    assert doc["counts"]["repeat"] == MAX_SIGNALS + 50, "counts are exact"
    assert len(doc["signals"]) == MAX_SIGNALS, "the event list is capped"
    assert doc["turns"] == log.turn


def test_a_new_miss_and_a_new_confirmation_are_repairs():
    """`flow.apply` is pure and cannot log, so the drivers derive the repair from what it
    returned. One pure function, two callers, one definition of a repair."""
    from spatalk.brain.flow import Pending, Slots
    from spatalk.ops.signals import signals_for

    before = Slots(flow="new_booking", returning_client=True)
    missed = before.miss("practitioner")
    assert signals_for(before, missed) == [("repair", {"datum": "practitioner"})]

    pending = before.with_(pending=Pending(kind="match", slot="practitioner", value="Helen Courbetis"))
    assert signals_for(before, pending) == [("repair", {"datum": "practitioner"})]
    assert signals_for(before, before) == []
    # A slot that filled is not a repair.
    assert signals_for(before, before.with_(practitioner="any")) == []
