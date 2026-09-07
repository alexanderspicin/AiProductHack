"""Free, local preflight. Never calls OpenAI or Inworld. Run before the demo."""
import argparse
import asyncio
import json
import time
import wave


async def check(audio_path, whisper, fast=False):
    import os
    from pathlib import Path
    os.environ.setdefault('NLTK_DATA', str(Path('models/nltk_data').resolve()))
    import nltk
    nltk.data.find('tokenizers/punkt_tab/english')
    from backend.app.pipeline.turn_detection import make_user_aggregator_params
    params = make_user_aggregator_params(fast_interrupt=fast)
    vad = params.vad_analyzer
    vad.set_sample_rate(16000)
    turn = params.user_turn_strategies.stop[0]._turn_analyzer
    turn.set_sample_rate(16000)
    result = {"vad": type(vad).__name__, "turn_analyzer": type(turn).__name__, "external_api_calls": 0}
    if audio_path:
        with wave.open(audio_path, "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000), "Need PCM16 mono 16 kHz WAV"
            audio = wav.readframes(wav.getnframes())
        states = set()
        import numpy as np
        first_energy = None
        first_speaking = None
        for start in range(0, len(audio), 1024):
            chunk = audio[start:start + 1024].ljust(1024, b'\0')
            rms = float(np.sqrt(np.mean((np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768) ** 2)))
            if rms > .008 and first_energy is None:
                first_energy = round(start / 32)
            state = await vad.analyze_audio(chunk)
            if str(state) == 'VADState.SPEAKING' and first_speaking is None:
                first_speaking = round((start + 1024) / 32)
            states.add(str(state))
            turn.append_audio(chunk, is_speech=True)
        began = time.perf_counter()
        state, metrics = await turn.analyze_end_of_turn()
        result.update(vad_states=sorted(states), smart_turn_state=str(state),
                      first_energy_ms=first_energy, first_vad_speaking_ms=first_speaking,
                      smart_turn_ms=round((time.perf_counter() - began) * 1000))
    if whisper:
        from backend.app.pipeline.stt import make_stt
        began = time.perf_counter()
        stt = make_stt()
        result["stt"] = type(stt).__name__
        result["whisper_load_ms"] = round((time.perf_counter() - began) * 1000)
        if audio_path:
            began = time.perf_counter()
            # Use the same underlying faster-whisper model as WhisperSTTService.
            import numpy as np
            segments, info = stt._model.transcribe(np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768, language="ru")
            result["transcript"] = " ".join(segment.text.strip() for segment in segments)
            result["stt_ms"] = round((time.perf_counter() - began) * 1000)
    await turn.cleanup()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio")
    parser.add_argument("--whisper", action="store_true", help="Load/download the configured Whisper model")
    parser.add_argument("--fast", action="store_true", help="Use selected-avatar VAD parameters")
    args = parser.parse_args()
    asyncio.run(check(args.audio, args.whisper, args.fast))
