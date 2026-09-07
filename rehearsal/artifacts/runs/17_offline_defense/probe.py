"""Real loopback TTS tests. No paid services; outputs contain only synthetic text."""
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import wave
import numpy as np

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8898"
PHRASES = [
    "Понимаю ваши сомнения. Я уже пробовал похожее решение, но результата не получил. Чем ваш подход отличается?",
    "Павел, мы попробуем поменять план. В понедельник обсудим бюджет, а потом выберем подходящий вариант.",
    "Вы серьёзно? Мне обещали доставку вчера! Хорошо, я готов подождать. Но назовите, пожалуйста, точную дату.",
]


def post(text, voice, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    return urlopen(Request(BASE + "/speak", data=json.dumps({"text": text, "voice": voice}).encode(), headers=headers), timeout=60)


def main():
    result = {"date": "2026-09-07", "api_calls": 0, "api_cost_rub": 0, "runs": [], "http": {}}
    for voice in ["piper", "silero"]:
        for i, text in enumerate(PHRASES):
            start = time.perf_counter()
            with post(text, voice) as response:
                data = json.load(response)
            with urlopen(BASE + data["audio"]) as response:
                payload = response.read()
            with wave.open(io.BytesIO(payload)) as audio:
                rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
                samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float64)
            rms = float(np.sqrt(np.mean((samples / 32768) ** 2)))
            row = {"voice": voice, "phrase": i, "client_s": time.perf_counter() - start,
                   "prepare_s": data["prepare_s"], "tts_s": data["tts_s"], "audio_driver_s": data["timing"]["seconds"],
                   "duration_s": data["timing"]["duration_s"], "sample_rate": rate, "channels": channels,
                   "pcm_bytes": width, "rms": rms, "states_count": len(data["states"]),
                   "unique_states": len(set(data["states"])), "cached": data["cached"]}
            row["pass"] = rms > .003 and channels == 1 and width == 2 and row["unique_states"] > 1
            assert row["pass"], row
            result["runs"].append(row)
            (ROOT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps(row, ensure_ascii=False), flush=True)
    for label, text, voice, origin, expected in [
        ("empty", "", "piper", None, 400), ("too_long", "я" * 501, "piper", None, 400),
        ("unknown_voice", "Привет", "cloud", None, 400),
        ("foreign_origin", "Привет", "piper", "https://example.com", 403),
    ]:
        try:
            post(text, voice, origin)
            raise AssertionError(label)
        except HTTPError as error:
            assert error.code == expected
            result["http"][label] = error.code
    for target in ["/.env", "/assets/../../.env", "/clips/not-a-file.wav"]:
        try:
            urlopen(BASE + target)
            raise AssertionError(target)
        except HTTPError as error:
            assert error.code == 404
            result["http"][target] = 404
    with post(PHRASES[0], "piper") as response:
        assert json.load(response)["cached"] is True
        result["http"]["cached_repeat"] = True
    result["decision"] = "keep: functional local proof; human-perceived Russian lip sync remains unscored"
    (ROOT / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("PASS: six real syntheses, validation, origin, paths and cache", flush=True)


if __name__ == "__main__":
    main()
