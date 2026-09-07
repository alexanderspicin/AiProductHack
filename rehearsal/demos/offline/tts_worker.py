"""One bounded local synthesis. Only explicitly supplied, already cached weights."""
import argparse
import json
from pathlib import Path
import sys
import time
import wave


def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("Network access disabled in offline TTS worker")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", choices=["piper", "silero"], required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(no_network)
    text = json.load(sys.stdin)["text"]
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise ValueError("Expected 1–500 characters")
    if not args.model.is_file():
        raise ValueError("Local model missing; automatic downloads disabled")
    start = time.perf_counter()
    if args.voice == "piper":
        from piper import PiperVoice
        voice = PiperVoice.load(str(args.model))
        with wave.open(str(args.output), "wb") as output:
            voice.synthesize_wav(text, output)
    else:
        import torch
        torch.set_num_threads(2)
        model = torch.package.PackageImporter(str(args.model)).load_pickle("tts_models", "model")
        audio = model.apply_tts(text=text, speaker="eugene", sample_rate=24000)
        pcm = audio.detach().cpu().clamp(-1, 1).mul(32767).to(torch.int16).numpy().tobytes()
        with wave.open(str(args.output), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(pcm)
    print(json.dumps({"tts_s": time.perf_counter() - start}), flush=True)


if __name__ == "__main__":
    main()
