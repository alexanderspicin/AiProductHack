"""Separate loopback defense demo. Never imports the main trainer or its keys."""
import argparse
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GRAPH = REPO / "artifacts/runs/07_avatar_graph"
sys.path.insert(0, str(GRAPH))
from audio_driver import Driver
from runtime import select_states
from media_http import send_file

VOICES = {
    "piper": {"name": "Piper · Дмитрий", "license": "Piper: GPL-3.0; датасет голоса: CC0"},
    "silero": {"name": "Silero · Евгений", "license": "Silero v5.5: CC BY-NC-SA 4.0, некоммерческое использование"},
}


def validate_request(data):
    if not isinstance(data, dict):
        raise ValueError("Нужен объект JSON")
    text, voice = data.get("text"), data.get("voice")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise ValueError("Введите от 1 до 500 символов")
    if voice not in VOICES:
        raise ValueError("Выберите Piper или Silero")
    return text.strip(), voice


class Engine:
    def __init__(self, args):
        self.args = args
        self.meta = json.loads((args.package / "manifest.json").read_text())
        self.driver = Driver(args.package / "audio_driver.onnx")
        self.slots = threading.BoundedSemaphore(1)
        self.cache = OrderedDict()
        self.models = {"piper": args.piper, "silero": args.silero}
        args.clips.mkdir(parents=True, exist_ok=True)

    def speak(self, text, voice):
        key = (text, voice)
        if key in self.cache:
            self.cache.move_to_end(key)
            return {**self.cache[key], "cached": True, "prepare_s": 0}
        if not self.models[voice].is_file():
            raise ValueError("Модель не найдена локально. См. инструкцию запуска; автозагрузка отключена.")
        start = time.perf_counter()
        ident = uuid.uuid4().hex
        wav = self.args.clips / f"{ident}.wav"
        # No credentials/proxies inherited. Worker network operations are blocked too.
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TMPDIR", "SYSTEMROOT"}}
        env.update({"OMP_NUM_THREADS": "2", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        try:
            result = subprocess.run([
                str(self.args.tts_python), str(HERE / "tts_worker.py"), "--voice", voice,
                "--model", str(self.models[voice]), "--output", str(wav),
            ], input=json.dumps({"text": text}), text=True, capture_output=True, timeout=45, env=env)
            if result.returncode:
                raise RuntimeError("Локальный TTS не запустился. Проверьте зависимости и модель в инструкции.")
            tts_wall = time.perf_counter() - start
            controls, silent, timing = self.driver.wav(wav)
            if silent.all():
                raise ValueError("Модель вернула тишину. Попробуйте другую фразу или голос.")
            states, metrics = select_states(controls, self.meta)
            data = {"audio": f"/clips/{ident}.wav", "states": states.tolist(), "metrics": metrics,
                    "timing": timing, "tts_s": tts_wall, "prepare_s": time.perf_counter() - start,
                    "voice": voice, "cached": False, "external_calls": 0}
            self.cache[key] = data
            # Keep only recent local demo phrases. No submitted text saved to disk.
            while len(self.cache) > 12:
                self.cache.popitem(last=False)
            recent = sorted(self.args.clips.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in recent[24:]:
                if all(Path(v["audio"]).name != old.name for v in self.cache.values()):
                    old.unlink(missing_ok=True)
            return data
        except Exception:
            wav.unlink(missing_ok=True)
            raise


def make_handler(engine):
    args = engine.args
    allowed = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}

    class Handler(BaseHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def reply(self, status, data, head=False):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def host_ok(self):
            return self.headers.get("Host") in allowed

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if not self.host_ok():
                return self.reply(403, {"error": "Loopback host required"}, head)
            target = urlparse(self.path).path
            if target == "/status":
                return self.reply(200, {"voices": [{"id": k, **v, "available": engine.models[k].is_file()}
                                                   for k, v in VOICES.items()], "external_calls": 0}, head)
            files = {"/": HERE / "index.html", "/player.js": HERE / "player.js", "/demo.css": HERE / "demo.css",
                     "/motion.js": GRAPH / "motion.js", "/manifest.json": args.package / "manifest.json"}
            if target in files:
                file = files[target]
            elif re.fullmatch(r"/assets/(base/\d{3}\.jpg|atlas/\d{3}\.png)", target):
                file = args.package / target[len("/assets/"):]
            elif re.fullmatch(r"/clips/[a-f0-9]{32}\.wav", target):
                file = args.clips / target.rsplit("/", 1)[1]
            else:
                return self.reply(404, {"error": "Not found"}, head)
            if not file.is_file():
                return self.reply(404, {"error": "Local file unavailable"}, head)
            send_file(self, file, head=head)

        def do_POST(self):
            if not self.host_ok() or self.headers.get("Origin", f"http://127.0.0.1:{args.port}") not in {f"http://{h}" for h in allowed}:
                return self.reply(403, {"error": "Origin rejected"})
            if self.path != "/speak":
                return self.reply(404, {"error": "Not found"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "Expected JSON"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Некорректный размер запроса")
                self.connection.settimeout(10)
                text, voice = validate_request(json.loads(self.rfile.read(length)))
            except (ValueError, TypeError, TimeoutError):
                return self.reply(400, {"error": "Выберите голос и введите от 1 до 500 символов"})
            if not engine.slots.acquire(blocking=False):
                return self.reply(429, {"error": "Предыдущая фраза ещё рассчитывается. Подождите несколько секунд."})
            try:
                self.reply(200, engine.speak(text, voice))
            except (ValueError, RuntimeError) as error:
                self.reply(503, {"error": str(error)})
            except subprocess.TimeoutExpired:
                self.reply(504, {"error": "Локальный TTS не уложился в 45 секунд. Попробуйте короткую фразу."})
            except Exception:
                self.reply(500, {"error": "Ошибка локального движка. Проверьте окружение из инструкции."})
            finally:
                engine.slots.release()

        def log_message(self, fmt, *values):
            pass  # No body, text, paths or tokens in HTTP logs.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    legacy = REPO.parent / "avatar_trainer"
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--package", type=Path, default=REPO / "artifacts/private/07_avatar_graph/package")
    parser.add_argument("--clips", type=Path, default=REPO / "artifacts/private/17_offline_defense/clips")
    parser.add_argument("--tts-python", type=Path, default=legacy / ".venv/bin/python")
    parser.add_argument("--piper", type=Path, default=legacy / "models/piper/ru_RU-dmitri-medium.onnx")
    parser.add_argument("--silero", type=Path, default=legacy / "models/silero/v5_5_ru.pt")
    args = parser.parse_args()
    if not args.tts_python.is_file():
        parser.error("TTS environment missing; supply --tts-python. See demos/offline/README.md")
    if not (args.package / "manifest.json").is_file():
        parser.error("Prepared atlas missing; supply --package. No automatic downloads.")
    engine = Engine(args)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    print(f"Offline defense demo: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
