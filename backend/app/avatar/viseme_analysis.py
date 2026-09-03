"""Local, language-agnostic viseme classification from raw TTS audio.

Ported from wawa-lipsync (MIT License) https://github.com/wass08/wawa-lipsync,
which itself implements the Oculus LipSync viseme set:
https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/

The original is a browser library that reads an AnalyserNode fed by a live
<audio> element. We don't have that (the transport plays bot audio through an
internal player with no exposed MediaStreamTrack -- see visemeDriver.ts), but
the actual classification logic only needs frequency-band energies + spectral
centroid from each audio chunk, which we already have as raw PCM server-side.
Porting the algorithm to run directly on those bytes sidesteps the browser-audio
access problem entirely and adds no latency (still a synchronous computation on
the same chunk that's about to be sent for playback).

Output is a single discrete viseme name per chunk (not a continuous blend) --
same trade-off as the original. The frontend's existing exponential smoothing
(visemeDriver.ts) turns the string of discrete visemes into smooth motion, the
same way the original's Three.js demo does.
"""

import time
from collections import deque

import numpy as np

VISEMES = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"]
PLOSIVES = {"PP", "DD", "kk", "nn"}

BANDS_HZ = [
    (50, 200),
    (200, 400),
    (400, 800),
    (800, 1500),
    (1500, 2500),
    (2500, 4000),
    (4000, 8000),
]

# AnalyserNode.getByteFrequencyData() defaults -- min/max dB the spectrum gets
# normalized against before the heuristic thresholds below apply to it.
MIN_DECIBELS = -100.0
MAX_DECIBELS = -30.0

HISTORY_SIZE = 10
EARLY_PHASE_MS = 100
MAX_VISEME_DURATION_MS = 100


def _db_normalized_bands(audio: bytes, sample_rate: int) -> tuple[list[float], float] | None:
    """PCM16LE mono -> (7 band energies 0..1, spectral centroid Hz), mirroring
    what AnalyserNode.getByteFrequencyData() would report for the same audio."""
    if not audio:
        return None
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size < 32:
        return None

    windowed = samples * np.blackman(samples.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)

    with np.errstate(divide="ignore"):
        db = 20 * np.log10(np.maximum(spectrum, 1e-12))
    norm = np.clip((db - MIN_DECIBELS) / (MAX_DECIBELS - MIN_DECIBELS), 0.0, 1.0)

    bands = []
    for start, end in BANDS_HZ:
        mask = (freqs >= start) & (freqs < end)
        bands.append(float(np.mean(norm[mask])) if np.any(mask) else 0.0)

    total = float(np.sum(norm))
    centroid = float(np.sum(freqs * norm) / total) if total > 0 else 0.0
    return bands, centroid


