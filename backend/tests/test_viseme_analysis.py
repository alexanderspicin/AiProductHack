import numpy as np

from app.avatar.viseme_analysis import VISEMES, LipsyncAnalyzer

SAMPLE_RATE = 16000


def _tone(freq_hz: float, amplitude: float = 0.6, duration_s: float = 0.05) -> bytes:
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), dtype=np.float32)
    wave = np.sin(2 * np.pi * freq_hz * t) * amplitude
    return (wave * 32767).astype(np.int16).tobytes()


def _silence(duration_s: float = 0.05) -> bytes:
    return _tone(200, amplitude=0.0, duration_s=duration_s)


def test_starts_silent():
    assert LipsyncAnalyzer().viseme == "sil"


def test_empty_audio_keeps_previous_viseme():
    analyzer = LipsyncAnalyzer()
    assert analyzer.process_chunk(b"", SAMPLE_RATE) == "sil"


def test_returned_viseme_is_always_valid():
    analyzer = LipsyncAnalyzer()
    for freq in (150, 800, 2500, 5000):
        result = analyzer.process_chunk(_tone(freq), SAMPLE_RATE)
        assert result in VISEMES


def test_silence_stays_silent_after_a_few_quiet_chunks():
    analyzer = LipsyncAnalyzer()
    for _ in range(5):
        result = analyzer.process_chunk(_silence(), SAMPLE_RATE)
    assert result == "sil"


def test_sustained_loud_tone_eventually_leaves_silence():
    analyzer = LipsyncAnalyzer()
    # Feed several loud chunks so the rolling average volume rises out of the
    # "silence" threshold, same as the JS original needing sustained energy.
    result = "sil"
    for _ in range(10):
        result = analyzer.process_chunk(_tone(500, amplitude=0.9), SAMPLE_RATE)
    assert result != "sil"
