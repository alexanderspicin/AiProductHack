"""Text-driven viseme scheduling for Russian TTS output.

Inworld TTS provides word-level timing, and pipecat turns each word into a
`TTSTextFrame` stamped with a **presentation timestamp** (`frame.pts`,
nanoseconds on the pipeline clock -- see `TTSService._add_word_timestamps`).
That PTS is the moment the word is actually spoken: `BaseOutputTransport`'s
clock task literally sleeps until `pts` before releasing a timed frame. So word
PTS values and the pipeline clock are the one correct time base for lip-sync --
knowing *which word is being spoken right now* beats guessing mouth shape from
the audio spectrum, which is what made the avatar look like "a fish mouth
opening and closing" with no articulation.

Russian orthography is close to phonetic, so a simple per-letter viseme table
works reasonably well without a real phonemizer: each vowel/consonant maps to
one of Audio2Face-3D's Oculus viseme categories (viseme_analysis.py's VISEMES),
weighted by typical relative duration (vowels held longer than consonants), and
laid out across the word's speaking time.

A word's *duration* is not given to us -- only its start. `VisemeTimeline`
therefore keeps the most recent word un-committed ("tail") and, as soon as the
next word's start arrives, re-fits that word's letters to end exactly where the
next word begins. Re-anchoring on every word is what keeps the mouth from
drifting: with only per-letter duration guesses accumulated back-to-back, the
schedule desynchronised from the voice by tens of seconds over one response.
"""

from dataclasses import dataclass

VOWEL_VISEMES = {
    "а": "aa",
    "я": "aa",
    "о": "O",
    "ё": "O",
    "у": "U",
    "ю": "U",
    "ы": "I",
    "и": "I",
    "й": "I",
    "э": "E",
    "е": "E",
}

CONSONANT_VISEMES = {
    "б": "PP",
    "п": "PP",
    "м": "PP",
    "в": "FF",
    "ф": "FF",
    "г": "kk",
    "к": "kk",
    "х": "kk",
    "д": "DD",
    "т": "DD",
    "ж": "CH",
    "ш": "CH",
    "щ": "CH",
    "ч": "CH",
    "з": "SS",
    "с": "SS",
    "ц": "SS",
    "л": "nn",
    "н": "nn",
    "р": "RR",
}

VOWEL_WEIGHT = 2.0
CONSONANT_WEIGHT = 1.0
SECONDS_PER_UNIT = 0.075  # ~average phoneme duration at conversational pace

# A word is never stretched past this, however long the pause after it: the
# leftover time is a real pause in the speech and has to read as a closed mouth,
# not as an absurdly held final vowel.
MAX_WORD_SPAN_S = 1.5

# Half-width of the crossfade between neighbouring visemes. Real articulation is
# coarticulated -- the mouth is already moving toward the next shape while it
# still holds the current one -- and a hard switch every ~75ms is what makes an
# otherwise correct schedule look like it runs at a few frames per second.
BLEND_S = 0.05

# How far each viseme drops the jaw, used for a continuous `mouth_open` (and a
# light ARKit jawOpen) on top of the morph weights, so the motion has amplitude
# variation instead of every shape reading as equally wide open.
JAW_OPENNESS = {
    "sil": 0.0,
    "PP": 0.05,
    "FF": 0.15,
    "TH": 0.25,
    "DD": 0.3,
    "kk": 0.3,
    "CH": 0.3,
    "SS": 0.2,
    "nn": 0.25,
    "RR": 0.3,
    "aa": 1.0,
    "E": 0.6,
    "I": 0.4,
    "O": 0.8,
    "U": 0.45,
}


@dataclass
class VisemeUnit:
    viseme: str
    start_s: float
    end_s: float


def _weighted_units(text: str) -> list[tuple[str, float]]:
    """(viseme, relative duration weight) per pronounceable letter of `text`.

    Letters in neither table (ь/ъ, punctuation, digits, Latin letters,
    whitespace) are silently skipped -- they consume no schedule time, same as
    they'd be roughly silent/neutral in real speech.
    """
    units: list[tuple[str, float]] = []
    for ch in text.lower():
        if ch in VOWEL_VISEMES:
            units.append((VOWEL_VISEMES[ch], VOWEL_WEIGHT))
        elif ch in CONSONANT_VISEMES:
            units.append((CONSONANT_VISEMES[ch], CONSONANT_WEIGHT))
    return units


def layout_word(text: str, start_s: float, span_s: float | None = None) -> list[VisemeUnit]:
    """Break `text` into visemes laid out from `start_s` over `span_s` seconds.

    With `span_s` omitted the word's length is estimated from per-letter
    durations; pass a span once the real one is known (i.e. once the next word's
    start timestamp has arrived) to re-fit the word onto the actual speech.
    """
    units = _weighted_units(text)
    if not units:
        return []

    total_weight = sum(weight for _, weight in units)
    if span_s is None:
        span_s = total_weight * SECONDS_PER_UNIT
    seconds_per_weight = span_s / total_weight

    schedule = []
    t = start_s
    for viseme, weight in units:
        duration = weight * seconds_per_weight
        schedule.append(VisemeUnit(viseme, t, t + duration))
        t += duration
    return schedule


