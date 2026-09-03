from app.avatar.viseme_text import (
    MAX_WORD_SPAN_S,
    VisemeTimeline,
    jaw_openness,
    layout_word,
    schedule_word,
    viseme_at,
    weights_at,
)


def test_empty_text_has_no_schedule():
    assert schedule_word("ь ъ, .") == []


def test_vowels_and_consonants_alternate_visemes():
    schedule = schedule_word("мама")
    visemes = [u.viseme for u in schedule]
    assert visemes == ["PP", "aa", "PP", "aa"]


def test_vowels_are_held_longer_than_consonants():
    schedule = schedule_word("па")
    consonant, vowel = schedule
    assert (vowel.end_s - vowel.start_s) > (consonant.end_s - consonant.start_s)


def test_viseme_at_tracks_progress_through_the_word():
    schedule = schedule_word("привет")
    assert viseme_at(schedule, 0.0) == schedule[0].viseme
    mid_last_unit = (schedule[-1].start_s + schedule[-1].end_s) / 2
    assert viseme_at(schedule, mid_last_unit) == schedule[-1].viseme


def test_viseme_at_empty_schedule_returns_none():
    assert viseme_at([], 0.5) is None


def test_viseme_at_past_end_returns_none_so_caller_can_fall_back():
    schedule = schedule_word("да")
    far_future = schedule[-1].end_s + 10.0
    assert viseme_at(schedule, far_future) is None


def test_layout_word_fits_an_explicit_span_exactly():
    schedule = layout_word("привет", start_s=4.0, span_s=0.5)
    assert schedule[0].start_s == 4.0
    assert abs(schedule[-1].end_s - 4.5) < 1e-9


def test_timeline_keeps_every_word_of_a_batch():
    timeline = VisemeTimeline()
    # Inworld can deliver several TTSTextFrames back-to-back; each carries its own
    # playback timestamp and none may be discarded.
    timeline.add_word("да", 1.0)
    timeline.add_word("нет", 1.4)
    timeline.flush()

    assert timeline.viseme_at(1.05) == "DD"  # "да" still present
    assert timeline.viseme_at(1.45) == "nn"  # "нет" reachable too


def test_timeline_refits_a_word_to_end_where_the_next_one_starts():
    timeline = VisemeTimeline()
    timeline.add_word("привет", 2.0)  # estimated span is longer than 0.3s
    timeline.add_word("да", 2.3)

    first_word = [u for u in timeline.units if u.start_s < 2.3]
    assert abs(first_word[-1].end_s - 2.3) < 1e-9
    # ...and the next word is not overrun by the previous one.
    assert timeline.viseme_at(2.31) == "DD"


def test_timeline_does_not_stretch_a_word_across_a_long_pause():
    timeline = VisemeTimeline()
    timeline.add_word("да", 1.0)
    timeline.add_word("нет", 30.0)  # long pause (or a new sentence)

    first_word = [u for u in timeline.units if u.start_s < 30.0]
    assert first_word[-1].end_s <= 1.0 + MAX_WORD_SPAN_S + 1e-9
    # The pause itself has no viseme, so the caller can hold a closed mouth.
    assert timeline.viseme_at(10.0) is None


def test_timeline_words_at_the_same_timestamp_keep_estimated_layout():
    timeline = VisemeTimeline()
    timeline.add_word("да", 5.0)
    timeline.add_word("нет", 5.0)
    timeline.flush()

    assert timeline.viseme_at(5.01) == "DD"
    assert len(timeline.units) == len(schedule_word("да")) + len(schedule_word("нет"))


def test_weights_hold_one_viseme_in_the_middle_of_a_unit():
    schedule = layout_word("мама", start_s=0.0)
    unit = schedule[1]
    mid = (unit.start_s + unit.end_s) / 2
    weights = weights_at(schedule, mid)
    assert weights == {unit.viseme: 1.0}


def test_weights_crossfade_across_a_unit_boundary():
    schedule = layout_word("мама", start_s=0.0)
    boundary = schedule[0].end_s
    weights = weights_at(schedule, boundary)
    assert set(weights) == {schedule[0].viseme, schedule[1].viseme}
    # Half-way through the crossfade both shapes are partially applied and
    # neither is at full weight -- that continuity is what makes the motion
    # smooth instead of stepping between discrete shapes.
    assert all(0.0 < w < 1.0 for w in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 0.2


def test_weights_are_empty_outside_the_schedule():
    schedule = layout_word("да", start_s=1.0)
    assert weights_at(schedule, 0.5) == {}
    assert weights_at(schedule, schedule[-1].end_s + 1.0) == {}


def test_repeated_viseme_does_not_stack_above_one():
    # "нн" is two units mapping to the same viseme; their envelopes overlap.
    schedule = layout_word("нн", start_s=0.0)
    boundary = schedule[0].end_s
    assert weights_at(schedule, boundary) == {"nn": 1.0}


def test_jaw_openness_is_wider_for_open_vowels_than_for_closed_consonants():
    assert jaw_openness({"aa": 1.0}) > jaw_openness({"E": 1.0}) > jaw_openness({"PP": 1.0})
    assert jaw_openness({"sil": 1.0}) == 0.0
    assert jaw_openness({}) == 0.0


def test_timeline_weights_cover_the_pending_word():
    timeline = VisemeTimeline()
    timeline.add_word("да", 2.0)
    # "да" is still the un-committed tail (no next word yet) but must already
    # animate.
    assert timeline.weights_at(2.03)


def test_trim_before_drops_fully_consumed_units():
    timeline = VisemeTimeline()
    timeline.add_word("мама", 0.0)
    timeline.flush()
    total = len(timeline.units)
    cutoff = timeline.units[1].end_s

    timeline.trim_before(cutoff)

    assert len(timeline.units) < total
    assert all(u.end_s >= cutoff for u in timeline.units)