class LipsyncAnalyzer:
    """Stateful per-utterance classifier -- create one per TTS utterance (the
    temporal smoothing/hysteresis needs continuity across chunks)."""

    def __init__(self):
        self._history: deque[dict] = deque(maxlen=HISTORY_SIZE)
        self.viseme = "sil"
        self._viseme_started_at = time.monotonic()

    def process_chunk(self, audio: bytes, sample_rate: int) -> str:
        extracted = _db_normalized_bands(audio, sample_rate)
        if extracted is None:
            return self.viseme
        bands, centroid = extracted
        volume = float(np.mean(bands))
        features = {"bands": bands, "volume": volume, "centroid": centroid}
        # Unlike the original (which skips zero-volume chunks so they don't get
        # averaged in), we always append: TTS audio has real digital-silence gaps
        # between words, and skipping them left the rolling average "stuck" at the
        # previous loud volume, which kept the FSM stuck on a non-silent viseme
        # through pauses instead of returning to "sil".
        self._history.append(features)
        self._detect_state(features)
        return self.viseme

    def _averaged(self) -> dict:
        if not self._history:
            return {"volume": 0.0, "centroid": 0.0, "bands": [0.0] * len(BANDS_HZ)}
        n = len(self._history)
        volume = sum(f["volume"] for f in self._history) / n
        centroid = sum(f["centroid"] for f in self._history) / n
        bands = [sum(f["bands"][i] for f in self._history) / n for i in range(len(BANDS_HZ))]
        return {"volume": volume, "centroid": centroid, "bands": bands}

    def _detect_state(self, current: dict) -> None:
        avg = self._averaged()
        d_volume = current["volume"] - avg["volume"]
        d_centroid = current["centroid"] - avg["centroid"]

        scores = self._score_visemes(current, avg, d_volume, d_centroid)
        scores = self._adjust_for_consistency(scores)

        top = max(scores, key=scores.get)
        if top != self.viseme:
            self._viseme_started_at = time.monotonic()
        self.viseme = top

    def _score_visemes(self, current: dict, avg: dict, d_volume: float, d_centroid: float) -> dict[str, float]:
        scores = dict.fromkeys(VISEMES, 0.0)
        b7 = current["bands"][6]
        centroid = current["centroid"]

        if avg["volume"] < 0.2 and current["volume"] < 0.2:
            scores["sil"] = 1.0

        for viseme in PLOSIVES:
            if d_volume < 0.01:
                scores[viseme] -= 0.5
            if avg["volume"] < 0.2:
                scores[viseme] += 0.2
            if d_centroid > 1000:
                scores[viseme] += 0.2

        if 1000 < centroid < 8000:
            if centroid > 7000:
                scores["DD"] += 0.6
            elif centroid > 5000:
                scores["kk"] += 0.6
            elif centroid > 4000:
                scores["PP"] += 1.0
                if b7 > 0.25 and centroid < 6000:
                    scores["DD"] += 1.4
            else:
                scores["nn"] += 0.6

        if d_centroid > 1000 and current["centroid"] > 6000 and avg["centroid"] > 5000:
            if current["bands"][6] > 0.4 and avg["bands"][6] > 0.3:
                scores["FF"] = 0.7

        if avg["volume"] > 0.1 and avg["centroid"] < 6000 and current["centroid"] < 6000:
            b1, b2, b3, b4, b5 = avg["bands"][:5]
            gap_b1_b2 = abs(b1 - b2)
            max_gap = max(abs(b2 - b3), abs(b2 - b4), abs(b3 - b4))

            if b3 > 0.1 or b4 > 0.1:
                if b4 > b3:
                    scores["aa"] = 0.8
                    if b3 > b2:
                        scores["aa"] += 0.2
                if b3 > b2 and b3 > b4:
                    scores["I"] = 0.7
                if gap_b1_b2 < 0.25:
                    scores["U"] = 0.7
                if max_gap < 0.25:
                    scores["O"] = 0.9
                if b2 > b3 > b4:
                    scores["E"] = 1.0
                if b3 < 0.2 and b4 > 0.3:
                    scores["I"] = 0.7
                if b3 > 0.25 and b5 > 0.25:
                    scores["O"] = 0.7
                if b3 < 0.15 and b5 < 0.15:
                    scores["U"] = 0.7

        return scores

    def _adjust_for_consistency(self, scores: dict[str, float]) -> dict[str, float]:
        adjusted = dict(scores)
        duration_ms = (time.monotonic() - self._viseme_started_at) * 1000

        if duration_ms <= EARLY_PHASE_MS:
            boost = 1.3
        elif duration_ms <= MAX_VISEME_DURATION_MS:
            decay_range = MAX_VISEME_DURATION_MS - EARLY_PHASE_MS
            decay = (duration_ms - EARLY_PHASE_MS) / decay_range
            boost = 1.3 - 0.3 * decay
        else:
            excess = duration_ms - MAX_VISEME_DURATION_MS
            boost = max(0.5, 1.0 - excess / 1000)

        if self.viseme in adjusted:
            adjusted[self.viseme] *= boost
        return adjusted