def schedule_word(text: str) -> list[VisemeUnit]:
    """`layout_word` at t=0 with an estimated duration."""
    return layout_word(text, 0.0)


def viseme_at(schedule: list[VisemeUnit], t: float) -> str | None:
    """Viseme active at time t (seconds), or None if t falls outside every unit
    (before the first, after the last, or in a gap between words)."""
    for unit in schedule:
        if unit.start_s <= t < unit.end_s:
            return unit.viseme
    return None


def _smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def _envelope(unit: VisemeUnit, t: float) -> float:
    """Weight of one viseme unit at time t: ramps up around its start, holds,
    ramps down around its end.

    The ramps are centred on the unit boundaries and half a blend wide on each
    side, so two neighbouring units crossfade (each at 0.5 exactly on their
    shared boundary) instead of switching abruptly.
    """
    ramp = min(BLEND_S, (unit.end_s - unit.start_s) / 2)
    if ramp <= 0:
        return 1.0 if unit.start_s <= t < unit.end_s else 0.0
    if t <= unit.start_s - ramp or t >= unit.end_s + ramp:
        return 0.0
    rise = _smoothstep((t - (unit.start_s - ramp)) / (2 * ramp))
    fall = 1.0 - _smoothstep((t - (unit.end_s - ramp)) / (2 * ramp))
    return min(rise, fall)


def weights_at(schedule: list[VisemeUnit], t: float) -> dict[str, float]:
    """Continuous viseme weights at time t: usually one shape at full weight,
    two crossfading near a boundary. Empty dict when nothing is scheduled at t
    (a pause, or before/after the utterance)."""
    weights: dict[str, float] = {}
    for unit in schedule:
        if unit.start_s - BLEND_S > t:
            break  # schedule is ordered; nothing later can be active yet
        weight = _envelope(unit, t)
        if weight > 0.0:
            # Same viseme twice in a row (e.g. "нн", "сс"): the two envelopes
            # crossfade into each other, so summing (clamped) holds the shape
            # instead of dipping to half weight at their shared boundary.
            weights[unit.viseme] = min(1.0, weights.get(unit.viseme, 0.0) + weight)
    return weights


def jaw_openness(weights: dict[str, float]) -> float:
    """Weighted jaw opening (0..1) for a set of viseme weights."""
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return sum(JAW_OPENNESS.get(v, 0.3) * w for v, w in weights.items()) / total


class VisemeTimeline:
    """Absolute-time viseme schedule built from word start timestamps.

    All times are seconds on the pipeline clock -- the same base as
    `TTSTextFrame.pts` -- so `viseme_at(clock_now)` answers "what is the mouth
    doing right now".
    """

    def __init__(self) -> None:
        self._units: list[VisemeUnit] = []
        # Most recent word, laid out with an *estimated* duration and kept apart
        # from `_units` so it can be re-fitted once the next word's start
        # timestamp reveals where it actually ended.
        self._tail: list[VisemeUnit] = []

    def add_word(self, text: str, start_s: float) -> None:
        self._commit_tail(next_word_start_s=start_s)
        self._tail = layout_word(text, start_s)

    def flush(self) -> None:
        """Commit the pending word as-is -- end of utterance, so no next word
        will arrive to tell us where it really ended."""
        self._commit_tail(next_word_start_s=None)

    def _commit_tail(self, next_word_start_s: float | None) -> None:
        if not self._tail:
            return

        tail_start_s = self._tail[0].start_s
        estimated_span_s = self._tail[-1].end_s - tail_start_s
        if next_word_start_s is not None and estimated_span_s > 0:
            # Re-fit onto the real span the voice spent on this word, capped so a
            # long pause stays a pause.
            real_span_s = min(next_word_start_s - tail_start_s, MAX_WORD_SPAN_S)
            if real_span_s > 0:
                factor = real_span_s / estimated_span_s
                self._tail = [
                    VisemeUnit(
                        u.viseme,
                        tail_start_s + (u.start_s - tail_start_s) * factor,
                        tail_start_s + (u.end_s - tail_start_s) * factor,
                    )
                    for u in self._tail
                ]

        self._units.extend(self._tail)
        self._tail = []

    def viseme_at(self, t: float) -> str | None:
        return viseme_at(self._units, t) or viseme_at(self._tail, t)

    def weights_at(self, t: float) -> dict[str, float]:
        """Crossfaded viseme weights at time t (see module-level `weights_at`)."""
        weights = weights_at(self._units, t)
        for viseme, weight in weights_at(self._tail, t).items():
            weights[viseme] = max(weights.get(viseme, 0.0), weight)
        return weights

    def has_words(self) -> bool:
        return bool(self._units or self._tail)

    def trim_before(self, t: float) -> None:
        """Drop already-consumed units so the timeline doesn't grow unboundedly
        across a long response."""
        while self._units and self._units[0].end_s < t:
            self._units.pop(0)

    @property
    def units(self) -> list[VisemeUnit]:
        return self._units + self._tail
